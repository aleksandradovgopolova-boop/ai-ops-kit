"""Селфтест context_hybrid, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_hybrid import (  # noqa: F401 — имена, которые использует тело
    Path,
    build_hybrid,
    build_hybrid_from_child,
)


@pytest.mark.slow
def test_context_hybrid_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # ready view -> hybrid, v1 не теряется, additions = v2 \ v1
    ready_view = {"included": [{"file": "a.py", "data_class": "internal"},
                               {"file": "b.py", "data_class": "internal"}],
                  "excluded_access": [], "mandatory_missing": [], "mandatory_excluded_access": [],
                  "cache_key": "repo:x|sha:s1|afp:A:1|dcp:D:1|allowed:h|role:executor",
                  "sha": "s1", "total_tokens": 500}
    h = build_hybrid(["POLICY.md", "a.py"], ready_view, {"internal"}, 100000,
                     rule_refs=["core", "engineering"], policy_refs=["CHILD-AFP"])
    expect("ready -> mode=hybrid", h["mode"] == "hybrid" and h["promotion_ready"])
    expect("v1 mandatory полностью в context (не потерян)",
           "POLICY.md" in h["context"] and "a.py" in h["context"])
    expect("mandatory включает applicable rules + policy references (ревью #3)",
           "rule:core" in h["mandatory_references"] and "rule:engineering" in h["mandatory_references"]
           and "policy:CHILD-AFP" in h["mandatory_references"])
    expect("v2 ТОЛЬКО добавляет: additions = b.py (a.py уже в v1 -> не дубль)",
           h["v2_additions"] == ["b.py"] and h["context"] == ["POLICY.md", "a.py", "b.py"])

    # not-ready view (mandatory потерян) -> v1-only, additions пусты, контекст = v1
    bad_view = {**ready_view, "mandatory_missing": ["spec.md"]}
    h2 = build_hybrid(["POLICY.md"], bad_view, {"internal"}, 100000)
    expect("promotion gate НЕ пройден -> mode=v1-only (fail-safe)",
           h2["mode"] == "v1-only" and h2["promotion_ready"] is False)
    expect("v1-only: additions пусты, context == v1 (execution не деградирует)",
           h2["v2_additions"] == [] and h2["context"] == ["POLICY.md"] and h2["violations"])

    # secret в v2 -> gate FAIL -> hybrid отклонён (v2 не протаскивает secret)
    leak_view = {**ready_view, "included": [{"file": "s.py", "data_class": "secret"}]}
    h3 = build_hybrid(["POLICY.md"], leak_view, {"internal"}, 100000)
    expect("secret в v2 -> hybrid отклонён (v1-only)", h3["mode"] == "v1-only")

    # from_child: реальный build_context -> hybrid
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount logic\ndef f():\n    return 1\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# policy discount\n", encoding="utf-8")
        afp = {"id": "T", "kind": "AccessFilterPolicy",
               "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}
        h4 = build_hybrid_from_child(root, "discount", "executor", sha="abc123", afp=afp,
                                     v1_mandatory=["POLICY.md"], require_snapshot=False)
        expect("from_child: mode=hybrid, POLICY.md в context, execution_uses=v1",
               h4["mode"] == "hybrid" and "POLICY.md" in h4["context"]
               and h4["execution_uses"] == "context_compiler_v1")

    assert ok, "перенесённый селфтест context_hybrid: см. строки FAIL в выводе"
