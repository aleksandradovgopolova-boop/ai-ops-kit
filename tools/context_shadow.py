#!/usr/bin/env python3
"""context_shadow.py (v3.6.4) — SHADOW-режим Context Engine v2 рядом с боевым v1.

Ревью владельца: НЕ заменять старый Context Compiler сразу. Первый режим wiring —
v1 (обязательный, им и исполняем) + v2 shadow view рядом: сохранить оба, сравнить источники,
execution по-прежнему на v1. Здесь — построение shadow-view поверх child-репо и сравнение с v1.

Shadow НЕ управляет прогоном: это чистая наблюдаемость перед промоушеном retrieval в runtime.

CLI:  context_shadow.py <child_root> --query "..." [--role executor] [--sha SHA] | --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))
import context_retrieval as cr   # noqa: E402

DEFAULT_AFP = PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"


def build_shadow(child_root, query, role="executor", sha=None, afp=None, budget=20000):
    allowed = cr.role_allowed_classes(afp, role) if afp else {"public", "internal"}
    view = cr.build_view(child_root, query, role, allowed, budget, sha=sha, subdirs=("",))
    return {"kind": "context-shadow", "mode": "shadow", "execution_uses": "context_compiler_v1",
            "role": role, "query": query, "sha": sha, "cache_key": view["cache_key"],
            "included": [i["file"] for i in view["included"]],
            "included_count": len(view["included"]), "total_tokens": view["total_tokens"],
            "excluded_access": len(view["excluded_access"]),
            "excluded_budget": len(view["excluded_budget"])}


def compare(shadow: dict, v1_files) -> dict:
    """Сравнение источников v1 vs v2-shadow: overlap / только в v1 / только в v2."""
    v2 = set(shadow.get("included", []))
    v1 = set(v1_files or [])
    return {"overlap": sorted(v1 & v2), "v1_only": sorted(v1 - v2), "v2_only": sorted(v2 - v1),
            "v1_count": len(v1), "v2_count": len(v2)}


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9\n", encoding="utf-8")
        (root / "src" / "order.py").write_text("import pricing\n# discount order flow\n", encoding="utf-8")
        (root / ".ai").mkdir()
        (root / ".ai" / "state.py").write_text("# discount secret internal state\n", encoding="utf-8")

        sh = build_shadow(root, "discount", role="executor", sha="abc123")
        expect("shadow: mode=shadow, execution_uses=v1 (не управляет прогоном)",
               sh["mode"] == "shadow" and sh["execution_uses"] == "context_compiler_v1")
        expect("shadow находит src/*.py по 'discount'",
               "src/order.py" in sh["included"])
        expect("shadow НЕ сканирует скрытые .ai/ (engine state вне контекста)",
               all(not f.startswith(".ai") for f in sh["included"]))
        expect("shadow.cache_key привязан к sha (exact-revision)", "sha:abc123" in sh["cache_key"])

        cmp = compare(sh, ["src/pricing.py", "docs/legacy.md"])
        expect("compare: overlap/v1_only/v2_only считаются",
               "src/pricing.py" in cmp["overlap"] and "docs/legacy.md" in cmp["v1_only"])

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
    afp = yaml.safe_load(DEFAULT_AFP.read_text(encoding="utf-8")) if DEFAULT_AFP.exists() else None
    sh = build_shadow(args[0], _opt("--query", ""), _opt("--role", "executor"), _opt("--sha"), afp)
    print(json.dumps(sh, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
