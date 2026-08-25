"""Гранулярные тесты validate_engops_policy (миграция с селфтеста)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_engops_policy import (
    check_child,
    check_parity,
    check_policy,
)


# ---------------------------------------------------------------------------
# Policy basics
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestPolicy:

    def test_empty_policy_is_consistent(self):
        assert check_policy({}) == []

    def test_none_is_consistent(self):
        assert check_policy(None) == []

    def test_non_object_policy_rejected(self):
        assert check_policy(["x"]) != []

    def test_full_correct_policy_is_consistent(self):
        full = {"commit": {"enforce": "block", "max_files": 10},
                 "branch": {"enforce": "advise", "base_drift_advisory": 20,
                             "base_drift_stale": 100, "protected_refs": ["main"],
                             "branch_prefix": "ai-ops/"}}
        assert check_policy(full) == []

    def test_advisory_gte_stale_rejected(self):
        bad_order = {"branch": {"base_drift_advisory": 100, "base_drift_stale": 20}}
        assert any("не сработает никогда" in e for e in check_policy(bad_order))

    def test_advisory_eq_stale_rejected(self):
        assert check_policy({"branch": {"base_drift_advisory": 50, "base_drift_stale": 50}}) != []

    def test_enforce_outside_enum_rejected(self):
        assert any("enforce" in e for e in check_policy({"commit": {"enforce": "force"}}))

    def test_unknown_top_level_key_rejected(self):
        assert any("неизвестные ключи" in e for e in check_policy({"observability": {}}))

    def test_unknown_commit_key_rejected(self):
        assert any("неизвестные ключи" in e for e in check_policy({"commit": {"max_lines": 5}}))

    def test_zero_or_negative_threshold_rejected(self):
        assert (check_policy({"commit": {"max_files": 0}}) != []
                and check_policy({"branch": {"max_branch_age_days": -3}}) != [])

    def test_bool_instead_of_number_rejected(self):
        assert check_policy({"commit": {"max_files": True}}) != []

    def test_empty_protected_refs_rejected(self):
        assert any("непустой список" in e
                    for e in check_policy({"branch": {"protected_refs": []}}))

    def test_protected_refs_not_list_rejected(self):
        assert check_policy({"branch": {"protected_refs": "main"}}) != []

    def test_branch_prefix_equals_protected_branch_rejected(self):
        assert any("совпадает с защищённой" in e
                    for e in check_policy({"branch": {"branch_prefix": "main/",
                                                       "protected_refs": ["main"]}}))

    def test_empty_branch_prefix_rejected(self):
        assert check_policy({"branch": {"branch_prefix": "  "}}) != []


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestEnvironments:

    def test_environments_absent_is_consistent(self):
        assert check_policy({"environments": None}) == []

    def test_string_environments_are_consistent(self):
        assert check_policy({"environments": ["staging", "production"]}) == []

    def test_full_environment_declaration_is_consistent(self):
        ok_envs = {"environments": [{"name": "production", "kind": "production",
                                      "approvers": ["owner"],
                                      "secret_names": ["DEPLOY_TOKEN"]}]}
        assert check_policy(ok_envs) == []

    def test_environments_not_list_rejected(self):
        assert check_policy({"environments": {}}) != []

    def test_environment_without_name_rejected(self):
        assert check_policy({"environments": [{"kind": "staging"}]}) != []

    def test_duplicate_environment_rejected(self):
        assert any("дважды" in e
                    for e in check_policy({"environments": ["prod", "prod"]}))

    def test_unknown_environment_kind_rejected(self):
        assert check_policy({"environments": [{"name": "x", "kind": "чепуха"}]}) != []

    def test_unknown_environment_key_rejected(self):
        assert check_policy({"environments": [{"name": "x", "url": "https://x"}]}) != []

    def test_approvers_not_list_of_strings_rejected(self):
        assert check_policy({"environments": [{"name": "x", "approvers": "owner"}]}) != []

    def test_secret_values_rejected(self):
        errs = check_policy({"environments": [{"name": "x",
                                                 "secret_names": ["sk-abcdefghijklmnopqrstuvwx"]}]})
        assert any("значения запрещены" in e or "ЗНАЧЕНИЕ" in e for e in errs)

    def test_secret_names_with_space_or_hyphen_rejected(self):
        assert check_policy({"environments": [{"name": "x",
                                                 "secret_names": ["MY KEY"]}]}) != []


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestDeploy:

    def test_deploy_absent_is_consistent(self):
        assert check_policy({"deploy": None}) == []

    def test_deploy_command_with_rollback_consistent(self):
        assert check_policy({"deploy": {"deploy_command": "make deploy",
                                         "rollback": "make rollback"}}) == []

    def test_deploy_command_without_rollback_rejected(self):
        assert any("нельзя отменить" in e
                    for e in check_policy({"deploy": {"deploy_command": "make deploy"}}))

    def test_rollback_without_deploy_command_consistent(self):
        assert check_policy({"deploy": {"rollback": "make undo"}}) == []

    def test_deploy_not_object_rejected(self):
        assert check_policy({"deploy": []}) != []

    def test_unknown_deploy_key_rejected(self):
        assert check_policy({"deploy": {"strategy": "canary"}}) != []

    def test_empty_deploy_command_rejected(self):
        assert check_policy({"deploy": {"deploy_command": "  ", "rollback": "x"}}) != []

    def test_literal_secret_in_deploy_command_rejected(self):
        errs = check_policy({"deploy": {
            "deploy_command": "deploy --token ghp_abcdefghijklmnopqrstuvwxyz012345",
            "rollback": "undo"}})
        assert any("литеральный секрет" in e for e in errs)


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestEconomics:

    def test_economics_absent_is_consistent(self):
        assert check_policy({"economics": None}) == []

    def test_correct_economics_consistent(self):
        assert check_policy({"economics": {"enforce": "advise",
                                            "confirm_over_cost_usd": 5,
                                            "min_history_tasks": 3}}) == []

    def test_null_confirm_over_cost_consistent(self):
        assert check_policy({"economics": {"confirm_over_cost_usd": None}}) == []

    def test_economics_not_object_rejected(self):
        assert check_policy({"economics": []}) != []

    def test_unknown_economics_key_rejected(self):
        assert check_policy({"economics": {"max_cost": 5}}) != []

    def test_negative_confirm_threshold_rejected(self):
        assert check_policy({"economics": {"confirm_over_cost_usd": -1}}) != []

    def test_zero_min_history_tasks_rejected(self):
        assert check_policy({"economics": {"min_history_tasks": 0}}) != []

    def test_require_estimate_not_boolean_rejected(self):
        assert check_policy({"economics": {"require_estimate": "да"}}) != []

    def test_require_estimate_with_advise_contradiction(self):
        errs = check_policy({"economics": {"require_estimate": True, "enforce": "advise"}})
        assert any("противоречие" in e for e in errs)

    def test_require_estimate_with_block_consistent(self):
        assert check_policy({"economics": {"require_estimate": True, "enforce": "block"}}) == []


# ---------------------------------------------------------------------------
# Parity (rule ↔ code)
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestParity:

    def test_parity_of_real_files(self):
        assert check_parity() == []

    def test_threshold_drift_detected(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "rule.md"
            doc.write_text(
                "```yaml\nengineering_operating_model:\n  commit:\n    max_files: 999\n"
                "  branch:\n    base_drift_stale: 100\n```\n", encoding="utf-8")
            errs = check_parity(doc)
            assert any("дрейф commit.max_files" in e for e in errs)

    def test_uncovered_thresholds_detected(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "rule.md"
            doc.write_text(
                "```yaml\nengineering_operating_model:\n  commit:\n    max_files: 999\n"
                "  branch:\n    base_drift_stale: 100\n```\n", encoding="utf-8")
            errs = check_parity(doc)
            assert any("не описаны пороги" in e for e in errs)

    def test_rule_without_yaml_block_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "rule.md"
            doc.write_text("нет yaml-блока\n", encoding="utf-8")
            assert any("не найден yaml-блок" in e for e in check_parity(doc))

    def test_broken_yaml_block_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "rule.md"
            doc.write_text(
                "```yaml\nengineering_operating_model:\n  commit:\n   {{битый\n```\n",
                encoding="utf-8")
            assert check_parity(doc) != []

    def test_missing_rule_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            assert check_parity(Path(td) / "нет.md") != []


# ---------------------------------------------------------------------------
# Child repository policy
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.slow
class TestChild:

    def test_repo_without_ai_ops_yaml_only_parity(self):
        with tempfile.TemporaryDirectory() as td:
            assert check_child(Path(td)) == []

    def test_contradiction_in_child_ai_ops_yaml_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai-ops.yaml").write_text(
                "engineering_operating_model:\n  branch:\n    base_drift_advisory: 200\n"
                "    base_drift_stale: 100\n", encoding="utf-8")
            assert check_child(root) != []

    def test_correct_child_policy_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai-ops.yaml").write_text(
                "engineering_operating_model:\n  commit:\n    enforce: block\n",
                encoding="utf-8")
            assert check_child(root) == []

    def test_broken_child_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
            assert check_child(root) != []
