"""Гранулярные тесты context_hybrid (мигрировано из test_context_hybrid_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.context.context_hybrid import (
    Path,
    build_hybrid,
    build_hybrid_from_child,
)


@pytest.fixture
def ready_view():
    return {"included": [{"file": "a.py", "data_class": "internal"},
                          {"file": "b.py", "data_class": "internal"}],
            "excluded_access": [], "mandatory_missing": [], "mandatory_excluded_access": [],
            "cache_key": "repo:x|sha:s1|afp:A:1|dcp:D:1|allowed:h|role:executor",
            "sha": "s1", "total_tokens": 500}


@pytest.mark.unit
class TestBuildHybridReady:
    def test_mode_hybrid(self, ready_view):
        h = build_hybrid(["POLICY.md", "a.py"], ready_view, {"internal"}, 100000,
                         rule_refs=["core", "engineering"], policy_refs=["CHILD-AFP"])
        assert h["mode"] == "hybrid" and h["promotion_ready"]

    def test_v1_not_lost(self, ready_view):
        h = build_hybrid(["POLICY.md", "a.py"], ready_view, {"internal"}, 100000,
                         rule_refs=["core", "engineering"], policy_refs=["CHILD-AFP"])
        assert "POLICY.md" in h["context"] and "a.py" in h["context"]

    def test_mandatory_includes_rules_and_policy(self, ready_view):
        h = build_hybrid(["POLICY.md", "a.py"], ready_view, {"internal"}, 100000,
                         rule_refs=["core", "engineering"], policy_refs=["CHILD-AFP"])
        assert "rule:core" in h["mandatory_references"]
        assert "rule:engineering" in h["mandatory_references"]
        assert "policy:CHILD-AFP" in h["mandatory_references"]

    def test_v2_only_additions(self, ready_view):
        h = build_hybrid(["POLICY.md", "a.py"], ready_view, {"internal"}, 100000,
                         rule_refs=["core", "engineering"], policy_refs=["CHILD-AFP"])
        assert h["v2_additions"] == ["b.py"]
        assert h["context"] == ["POLICY.md", "a.py", "b.py"]


@pytest.mark.unit
class TestBuildHybridNotReady:
    def test_not_ready_v1_only(self, ready_view):
        bad_view = {**ready_view, "mandatory_missing": ["spec.md"]}
        h = build_hybrid(["POLICY.md"], bad_view, {"internal"}, 100000)
        assert h["mode"] == "v1-only" and h["promotion_ready"] is False

    def test_not_ready_no_additions(self, ready_view):
        bad_view = {**ready_view, "mandatory_missing": ["spec.md"]}
        h = build_hybrid(["POLICY.md"], bad_view, {"internal"}, 100000)
        assert h["v2_additions"] == [] and h["context"] == ["POLICY.md"] and h["violations"]


@pytest.mark.unit
class TestBuildHybridSecret:
    def test_secret_in_v2_rejected(self, ready_view):
        leak_view = {**ready_view, "included": [{"file": "s.py", "data_class": "secret"}]}
        h = build_hybrid(["POLICY.md"], leak_view, {"internal"}, 100000)
        assert h["mode"] == "v1-only"


@pytest.mark.unit
class TestBuildHybridFromChild:
    def test_from_child_hybrid(self, tmp_path):
        root = tmp_path
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount logic\ndef f():\n    return 1\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# policy discount\n", encoding="utf-8")
        afp = {"id": "T", "kind": "AccessFilterPolicy",
               "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}
        h = build_hybrid_from_child(root, "discount", "executor", sha="abc123", afp=afp,
                                    v1_mandatory=["POLICY.md"], require_snapshot=False)
        assert h["mode"] == "hybrid"
        assert "POLICY.md" in h["context"]
        assert h["execution_uses"] == "context_compiler_v1"
