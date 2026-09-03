"""Гранулярные тесты context_shadow (мигрировано из test_context_shadow_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import yaml

import pytest

from ai_ops_kit.context.context_shadow import (
    Path,
    build_shadow,
    ce,
    compare,
)


def _mkrepo(root, with_policies=True):
    (root / "src").mkdir(parents=True)
    (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9  # discount\n", encoding="utf-8")
    (root / "src" / "order.py").write_text("import pricing\n# discount order flow\n", encoding="utf-8")
    (root / ".gitignore").write_text(".ai/\n", encoding="utf-8")
    pol = root / ".ai" / "policies"
    pol.mkdir(parents=True)
    (pol / "state.py").write_text("# discount secret internal state\n", encoding="utf-8")
    if with_policies:
        (pol / "access-filter.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-AFP", "kind": "AccessFilterPolicy",
            "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}), encoding="utf-8")
        (pol / "data-classification.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-DCP", "kind": "DataClassificationPolicy", "default_class": "internal"}),
            encoding="utf-8")
        (pol / "budget.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-BUD", "kind": "BudgetContract",
            "scopes": [{"scope": "run", "token_budget": 15000}]}), encoding="utf-8")
    ce._git(root, "init", "-q")
    ce._git(root, "add", "src", ".gitignore")
    ce._git(root, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "init")
    _, head, _ = ce._git(root, "rev-parse", "HEAD")
    return head


@pytest.fixture
def shadow_repo(tmp_path):
    head = _mkrepo(tmp_path)
    return tmp_path, head


@pytest.mark.unit
class TestBuildShadow:
    def test_mode_shadow(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert sh["mode"] == "shadow" and sh["execution_uses"] == "context_compiler_v1"

    def test_valid_and_snapshot(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert sh["valid"] is True and sh["snapshot_verified"] is True

    def test_full_chain(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert sh["sources_used"]["fulltext"] >= 1
        assert "graph_added" in sh["sources_used"]

    def test_finds_pricing(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert "src/order.py" in sh["included"]

    def test_no_hidden_dirs(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert all(not f.startswith(".ai") for f in sh["included"])

    def test_budget_from_child(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert sh["budget_tokens"] == 15000

    def test_cache_key_pinned(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        assert f"sha:{head}" in sh["cache_key"] and "afp:CHILD-AFP" in sh["cache_key"]


@pytest.mark.unit
class TestCompare:
    def test_overlap_counted(self, shadow_repo):
        root, head = shadow_repo
        sh = build_shadow(root, "discount", role="executor", sha=head)
        cmp = compare(sh, ["src/pricing.py", "docs/legacy.md"])
        assert "src/pricing.py" in cmp["overlap"]
        assert "docs/legacy.md" in cmp["v1_only"]


@pytest.mark.unit
class TestShadowEdgeCases:
    def test_dirty_tree_invalid(self, shadow_repo):
        root, head = shadow_repo
        (root / "src" / "pricing.py").write_text("# dirty change\n", encoding="utf-8")
        sh = build_shadow(root, "discount", sha=head)
        assert sh["valid"] is False

    def test_no_sha_raises(self, shadow_repo):
        root, head = shadow_repo
        with pytest.raises(ValueError):
            build_shadow(root, "discount", sha=None)

    def test_no_child_policy_deny_by_default(self, tmp_path):
        head = _mkrepo(tmp_path, with_policies=False)
        sh = build_shadow(tmp_path, "discount", sha=head)
        assert sh["included_count"] == 0
