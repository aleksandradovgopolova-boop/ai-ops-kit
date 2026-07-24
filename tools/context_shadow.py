#!/usr/bin/env python3
"""context_shadow.py (v3.6.7) — SHADOW-режим ПОЛНОЙ Context Engine v2 рядом с боевым v1.

Ревью владельца: НЕ заменять старый Context Compiler сразу. Первый режим wiring — v1 (обязательный,
им и исполняем) + v2 shadow view рядом: сохранить оба, сравнить источники, execution по-прежнему на v1.

v3.6.7: shadow теперь строит ПОЛНУЮ v2-цепочку через `context_engine.build_context` (full-text +
Repository Graph augmentation + условный semantic-lite + access-filter + rerank + budget), на
политиках CHILD-репо (AFP + DataClassificationPolicy), а не на демо-политике кита. Без точного SHA
shadow НЕ строится. Раньше shadow звал только `build_view()` (full-text) на демо-AFP без DCP.

Shadow НЕ управляет прогоном: чистая наблюдаемость перед промоушеном retrieval в runtime.

CLI:  context_shadow.py <child_root> --query "..." [--role executor] [--sha SHA] | --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))
import context_engine as ce   # noqa: E402


def build_shadow(child_root, query, role="executor", sha=None, afp=None, dcp=None, budget=20000,
                 v1_mandatory=None):
    """Полная v2-цепочка в shadow. Политики — CHILD-репо (не демо). sha обязателен (иначе ValueError)."""
    if afp is None and dcp is None:
        afp, dcp, _ = ce.load_child_policies(child_root)
    view = ce.build_context(child_root, query, role, sha=sha, afp=afp, dcp=dcp,
                            budget_tokens=budget, v1_mandatory=v1_mandatory)
    return {"kind": "context-shadow", "mode": "shadow", "execution_uses": "context_compiler_v1",
            "role": role, "query": query, "sha": sha, "cache_key": view["cache_key"],
            "sources_used": view["sources_used"],
            "included": [i["file"] for i in view["included"]],
            "included_count": len(view["included"]), "total_tokens": view["total_tokens"],
            "excluded_access": len(view["excluded_access"]),
            "excluded_budget": len(view["excluded_budget"]),
            "mandatory_missing": view["mandatory_missing"]}


def compare(shadow: dict, v1_files) -> dict:
    """Сравнение источников v1 vs ПОЛНАЯ v2-цепочка: overlap / только в v1 / только в v2."""
    v2 = set(shadow.get("included", []))
    v1 = set(v1_files or [])
    return {"overlap": sorted(v1 & v2), "v1_only": sorted(v1 - v2), "v2_only": sorted(v2 - v1),
            "v1_count": len(v1), "v2_count": len(v2)}


def selftest():
    import tempfile
    import yaml
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9  # discount\n", encoding="utf-8")
        (root / "src" / "order.py").write_text("import pricing\n# discount order flow\n", encoding="utf-8")
        (root / ".ai").mkdir()
        (root / ".ai" / "state.py").write_text("# discount secret internal state\n", encoding="utf-8")
        # политики CHILD (не демо кита)
        pol = root / ".ai" / "policies"
        pol.mkdir()
        (pol / "access-filter.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-AFP", "kind": "AccessFilterPolicy",
            "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}), encoding="utf-8")
        (pol / "data-classification.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-DCP", "kind": "DataClassificationPolicy", "default_class": "internal"}),
            encoding="utf-8")

        sh = build_shadow(root, "discount", role="executor", sha="abc123")
        expect("shadow: mode=shadow, execution_uses=v1 (не управляет прогоном)",
               sh["mode"] == "shadow" and sh["execution_uses"] == "context_compiler_v1")
        expect("shadow строит ПОЛНУЮ цепочку (sources_used: fulltext + graph)",
               sh["sources_used"]["fulltext"] >= 1 and "graph_added" in sh["sources_used"])
        expect("shadow находит src/*.py по 'discount'", "src/order.py" in sh["included"])
        expect("shadow НЕ сканирует скрытые .ai/ (engine state вне контекста)",
               all(not f.startswith(".ai") for f in sh["included"]))
        expect("shadow.cache_key привязан к sha + child-политикам (exact-revision, no demo)",
               "sha:abc123" in sh["cache_key"] and "afp:CHILD-AFP" in sh["cache_key"])

        cmp = compare(sh, ["src/pricing.py", "docs/legacy.md"])
        expect("compare: overlap/v1_only/v2_only считаются",
               "src/pricing.py" in cmp["overlap"] and "docs/legacy.md" in cmp["v1_only"])

        # без точного SHA shadow НЕ строится
        try:
            build_shadow(root, "discount", sha=None)
            expect("без SHA shadow НЕ строится -> ValueError", False)
        except ValueError:
            expect("без SHA shadow НЕ строится -> ValueError", True)

        # нет child-политики -> deny-by-default (никакого demo-fallback в runtime)
        with tempfile.TemporaryDirectory() as td2:
            r2 = Path(td2)
            (r2 / "a.py").write_text("# discount here\n", encoding="utf-8")
            sh2 = build_shadow(r2, "discount", sha="x1")
            expect("нет child-AFP -> deny-by-default, ничего не включается (no demo policy в runtime)",
                   sh2["included_count"] == 0)

    print("context_shadow selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1

    def _opt(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    sh = build_shadow(args[0], _opt("--query", ""), _opt("--role", "executor"), _opt("--sha"))
    print(json.dumps(sh, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
