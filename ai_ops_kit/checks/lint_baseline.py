"""Базовая линия профиля стиля: существующее заморожено, новое краснеет, счётчик ходит вниз (#1183).

ЗАЧЕМ. Включение профиля на ии-среде нашло бы тысячи имён не латиницей в работающем коде. Требовать
переименовать всё в день включения — значит уронить main дочки, и профиль просто выключат. Поэтому
существующее ЗАМОРАЖИВАЕТСЯ счётчиком «файл × правило», новое сверх счётчика краснеет, исправленное
сокращает счётчик. Вырасти линия не может: рост и есть новое расхождение.

ЗАПУСК ИНСТРУМЕНТА — СНАРУЖИ. Модуль в слое primitives и процессов не запускает (AC-01): функцию
замера передаёт точка входа (`cli.lint_profile_cli.measure`), тесты — подделку.

ДВА МЕХАНИЗМА, ОДИН СМЫСЛ.
  * ESLint ≥ 9.24 — РОДНЫЕ массовые подавления (`--suppress-rule`, `--prune-suppressions`, файл
    `.ai/project/lint/eslint-suppressions.json`). Проверено на ESLint 10 ии-среды: превышение
    счётчика в файле возвращает ВСЕ находки этого правила в файле, неиспользованные подавления
    снимает `--prune-suppressions`. Родной механизм предпочтён своему: его понимают редакторы и
    сам ESLint, второй правды о тех же числах не появляется.
  * Прочие инструменты (Ruff, import-linter, golangci-lint, ast-grep) и ESLint старше 9.24 —
    файл кита `.ai/project/lint/baseline.json` той же формы (`{инструмент: {файл: {правило:
    {"count": N}}}}`) и сравнение, которое краснеет ТОЛЬКО на росте.

ПЕРЕЗАМОРОЗКА НЕ ПРОИСХОДИТ САМА. Повторное `--apply` линию не трогает: иначе рост можно было бы
«отмыть» пересборкой. Заморозить заново — осознанно, `--apply --force`, и это видно в диффе файла линии.
"""
from __future__ import annotations

import json
from pathlib import Path

from ai_ops_kit.checks import lint_profile as lp

BASELINE_REL = f"{lp.LINT_DIR}/baseline.json"
KIND = "ai-ops-lint-baseline"
ESLINT_NATIVE_MIN = (9, 24)

OK, GREW, NOT_CHECKED = "ok", "grew", "not_checked"


# ── Файл линии кита. ──────────────────────────────────────────────────────────────────────────
def load(child_root) -> dict:
    p = Path(child_root) / BASELINE_REL
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) and data.get("kind") == KIND else {}


def save(child_root, tools: dict) -> None:
    p = Path(child_root) / BASELINE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "kind": KIND,
            "note": "заморожено профилем стиля AI Ops: вправе только сокращаться "
                    "(./ai-ops lint-profile check --apply)",
            "tools": {t: _as_file(c) for t, c in sorted(tools.items())}}
    p.write_text(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")


def _as_file(counts: dict) -> dict:
    return {f: {r: {"count": n} for r, n in sorted(rules.items()) if n > 0}
            for f, rules in sorted(counts.items()) if any(n > 0 for n in rules.values())}


def _from_file(section: dict) -> dict:
    out = {}
    for f, rules in (section or {}).items():
        for r, v in (rules or {}).items():
            n = v.get("count", 0) if isinstance(v, dict) else v
            if isinstance(n, int) and n > 0:
                out.setdefault(f, {})[r] = n
    return out


def counts(findings) -> dict:
    """[(файл, правило, строка)] -> {файл: {правило: число}}."""
    out: dict = {}
    for f, r, _line in findings:
        out.setdefault(f, {}).setdefault(r, 0)
        out[f][r] += 1
    return out


# ── Сравнение: краснеет только рост. ──────────────────────────────────────────────────────────
def compare(frozen: dict, current: dict, findings=()) -> dict:
    """Линия против текущего замера. -> grown/shrunk + ужатая линия (рост в неё НЕ впитывается).

    Ключ, которого в линии нет, заморожен нулём: новый файл с находкой — рост. Ужатая линия —
    минимум из двух по каждому ключу; нули выбрасываются.
    """
    lines = {}
    for f, r, line in findings:
        lines.setdefault((f, r), []).append(line)
    grown, shrunk, tight = [], [], {}
    for f in sorted(set(frozen) | set(current)):
        for r in sorted(set(frozen.get(f, {})) | set(current.get(f, {}))):
            was, now = frozen.get(f, {}).get(r, 0), current.get(f, {}).get(r, 0)
            if now > was:
                grown.append({"file": f, "rule": r, "was": was, "now": now,
                              "lines": sorted(lines.get((f, r), []))[:10]})
            elif now < was:
                shrunk.append({"file": f, "rule": r, "was": was, "now": now})
            if min(was, now) > 0:
                tight.setdefault(f, {})[r] = min(was, now)
    return {"grown": grown, "shrunk": shrunk, "tightened": tight,
            "frozen": sum(n for rs in frozen.values() for n in rs.values()),
            "now": sum(n for rs in current.values() for n in rs.values())}


# ── Разбор вывода инструментов -> [(файл, правило, строка)]. ───────────────────────────────────
def _rel(root: Path, path: str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix() if p.is_absolute() else p.as_posix()
    except ValueError:
        return p.as_posix()


def parse_eslint(text: str, root, prefix: str = "ai-ops/") -> tuple:
    """JSON ESLint -> (неподавленные находки профиля, {(файл, правило): подавлено})."""
    root = Path(root)
    found, suppressed = [], {}
    for item in json.loads(text or "[]"):
        f = _rel(root, item.get("filePath", ""))
        for m in item.get("messages") or []:
            if str(m.get("ruleId") or "").startswith(prefix):
                found.append((f, m["ruleId"], m.get("line", 0)))
        for m in item.get("suppressedMessages") or []:
            if str(m.get("ruleId") or "").startswith(prefix):
                key = (f, m["ruleId"])
                suppressed[key] = suppressed.get(key, 0) + 1
    return found, suppressed


def parse_ruff(text: str, root, rules) -> list:
    root = Path(root)
    return [(_rel(root, d.get("filename", "")), d["code"], (d.get("location") or {}).get("row", 0))
            for d in json.loads(text or "[]")
            if d.get("code") and any(d["code"].startswith(r) for r in rules)]


def parse_golangci(text: str, root, linters) -> list:
    root = Path(root)
    data = json.loads(text or "{}") or {}
    return [(_rel(root, (i.get("Pos") or {}).get("Filename", "")), i.get("FromLinter"),
             (i.get("Pos") or {}).get("Line", 0))
            for i in data.get("Issues") or [] if i.get("FromLinter") in linters]


def parse_ast_grep(text: str, root) -> list:
    root = Path(root)
    return [(_rel(root, m.get("file", "")), m.get("ruleId", "ast-grep"),
             ((m.get("range") or {}).get("start") or {}).get("line", 0) + 1)
            for m in json.loads(text or "[]")]


def parse_import_linter(text: str) -> list:
    """Текст lint-imports -> находки: модуль-импортёр × «кто кому не разрешён» × строка."""
    found, contract = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.endswith(":") and " is not allowed to import " in line:
            contract = "import-linter:" + line[:-1].replace(" is not allowed to import ", "->")
        elif contract and line.startswith("-") and " -> " in line:
            importer = line.lstrip("- ").split(" -> ")[0].strip()
            lno = line.rsplit("(l.", 1)[-1].split(",")[0].rstrip(")") if "(l." in line else "0"
            found.append((importer, contract, int(lno) if lno.isdigit() else 0))
    return found


# ── Версия ESLint и состояние линии. ────────────────────────────────────────────────────────
def eslint_version(root) -> tuple:
    try:
        v = json.loads((Path(root) / "node_modules" / "eslint" / "package.json")
                       .read_text(encoding="utf-8")).get("version", "0")
        return tuple(int(x) for x in v.split(".")[:2])
    except (OSError, ValueError):
        return (0, 0)


def _native(root: Path, spec: dict) -> bool:
    return spec["tool"] == "eslint" and eslint_version(root) >= ESLINT_NATIVE_MIN


def _suppression_counts(root: Path, spec: dict) -> dict | None:
    p = root / spec["suppressions"]
    try:
        return _from_file(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else None
    except (OSError, ValueError):
        return None


# ── Заморозка и проверка. ─────────────────────────────────────────────────────────────────────
def freeze(child_root, tools: list, measure, force: bool = False) -> list:
    """Заморозить текущие находки профиля. Существующую линию без `force` не трогает (см. модуль).

    `measure(root, spec, extra) -> (находки|None, подавлено, причина)` — запуск инструмента. Он
    передаётся снаружи: процесс запускает точка входа (cli), а логика линии остаётся здесь, в
    слое без инфраструктуры (AC-01).
    """
    root = Path(child_root)
    kit = _from_kit(root)
    results = []
    for spec in tools:
        t = spec["tool"]
        if _native(root, spec):
            if _suppression_counts(root, spec) is not None and not force:
                results.append({"tool": t, "status": "kept"})
                continue
            if force:
                (root / spec["suppressions"]).unlink(missing_ok=True)
            (root / spec["suppressions"]).parent.mkdir(parents=True, exist_ok=True)
            extra = ["--suppressions-location", spec["suppressions"]]
            for r in spec.get("rules") or ["ai-ops/id-match", "ai-ops/no-restricted-imports"]:
                extra += ["--suppress-rule", r]
            found, _, why = measure(root, spec, extra)
            frozen = _suppression_counts(root, spec) or {}
            results.append({"tool": t, "status": NOT_CHECKED if found is None else "frozen",
                            "reason": why, "frozen": sum(sum(v.values()) for v in frozen.values()),
                            "native": True})
            continue
        if t in kit and not force:
            results.append({"tool": t, "status": "kept"})
            continue
        found, _, why = measure(root, spec)
        if found is None:
            results.append({"tool": t, "status": NOT_CHECKED, "reason": why})
            continue
        kit[t] = counts(found)
        results.append({"tool": t, "status": "frozen", "frozen": len(found), "native": False})
    if any(r["status"] == "frozen" and not r.get("native") for r in results):
        save(root, kit)
    return results


def _from_kit(root: Path) -> dict:
    return {t: _from_file(s) for t, s in (load(root).get("tools") or {}).items()}


def check(child_root, tools: list, measure, tighten: bool = False) -> dict:
    """Сверить текущее с линией. tighten — ужать линию под исправленное (рост не впитывается)."""
    root = Path(child_root)
    kit = _from_kit(root)
    rows, kit_changed = [], False
    for spec in tools:
        t = spec["tool"]
        native = _native(root, spec)
        frozen = _suppression_counts(root, spec) if native else kit.get(t)
        if frozen is None:
            rows.append({"tool": t, "status": NOT_CHECKED,
                         "reason": "линия не заморожена — сначала ./ai-ops lint-profile --apply"})
            continue
        extra = ["--suppressions-location", spec["suppressions"],
                 "--pass-on-unpruned-suppressions"] if native else []
        found, supp, why = measure(root, spec, extra)
        if found is None:
            rows.append({"tool": t, "status": NOT_CHECKED, "reason": why})
            continue
        if native:
            # Превышение счётчика ESLint возвращает ВСЕ находки правила в файле, в пределах — все
            # подавлены. Поэтому «стало» по ключу = подавленные + неподавленные.
            current: dict = {}
            for (f, r), n in supp.items():
                current.setdefault(f, {})[r] = n
            for f, rs in counts(found).items():
                for r, n in rs.items():
                    current.setdefault(f, {})[r] = current.get(f, {}).get(r, 0) + n
        else:
            current = counts(found)
        cmp = compare(frozen, current, found)
        row = {"tool": t, "status": GREW if cmp["grown"] else OK, "native": native, **cmp}
        if tighten and cmp["shrunk"] and not cmp["grown"]:
            if native:
                measure(root, spec, ["--suppressions-location", spec["suppressions"],
                                      "--prune-suppressions"])
            else:
                kit[t], kit_changed = cmp["tightened"], True
            row["tightened_applied"] = True
        rows.append(row)
    if kit_changed:
        save(root, kit)
    return {"status": _overall(rows), "tools": rows}


def _overall(rows: list) -> str:
    if any(r["status"] == GREW for r in rows):
        return GREW
    if not rows or all(r["status"] == NOT_CHECKED for r in rows):
        return NOT_CHECKED
    return "partial" if any(r["status"] == NOT_CHECKED for r in rows) else OK
