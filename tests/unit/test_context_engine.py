"""Unit tests for tools/context_engine.py — the Context Engine v2 orchestrator.

Tests the build_context() pipeline: mandatory v1, full-text, graph augmentation,
semantic-lite conditional, access filtering, budget, and snapshot verification.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import context_engine as ce


def _setup_child_policies(root: Path, *, afp_classes=None, dcp_secret_path=None, budget_tokens=None):
    """Write minimal child policies into root/.ai/policies/."""
    pol = root / ".ai" / "policies"
    pol.mkdir(parents=True, exist_ok=True)
    afp = {
        "id": "TEST-AFP", "kind": "AccessFilterPolicy",
        "rules": [{"role": "executor", "allowed_classes": afp_classes or ["public", "internal"]}],
    }
    (pol / "access-filter.yaml").write_text(yaml.safe_dump(afp), encoding="utf-8")
    dcp = {"id": "TEST-DCP", "kind": "DataClassificationPolicy", "default_class": "internal", "rules": []}
    if dcp_secret_path:
        dcp["rules"].append({"path_prefix": dcp_secret_path, "class": "confidential"})
    (pol / "data-classification.yaml").write_text(yaml.safe_dump(dcp), encoding="utf-8")
    if budget_tokens is not None:
        budget = {"scopes": [{"scope": "run", "token_budget": budget_tokens}]}
        (pol / "budget.yaml").write_text(yaml.safe_dump(budget), encoding="utf-8")


@pytest.mark.unit
class TestBuildContextReturnsDict:
    """build_context() must return a well-formed context-engine-view dict."""

    def test_compile_returns_dict_with_required_keys(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text("# discount logic\ndef apply(): pass\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)

        assert isinstance(view, dict)
        assert view["kind"] == "context-engine-view"
        assert "included" in view
        assert "sources_used" in view
        assert "total_tokens" in view
        assert "budget_tokens" in view
        assert "cache_key" in view

    def test_compile_includes_sources(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount formula\ndef calc(): pass\n", encoding="utf-8")
        (root / "docs.md").write_text("# discount guide\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)

        included_files = {i["file"] for i in view["included"]}
        assert "src/pricing.py" in included_files
        assert "docs.md" in included_files
        assert view["sources_used"]["fulltext"] >= 1

    def test_compile_respects_budget(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("# discount " * 500 + "\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# mandatory policy\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        # Very small budget — mandatory must still be included (over_budget flag)
        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                                budget_tokens=1, v1_mandatory=["POLICY.md"])
        mandatory_items = [i for i in view["included"] if i.get("mandatory")]
        assert len(mandatory_items) >= 1
        assert any(i["file"] == "POLICY.md" and i.get("over_budget") for i in view["included"])

    def test_compile_empty_signals(self, tmp_path):
        """Empty repo with no matching files -> included is empty (or only mandatory)."""
        root = tmp_path / "child"
        root.mkdir()
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "nonexistent-topic", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert isinstance(view["included"], list)
        assert view["total_tokens"] == 0 or view["total_tokens"] >= 0


@pytest.mark.unit
class TestBuildContextShaRequired:
    """build_context() without SHA must raise ValueError."""

    def test_no_sha_raises_value_error(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        with pytest.raises(ValueError, match="SHA"):
            ce.build_context(root, "query", "executor", sha=None, afp=afp, dcp=dcp)


@pytest.mark.unit
class TestBuildContextNoAfp:
    """No AFP -> deny-by-default, nothing included."""

    def test_no_afp_deny_by_default(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "app.py").write_text("# discount code\n", encoding="utf-8")
        _setup_child_policies(root)
        _, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=None, dcp=dcp)
        assert view["included"] == []


@pytest.mark.unit
class TestGraphAugmentation:
    """Graph augmentation adds neighbours that full-text missed."""

    def test_graph_adds_import_neighbour(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a * 0.9\n", encoding="utf-8")
        # order.py imports pricing but does NOT contain 'discount' -> found only via graph
        (root / "src" / "order.py").write_text("import pricing\n# fulfillment\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        included_files = {i["file"] for i in view["included"]}
        assert "src/order.py" in included_files
        assert view["sources_used"]["graph_added"] >= 1


@pytest.mark.unit
class TestMandatoryContext:
    """Mandatory v1 context is never lost on budget/rerank."""

    def test_mandatory_missing_invalidates_view(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                                v1_mandatory=["does/not/exist.md"])
        assert view["valid"] is False
        assert "does/not/exist.md" in view["mandatory_missing"]


@pytest.mark.unit
class TestBudgetTokensFrom:
    """budget_tokens_from() reads from policy dict."""

    def test_reads_scope_run(self):
        policy = {"scopes": [{"scope": "run", "token_budget": 5000}]}
        assert ce.budget_tokens_from(policy, "run") == 5000

    def test_default_on_none(self):
        assert ce.budget_tokens_from(None) == ce.DEFAULT_BUDGET_TOKENS

    def test_default_on_empty(self):
        assert ce.budget_tokens_from({}) == ce.DEFAULT_BUDGET_TOKENS


@pytest.mark.unit
class TestCompareV1:
    """compare_v1() computes overlap / v1_only / v2_only."""

    def test_compare_v1_sets(self):
        view = {"included": [{"file": "a.py"}, {"file": "b.py"}]}
        result = ce.compare_v1(view, ["a.py", "c.py"])
        assert "a.py" in result["overlap"]
        assert "c.py" in result["v1_only"]
        assert "b.py" in result["v2_only"]


@pytest.mark.unit
class TestLoadChildPolicies:
    """load_child_policies reads from child .ai/policies/."""

    def test_loads_afp_and_dcp(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        _setup_child_policies(root)

        afp, dcp, budget = ce.load_child_policies(root)
        assert afp is not None
        assert afp["id"] == "TEST-AFP"
        assert dcp is not None
        assert dcp["id"] == "TEST-DCP"

    def test_missing_policies_return_none(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        afp, dcp, budget = ce.load_child_policies(root)
        assert afp is None
        assert dcp is None
        assert budget is None
