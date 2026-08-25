"""Unit tests for tools/verification_tiers.py — tier selection and test targeting."""
from __future__ import annotations

import pytest

import verification_tiers


@pytest.mark.unit
class TestDecideTier:
    """Tests for decide_tier(): verification level from changed files."""

    def test_decide_tier_docs_only(self):
        """Documentation-only changes -> skip tier."""
        tier = verification_tiers.decide_tier(["README.md", "docs/guide.md"])
        assert tier == "skip"

    def test_decide_tier_infra_change(self):
        """Infrastructure change (orchestrator.py) -> full tier."""
        tier = verification_tiers.decide_tier(["tools/orchestrator.py"])
        assert tier == "full"

    def test_decide_tier_many_files(self):
        """More than 20 files -> module tier."""
        files = [f"tools/file{i}.py" for i in range(25)]
        tier = verification_tiers.decide_tier(files)
        assert tier == "module"

    def test_decide_tier_normal_file(self):
        """Normal file change -> affected tier."""
        tier = verification_tiers.decide_tier(["tools/usage_ledger.py"])
        assert tier == "affected"

    def test_decide_tier_force_overrides(self):
        """force_tier overrides automatic detection."""
        tier = verification_tiers.decide_tier(["README.md"], force_tier="full")
        assert tier == "full"

    def test_decide_tier_empty_changes(self):
        """No changed files -> skip."""
        tier = verification_tiers.decide_tier([])
        assert tier == "skip"

    def test_decide_tier_lifecycle_intent_explore(self):
        """lifecycle_intent=explore -> skip."""
        tier = verification_tiers.decide_tier(["tools/usage_ledger.py"],
                                              lifecycle_intent="explore")
        assert tier == "skip"

    def test_decide_tier_lifecycle_intent_merge(self):
        """lifecycle_intent=merge_candidate -> full."""
        tier = verification_tiers.decide_tier(["tools/usage_ledger.py"],
                                              lifecycle_intent="merge_candidate")
        assert tier == "full"

    def test_decide_tier_lifecycle_intent_draft(self):
        """lifecycle_intent=draft -> affected."""
        tier = verification_tiers.decide_tier(["tools/usage_ledger.py"],
                                              lifecycle_intent="draft")
        assert tier == "affected"

    def test_decide_tier_registry_is_full(self):
        """registry/ changes -> full tier."""
        tier = verification_tiers.decide_tier(["registry/tracks.yaml"])
        assert tier == "full"

    def test_decide_tier_lifecycle_intent_overrides_files(self):
        """lifecycle_intent takes precedence over file-based detection."""
        tier = verification_tiers.decide_tier(["tools/orchestrator.py"],
                                              lifecycle_intent="explore")
        assert tier == "skip"  # intent overrides even infra files


@pytest.mark.unit
class TestSelectTests:
    """Tests for select_tests(): test selection engine."""

    def test_select_tests_docs_returns_skip(self, tmp_path):
        result = verification_tiers.select_tests(["README.md"], str(tmp_path))
        assert result["tier"] == "skip"
        assert result["impact_status"] == verification_tiers.IMPACT_DOCS_ONLY

    def test_select_tests_returns_dict_with_required_keys(self, tmp_path):
        result = verification_tiers.select_tests(["tools/usage_ledger.py"], str(tmp_path))
        assert "tier" in result
        assert "changed_files" in result
        assert "impact_status" in result
        assert "note" in result

    def test_select_tests_full_for_infra(self, tmp_path):
        result = verification_tiers.select_tests(["tools/orchestrator.py"], str(tmp_path))
        assert result["tier"] == "full"
        assert result["full_command"] is True

    def test_select_tests_module_without_test_is_impact_unknown(self, tmp_path):
        """Module present but no targeting test -> impact_status=targeted_tests_not_found."""
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
        result = verification_tiers.select_tests(["tools/module.py"], str(tmp_path))
        assert result["impact_status"] == verification_tiers.IMPACT_TARGETED_TESTS_NOT_FOUND

    def test_select_tests_targeted_test_found_is_affected(self, tmp_path):
        """When the module's test exists: tier is affected, test lands in affected_tests,
        and impact_status reports the test was found."""
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
        (tmp_path / "tools" / "test_module.py").write_text(
            "import module\ndef test_func(): assert module.func() == 1\n", encoding="utf-8")
        result = verification_tiers.select_tests(["tools/module.py"], str(tmp_path))
        assert result["tier"] == "affected"
        assert "tools/test_module.py" in (result["affected_tests"] or [])
        assert result["impact_status"] == verification_tiers.IMPACT_TARGETED_TESTS_FOUND
