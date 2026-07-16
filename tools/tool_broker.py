#!/usr/bin/env python3
"""Tool Broker + Policy Engine (v2.36, Execution Engine Фаза 2, срез 2).

Голый API-рантайм (generic-orchestrator) не имеет своего tool loop — раньше модель лишь
возвращала текст. Здесь — контролируемое исполнение: модель ПРЕДЛАГАЕТ действие, а
разрешено ли оно, решает Policy Engine (уровни из security/permission-levels.yaml +
write_scope + config/protected-paths.yaml), НЕ модель. Broker исполняет только
разрешённое и собирает Evidence (команда, exit_code, ревизия, что тронуто).

Инвариант: execute() ВСЕГДА вызывает decide() первым и отказывает, если запрещено —
обойти политику через прямой вызов нельзя.

Действие: {"op": read|write|shell|git, "path": ..., "command": ..., "content": ...}.

Использование (программно; интегрируется в tools/orchestrator.py):
  from tool_broker import Policy, execute
  pol = Policy(level="controlled-write", write_scope=["src/"])
  ev = execute({"op": "write", "path": "src/a.ts", "content": "..."}, root, pol)

  tool_broker.py --selftest
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]

# уровни по возрастанию (security/permission-levels.yaml order)
LEVEL_ORDER = ["read-only", "controlled-write", "execution", "network", "privileged", "destructive"]
# что минимально требует операция
OP_MIN_LEVEL = {"read": "read-only", "write": "controlled-write", "shell": "execution", "git": "execution"}

# необратимые/опасные shell/git паттерны -> требуют уровня destructive + approval
DESTRUCTIVE_RE = re.compile(
    r"(rm\s+-rf|rm\s+-fr|\bmkfs\b|\bdd\s+if=|:\(\)\s*\{|>\s*/dev/sd|chmod\s+-R\s+777|"
    r"git\s+push\s+.*(--force|-f)\b|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f|"
    r"drop\s+table|truncate\s+table|curl[^|]*\|\s*(sh|bash)|force-with-lease)", re.I)


def _load(rel):
    try:
        return yaml.safe_load((PKG / rel).read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _norm_entry(e, default_appr="required"):
    """Принимает как {path, approval}, так и строку 'path/' -> (prefix, approval)."""
    if isinstance(e, str):
        return (e.strip().rstrip("/"), default_appr) if e.strip() else None
    if isinstance(e, dict) and e.get("path"):
        return (str(e["path"]).rstrip("/"), e.get("approval", default_appr))
    return None


def _protected_prefixes(child_root=None):
    """Дефолт пакета + карта child'а (MERGE, не replace): child ДОБАВЛЯЕт к
    универсально-опасным путям, не отменяя их. Источники child'а:
      1. <child>/.ai-ops.yaml -> protected_paths (список строк) — единый источник;
      2. <child>/config/protected-paths.yaml (если есть) — как у пакета.
    Так Policy знает реальную карту репозитория (finding обкатки v2.36)."""
    out, seen = [], set()

    def add(entry):
        n = _norm_entry(entry)
        if n and n[0] and n[0] not in seen:
            seen.add(n[0]); out.append(n)

    for e in _load("config/protected-paths.yaml").get("protected_paths", []) or []:
        add(e)
    if child_root:
        child_root = Path(child_root)
        cfg = child_root / ".ai-ops.yaml"
        if cfg.exists():
            try:
                data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                for e in data.get("protected_paths", []) or []:
                    add(e)
            except (OSError, yaml.YAMLError):
                pass
        cpp = child_root / "config" / "protected-paths.yaml"
        if cpp.exists():
            try:
                for e in (yaml.safe_load(cpp.read_text(encoding="utf-8")) or {}).get("protected_paths", []) or []:
                    add(e)
            except (OSError, yaml.YAMLError):
                pass
    return out


def _under(path: str, prefix: str) -> bool:
    p = path.strip("/")
    pre = prefix.strip("/")
    return p == pre or p.startswith(pre + "/")


class Policy:
    def __init__(self, level="controlled-write", write_scope=None, confidentiality="internal",
                 approvals=None, child_root=None):
        if level not in LEVEL_ORDER:
            raise ValueError(f"неизвестный уровень '{level}'")
        self.level = level
        self.write_scope = [s.strip("/") for s in (write_scope or [])]
        self.confidentiality = confidentiality
        self.approvals = set(approvals or [])   # набор одобренных ярлыков (напр. {'destructive'})
        # protected = дефолт пакета MERGE карта child'а (.ai-ops.yaml protected_paths)
        self.protected = _protected_prefixes(child_root)

    def _level_ok(self, required):
        return LEVEL_ORDER.index(self.level) >= LEVEL_ORDER.index(required)

    def decide(self, action: dict) -> dict:
        op = action.get("op")
        if op not in OP_MIN_LEVEL:
            return {"allow": False, "reason": f"неизвестная операция '{op}'"}
        if not self._level_ok(OP_MIN_LEVEL[op]):
            return {"allow": False,
                    "reason": f"op '{op}' требует уровень >= {OP_MIN_LEVEL[op]}, текущий {self.level}"}

        if op == "read":
            return {"allow": True, "reason": "чтение в пределах репозитория"}

        if op == "write":
            path = (action.get("path") or "").strip("/")
            if not path:
                return {"allow": False, "reason": "write без path"}
            # protected path -> нужен privileged + approval
            for pre, appr in self.protected:
                if _under(path, pre):
                    if self._level_ok("privileged") and "protected_path_write" in self.approvals:
                        return {"allow": True, "reason": f"protected '{pre}' + approval"}
                    return {"allow": False,
                            "reason": f"protected path '{pre}' ({appr}) — нужен privileged + approval"}
            # вне write_scope -> запрет
            if self.write_scope and not any(_under(path, s) for s in self.write_scope):
                return {"allow": False,
                        "reason": f"'{path}' вне write_scope {self.write_scope}"}
            return {"allow": True, "reason": "запись в пределах write_scope"}

        # shell / git
        cmd = action.get("command") or ""
        if DESTRUCTIVE_RE.search(cmd):
            if self._level_ok("destructive") and "destructive" in self.approvals:
                return {"allow": True, "reason": "destructive + approval"}
            return {"allow": False,
                    "reason": "необратимая/опасная команда — нужен уровень destructive + approval"}
        return {"allow": True, "reason": f"{op} в пределах уровня {self.level}"}


def _revision(root):
    rc = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                        capture_output=True, text=True)
    return rc.stdout.strip() if rc.returncode == 0 else None


def execute(action: dict, root, policy: Policy) -> dict:
    """Единственная точка исполнения. ВСЕГДА проверяет policy.decide() первым."""
    root = Path(root)
    d = policy.decide(action)
    ev = {"op": action.get("op"), "target": action.get("path") or action.get("command"),
          "allowed": d["allow"], "reason": d["reason"], "revision": _revision(root)}
    if not d["allow"]:
        ev["ok"] = False
        return ev   # запрещено — НИЧЕГО не исполняем

    op = action["op"]
    try:
        if op == "read":
            p = root / action["path"]
            text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
            ev.update({"ok": p.exists(), "bytes": len(text.encode("utf-8")),
                       "output_tail": text[-400:]})
        elif op == "write":
            p = root / action["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(action.get("content", ""), encoding="utf-8")
            ev.update({"ok": True, "bytes": len(action.get("content", "").encode("utf-8"))})
        else:  # shell / git
            r = subprocess.run(action["command"], shell=True, cwd=str(root),
                               capture_output=True, text=True)
            ev.update({"ok": r.returncode == 0, "exit_code": r.returncode,
                       "command": action["command"],
                       "output_tail": (r.stdout + r.stderr)[-400:]})
    except (OSError, KeyError) as e:
        ev.update({"ok": False, "error": str(e)})
    return ev


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "init"])

        cw = Policy(level="controlled-write", write_scope=["src/"])
        expect("read разрешён", cw.decide({"op": "read", "path": "src/a.ts"})["allow"])
        expect("write в scope разрешён", cw.decide({"op": "write", "path": "src/b.ts"})["allow"])
        expect("write вне scope запрещён", not cw.decide({"op": "write", "path": "config/x.yaml"})["allow"])
        expect("write в protected (security/) запрещён",
               not cw.decide({"op": "write", "path": "security/x.yaml"})["allow"])
        expect("shell на controlled-write запрещён (нужен execution)",
               not cw.decide({"op": "shell", "command": "echo hi"})["allow"])

        # инвариант: execute запрещённого НЕ создаёт файл
        ev = execute({"op": "write", "path": "config/x.yaml", "content": "y"}, root, cw)
        expect("execute запрещённого -> allowed:false и файл не создан",
               ev["allowed"] is False and not (root / "config" / "x.yaml").exists())

        # разрешённая запись -> evidence с ревизией
        ev2 = execute({"op": "write", "path": "src/b.ts", "content": "hello"}, root, cw)
        expect("write выполнен + evidence с revision",
               ev2["ok"] and (root / "src" / "b.ts").exists() and ev2["revision"])

        ex = Policy(level="execution", write_scope=["src/"])
        expect("shell на execution разрешён", ex.decide({"op": "shell", "command": "echo hi"})["allow"])
        ev3 = execute({"op": "shell", "command": "echo hi"}, root, ex)
        expect("shell выполнен, exit_code 0", ev3["ok"] and ev3["exit_code"] == 0)
        expect("destructive shell запрещён без destructive+approval",
               not ex.decide({"op": "shell", "command": "rm -rf /"})["allow"])
        expect("git force-push запрещён",
               not ex.decide({"op": "git", "command": "git push --force origin main"})["allow"])

        dp = Policy(level="destructive", write_scope=["src/"], approvals=["destructive"])
        expect("destructive + approval разрешает опасную команду",
               dp.decide({"op": "shell", "command": "rm -rf build/"})["allow"])

    # v2.37: child-override protected-paths (finding обкатки — Policy знает карту child'а)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai-ops.yaml").write_text(
            "kind: ai-ops-child-config\nprotected_paths: [.github/workflows/]\n", encoding="utf-8")
        # write_scope включает .github/, но child объявил его protected
        cw = Policy(level="controlled-write", write_scope=[".github/", "src/"], child_root=root)
        expect("child protected (.github/workflows/) запрещён, хоть и в scope",
               not cw.decide({"op": "write", "path": ".github/workflows/ci.yml"})["allow"])
        expect("не-protected путь в scope по-прежнему разрешён",
               cw.decide({"op": "write", "path": "src/x.ts"})["allow"])
        expect("дефолт пакета сохраняется (merge, не replace): security/ запрещён",
               not cw.decide({"op": "write", "path": "security/x.yaml"})["allow"])
        # без child_root старое поведение: .github/ не защищён дефолтом
        no_child = Policy(level="controlled-write", write_scope=[".github/"])
        expect("без child_root .github/ не protected (дефолт пакета)",
               no_child.decide({"op": "write", "path": ".github/workflows/ci.yml"})["allow"])

    print("tool_broker selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
