#!/usr/bin/env python3
"""context_retrieval.py (v3.6.1) — full-text retrieval + budgeted role context view.

Следующая ступень цепочки ContextArchitectureDecision (после Repository Graph Lite, v3.6.0):
детерминированный full-text поиск + сборка context view ПОД РОЛЬ с реальным применением
AccessFilterPolicy (v3.4.2) и token-бюджета (BudgetContract, v3.4.0). Всё ещё БЕЗ vector-DB
(семантика — позже в цепочке).

Инварианты цепочки (реализованы здесь):
  - access-filter ДО включения в view: файл класса, не разрешённого роли, НЕ попадает в контекст;
    секреты не попадают НИКОГДА (data_class=secret исключается всегда);
  - budget: включаем ранжированные файлы, пока не исчерпан token-бюджет (оценка chars/4);
  - provenance + cache_key = repository + sha + policy(role) + view (как в CAD).

CLI:  context_retrieval.py <root> --query "kw1 kw2" --role planner [--budget N] [--afp <file>] [--json]
      context_retrieval.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
_SECRET = re.compile(r"sk-ant-api03|sk-[A-Za-z0-9]{16,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY")
_DC_MARKER = re.compile(r"data-class:\s*(public|internal|confidential|secret)")


def classify(content: str) -> str:
    """Класс данных файла (lite): секрет по паттерну; явный маркер; иначе internal."""
    if _SECRET.search(content):
        return "secret"
    m = _DC_MARKER.search(content)
    return m.group(1) if m else "internal"


def _tokens(content: str) -> int:
    return max(1, len(content) // 4)   # грубая оценка токенов


def full_text_search(root, query: str, subdirs=("tools", "validation")):
    root = Path(root)
    kws = [k.lower() for k in query.split() if k.strip()]
    out = []
    for sd in subdirs:
        d = root / sd
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            try:
                content = f.read_text(encoding="utf-8")
            except OSError:
                continue
            low = content.lower()
            hits = {k: low.count(k) for k in kws}
            score = sum(hits.values())
            if score > 0:
                out.append({"file": str(f.relative_to(root)), "score": score, "hits": hits})
    out.sort(key=lambda r: (-r["score"], r["file"]))   # детерминированно
    return out


def role_allowed_classes(afp: dict, role: str):
    for r in afp.get("rules", []) or []:
        if r.get("role") == role:
            return set(r.get("allowed_classes") or [])
    return set()   # deny-by-default


def build_view(root, query: str, role: str, allowed_classes, budget_tokens: int, sha=None):
    root = Path(root)
    allowed = set(allowed_classes)
    included, excl_access, excl_budget = [], [], []
    total = 0
    for r in full_text_search(root, query):
        f = root / r["file"]
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        dc = classify(content)
        # access-filter ДО включения: секрет — никогда; класс вне allowed — исключить
        if dc == "secret" or dc not in allowed:
            excl_access.append({"file": r["file"], "data_class": dc})
            continue
        tk = _tokens(content)
        if total + tk <= budget_tokens:
            total += tk
            included.append({"file": r["file"], "data_class": dc, "tokens": tk, "score": r["score"]})
        else:
            excl_budget.append({"file": r["file"], "tokens": tk})
    return {"kind": "context-view", "role": role, "query": query,
            "cache_key": f"repo:{root.name}|sha:{sha or 'HEAD'}|policy:{role}|view:{role}",
            "included": included, "excluded_access": excl_access, "excluded_budget": excl_budget,
            "total_tokens": total, "budget_tokens": budget_tokens}


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "a.py").write_text("# keyword foo appears foo twice\ndef alpha():\n    return 'foo'\n", encoding="utf-8")
        (root / "tools" / "b.py").write_text("# data-class: confidential\n# foo here once\n", encoding="utf-8")
        (root / "tools" / "c.py").write_text("# foo but has a secret sk-ant-api03xxxxxxxx\n", encoding="utf-8")
        (root / "tools" / "d.py").write_text("# nothing relevant here\n", encoding="utf-8")

        res = full_text_search(root, "foo", ("tools",))
        expect("full-text: a.py ранжирован выше (больше hits), d.py не найден",
               res[0]["file"] == "tools/a.py" and all(r["file"] != "tools/d.py" for r in res))

        # planner: allowed {public, internal}
        v = build_view(root, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        inc = {i["file"] for i in v["included"]}
        exa = {e["file"] for e in v["excluded_access"]}
        expect("planner видит internal a.py", "tools/a.py" in inc)
        expect("planner НЕ видит confidential b.py (access-filter)", "tools/b.py" in exa)
        expect("секрет c.py исключён ВСЕГДА (никогда в контекст)", "tools/c.py" in exa)

        # executor: allowed adds confidential -> b.py включён, но c.py (secret) всё равно нет
        v2 = build_view(root, "foo", "executor", {"public", "internal", "confidential"}, 10000)
        inc2 = {i["file"] for i in v2["included"]}
        exa2 = {e["file"] for e in v2["excluded_access"]}
        expect("executor видит confidential b.py", "tools/b.py" in inc2)
        expect("секрет c.py исключён и для executor (secret никогда)", "tools/c.py" in exa2)

        # budget: крошечный бюджет -> часть уходит в excluded_budget
        vb = build_view(root, "foo", "executor", {"public", "internal", "confidential"}, budget_tokens=1)
        expect("бюджет=1 -> включён максимум один файл, остальное excluded_budget",
               len(vb["included"]) <= 1 and (len(vb["excluded_budget"]) >= 1 or len(vb["included"]) == 0)
               and vb["total_tokens"] <= 1)

        # deny-by-default: пустой allowed -> ничего не включается
        vd = build_view(root, "foo", "nobody", set(), 10000)
        expect("deny-by-default: allowed пуст -> included пуст", vd["included"] == [])

        expect("cache_key содержит repo+sha+policy+view",
               all(x in v["cache_key"] for x in ("repo:", "sha:", "policy:", "view:")))

    # интеграция с реальным AFP-001 (v3.4.2): роли резолвятся
    afp_p = PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"
    if afp_p.exists():
        afp = yaml.safe_load(afp_p.read_text(encoding="utf-8"))
        expect("AFP-001: planner -> {public, internal}",
               role_allowed_classes(afp, "planner") == {"public", "internal"})
        expect("AFP-001: security_reviewer включает confidential",
               "confidential" in role_allowed_classes(afp, "security_reviewer"))

    print("context_retrieval selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    root = args[0]

    def _opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    query = _opt("--query", "")
    role = _opt("--role", "planner")
    budget = int(_opt("--budget", "20000"))
    afp_path = _opt("--afp", str(PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"))
    afp = yaml.safe_load(Path(afp_path).read_text(encoding="utf-8")) if Path(afp_path).exists() else {}
    allowed = role_allowed_classes(afp, role)
    view = build_view(root, query, role, allowed, budget)
    if "--json" in argv:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(f"CONTEXT-VIEW [{role}] query='{query}' budget={budget}t used={view['total_tokens']}t")
        print(f"  included ({len(view['included'])}): {[i['file'] for i in view['included']]}")
        print(f"  excluded_access ({len(view['excluded_access'])}): {[e['file'] for e in view['excluded_access']]}")
        print(f"  excluded_budget ({len(view['excluded_budget'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
