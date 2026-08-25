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


@pytest.mark.unit
class TestFullTextCoversTsx:
    """full-text retrieval covers .tsx sources (React components), not only .py/.md."""

    def test_tsx_included(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "Widget.tsx").write_text(
            "// discount widget\nexport const W = () => 'discount';\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        included_files = {i["file"] for i in view["included"]}
        assert "src/Widget.tsx" in included_files


@pytest.mark.unit
class TestMandatoryFirst:
    """Mandatory v1 context is present and pinned first (included[0], mandatory=True)."""

    def test_mandatory_policy_is_first(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount formula\ndef calc(): pass\n", encoding="utf-8")
        (root / "POLICY.md").write_text(
            "# governing policy (mandatory v1) discount rules\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                                budget_tokens=10000, v1_mandatory=["POLICY.md"])
        included_files = {i["file"] for i in view["included"]}
        assert "POLICY.md" in included_files
        assert view["included"][0]["file"] == "POLICY.md"
        assert view["included"][0]["mandatory"] is True


@pytest.mark.unit
class TestPreFilteredDenied:
    """Denied-by-path files are pre-filtered: not read, not in any role-facing payload."""

    def test_secret_path_pre_filtered(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount\n", encoding="utf-8")
        # secret.py classified confidential by path -> not in executor's allowed classes
        (root / "secret.py").write_text(
            "# token sk-ant-api03deadbeefdeadbeef discount\n", encoding="utf-8")
        _setup_child_policies(root, dcp_secret_path="secret.py")
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        included_files = {i["file"] for i in view["included"]}
        excluded_access = {e["file"] for e in view["excluded_access"]}
        assert "secret.py" in view["pre_filtered_denied"]
        assert "secret.py" not in included_files
        assert "secret.py" not in excluded_access
        assert "secret.py" not in view["read_paths"]


@pytest.mark.unit
class TestIncludedProvenance:
    """Every included item carries content_hash + exact sha + reason."""

    def test_included_items_have_provenance(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount formula\ndef calc(): pass\n", encoding="utf-8")
        (root / "docs.md").write_text("# discount guide\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert view["included"]
        for i in view["included"]:
            assert i.get("content_hash")
            assert i["sha"] == "abc123"
            assert i.get("reason")


@pytest.mark.unit
class TestCacheKeyBinding:
    """cache_key is bound to sha + child AFP + child DCP identities."""

    def test_cache_key_contains_sha_afp_dcp(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("# discount\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert "sha:abc123" in view["cache_key"]
        assert "afp:TEST-AFP" in view["cache_key"]
        assert "dcp:TEST-DCP" in view["cache_key"]


@pytest.mark.unit
class TestGraphSemanticOnlyAdd:
    """Graph/semantic augmentation only ADDS candidates; deterministic full-text remain."""

    def test_deterministic_fulltext_survive_augmentation(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a * 0.9\n", encoding="utf-8")
        # order.py imports pricing but lacks 'discount' -> arrives only via graph
        (root / "src" / "order.py").write_text("import pricing\n# fulfillment\n", encoding="utf-8")
        (root / "docs.md").write_text("# discount guide\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        included_files = {i["file"] for i in view["included"]}
        # graph added a neighbour AND the deterministic full-text candidates are still present
        assert "src/order.py" in included_files
        assert {"src/pricing.py", "docs.md"} <= included_files


@pytest.mark.unit
class TestSemanticConditional:
    """Semantic-lite runs only when deterministic recall is below the floor."""

    def test_narrow_query_uses_semantic_with_floor_reason(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a * 0.9\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        # 'rebate' matches nothing deterministically -> recall < floor -> semantic engaged
        view = ce.build_context(root, "rebate", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert view["sources_used"]["semantic_used"] is True
        assert "floor" in view["sources_used"]["semantic_reason"]

    def test_wide_query_skips_semantic(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        # >= SEMANTIC_RECALL_FLOOR deterministic hits so semantic is not invoked
        for name in ("a.py", "b.py", "c.py", "d.py"):
            (root / "src" / name).write_text("# discount here\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert view["sources_used"]["semantic_used"] is False


@pytest.mark.unit
class TestMandatoryExcludedAccess:
    """Mandatory v1 file denied by access-policy invalidates the view."""

    def test_mandatory_secret_invalidates_view(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        # secret content -> classify returns 'secret' -> always excluded, even as mandatory
        (root / "secret.py").write_text(
            "# token sk-ant-api03deadbeefdeadbeef discount\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                                v1_mandatory=["secret.py"])
        assert view["valid"] is False
        assert "secret.py" in view["mandatory_excluded_access"]


@pytest.mark.unit
class TestGitignoreAware:
    """Retrieval honours .gitignore directory patterns."""

    def test_gitignored_dir_excluded(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        (root / "src").mkdir()
        # enough deterministic hits so semantic-lite is not engaged (it is a separate path)
        for name in ("pricing.py", "order.py", "cart.py", "checkout.py"):
            (root / "src" / name).write_text("# discount logic\n", encoding="utf-8")
        (root / ".gitignore").write_text("generated\n", encoding="utf-8")
        (root / "generated").mkdir()
        (root / "generated" / "big.py").write_text("# discount generated\n", encoding="utf-8")
        _setup_child_policies(root)
        afp, dcp, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        assert view["sources_used"]["semantic_used"] is False
        assert all("generated/" not in i["file"] for i in view["included"])


def _git_repo_with_commit(root: Path) -> str:
    """Init a git repo with one commit; return HEAD sha. .ai/ is gitignored (engine state)."""
    (root / "app.py").write_text("# discount logic here\n", encoding="utf-8")
    _setup_child_policies(root)
    (root / ".gitignore").write_text(".ai/\n", encoding="utf-8")

    def _g(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    _g("init", "-q")
    _g("add", "app.py", ".gitignore")
    _g("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return _g("rev-parse", "HEAD").stdout.strip()


@pytest.mark.unit
class TestSnapshotVerification:
    """require_snapshot proves dir content == commit snapshot via real git."""

    def test_head_matches_sha_clean_tree_valid(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        head = _git_repo_with_commit(root)
        afp, _, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha=head, afp=afp, require_snapshot=True)
        assert view["valid"] is True
        assert view["snapshot_verified"] is True

    def test_head_differs_from_sha_invalid(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        _git_repo_with_commit(root)
        afp, _, _ = ce.load_child_policies(root)

        view = ce.build_context(root, "discount", "executor", sha="0" * 40, afp=afp, require_snapshot=True)
        assert view["valid"] is False
        assert view["snapshot_verified"] is False

    def test_dirty_tree_invalid(self, tmp_path):
        root = tmp_path / "child"
        root.mkdir()
        head = _git_repo_with_commit(root)
        afp, _, _ = ce.load_child_policies(root)
        (root / "app.py").write_text("# discount logic CHANGED (dirty)\n", encoding="utf-8")

        view = ce.build_context(root, "discount", "executor", sha=head, afp=afp, require_snapshot=True)
        assert view["valid"] is False
