"""Unit tests for tools/workitem.py — WorkItem creation and status derivation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.lifecycle import workitem


@pytest.mark.unit
class TestWorkItemStart:
    """Tests for start(): creating a new WorkItem."""

    def test_start_creates_workitem_file(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "test-feat", "fix a typo")
        assert wi["kind"] == "workitem"
        assert wi["id"] == "test-feat"
        assert wi["status"] == "draft"
        assert workitem.wi_path(str(features), "test-feat").is_file()

    def test_start_has_required_paths(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "add feature")
        assert set(wi["paths"]) == {"blueprint", "run_state", "workitem"}

    def test_start_has_workflow(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "task", task_type="bug")
        assert wi["workflow"]  # non-empty, routed

    def test_start_has_lifecycle_intent(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "task")
        assert wi.get("lifecycle_intent") == "discovery"

    def test_start_writes_valid_yaml(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        workitem.start(str(features), "demo", "task")
        data = yaml.safe_load(workitem.wi_path(str(features), "demo").read_text(encoding="utf-8"))
        assert data["kind"] == "workitem"
        assert data["id"] == "demo"


@pytest.mark.unit
class TestDeriveStatus:
    """Tests for derive_status(): deterministic status from gate evidence."""

    def test_quick_without_evidence_needs_more(self):
        result = workitem.derive_status("QUICK", Path("/nonexistent"), {})
        assert result["status"] == "needs_more_evidence"

    def test_quick_with_full_evidence_is_done(self):
        evidence = {
            "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "pass",
                "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
        }
        result = workitem.derive_status("QUICK", Path("/nonexistent"), evidence)
        assert result["status"] == "done"

    def test_real_gate_failure_is_blocked(self):
        evidence = {
            "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "fail", "blockers": ["tests failed"]},
        }
        result = workitem.derive_status("QUICK", Path("/nonexistent"), evidence)
        assert result["status"] == "blocked"

    def test_status_result_has_schema(self):
        result = workitem.derive_status("QUICK", Path("/nonexistent"), {})
        assert result["schema_version"] == 1
        assert result["kind"] == "workitem-status"
        assert "action" in result
        assert "lifecycle_intent" in result

    def test_unclosed_human_approval_needs_human_decision(self):
        """Перенесено из монолита (прополка): если все машинные гейты pass, но остался незакрытый
        human-approval — статус needs_human_decision, а не done. Гранулярно проверялись
        needs_more_evidence/done/blocked, но эта ветвь — нет."""
        ge = workitem.gate_executor
        gates = ge.load_gates()
        for wid, w in ge.load_workflows().items():
            gs = w.get("quality_gates", []) or []
            human = [g for g in gs if ge.classify(gates[g]) == "human-approval"]
            if not human:
                continue
            # закрываем все НЕ-human гейты, human оставляем открытым
            ev = {g: {"status": "pass", "provided": list(gates[g].get("required_evidence", []) or [])}
                  for g in gs if g not in human}
            result = workitem.derive_status(wid, Path("/nonexistent"), ev)
            assert result["status"] == "needs_human_decision", (wid, human, result["status"])
            return
        pytest.skip("нет workflow с human-approval гейтом")
