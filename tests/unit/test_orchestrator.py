"""Unit tests for tools/orchestrator.py — workflow orchestration.

Tests the core orchestration logic: state persistence, role-prompt isolation,
workflow execution with mock provider, gate evaluation, budget enforcement,
and audit logging. Complements the selftest wrapper with granular assertions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import orchestrator


@pytest.mark.critical_path
@pytest.mark.unit
class TestStatePersistence:
    """Tests for load_state / save_state round-trip."""

    def test_save_and_load_state(self, child_root):
        """save_state writes valid YAML that load_state can read back."""
        run_dir = child_root / ".ai" / "runtime" / "test-run"
        run_dir.mkdir(parents=True)
        state = {
            "schema_version": 1,
            "status": "in-progress",
            "workflow": "QUICK",
            "goal": "fix a typo",
            "completed_checks": ["stage-1"],
            "artifacts": [],
        }
        orchestrator.save_state(run_dir, state)
        loaded = orchestrator.load_state(run_dir)
        assert loaded is not None
        assert loaded["status"] == "in-progress"
        assert loaded["workflow"] == "QUICK"
        assert loaded["completed_checks"] == ["stage-1"]

    def test_load_state_returns_none_when_missing(self, tmp_path):
        """load_state returns None if TaskState.yaml doesn't exist."""
        result = orchestrator.load_state(tmp_path / "nonexistent")
        assert result is None

    def test_save_state_creates_file(self, child_root):
        """save_state creates TaskState.yaml in the run directory."""
        run_dir = child_root / ".ai" / "runtime" / "run-x"
        run_dir.mkdir(parents=True)
        orchestrator.save_state(run_dir, {"status": "done"})
        assert (run_dir / "TaskState.yaml").is_file()


@pytest.mark.critical_path
@pytest.mark.unit
class TestBuildRolePrompt:
    """Tests for prompt isolation — judge stages must be read-only."""

    def test_judge_prompt_contains_read_only_guard(self, child_root):
        """Judge stage prompts must contain 'read-only' instruction."""
        agents_index = {}
        prompt = orchestrator.build_role_prompt(
            stage={"id": "review", "review_mode": "read-only"},
            agent_id="judge",
            agents_index=agents_index,
            task_text="fix the bug",
            published={},
        )
        assert "read-only" in prompt.lower() or "read-only" in prompt

    def test_prompt_includes_task_text(self, child_root):
        """The task text must appear in the generated prompt."""
        prompt = orchestrator.build_role_prompt(
            stage={"id": "implement"},
            agent_id="worker",
            agents_index={},
            task_text="implement feature X",
            published={},
        )
        assert "implement feature X" in prompt

    def test_prompt_includes_published_artifacts_only(self, child_root):
        """Only published artifact paths should appear, not internal reasoning."""
        prompt = orchestrator.build_role_prompt(
            stage={"id": "review"},
            agent_id="reviewer",
            agents_index={},
            task_text="task",
            published={"stage-1.md": "content1", "stage-2.md": "content2"},
        )
        assert "stage-1.md" in prompt
        assert "stage-2.md" in prompt


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunWorkflowQuick:
    """Tests for run_workflow with the QUICK workflow."""

    def test_quick_without_evidence_is_blocked(self, child_root):
        """QUICK workflow without gate evidence should end blocked."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo in README",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        assert state["status"] == "blocked"
        assert "unmet_gates" in state
        assert len(state["unmet_gates"]) > 0

    def test_quick_with_evidence_is_done(self, child_root):
        """QUICK workflow with full evidence should complete successfully."""
        evidence = {
            "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "pass", "provided": [
                "build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"
            ]},
        }
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo in README",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            gate_evidence=evidence,
            fresh=True,
        )
        assert state["status"] == "done"
        assert len(state.get("completed_checks", [])) > 0

    def test_quick_produces_gate_report(self, child_root):
        """run_workflow must write GateReport.json to the run directory."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        gate_report = Path(run_dir) / "GateReport.json"
        assert gate_report.is_file()
        report = json.loads(gate_report.read_text())
        assert "blocked" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestBudgetEnforcement:
    """Tests for execution budget limiting workflow stages."""

    def test_budget_limits_stages(self, child_root):
        """With max_model_calls=1, only one stage should complete."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            budget={"max_model_calls": 1},
            fresh=True,
        )
        assert state["status"] == "blocked"
        assert state.get("budget_exceeded")


@pytest.mark.critical_path
@pytest.mark.unit
class TestAuditLog:
    """Tests for the append-only interaction log."""

    def test_audit_log_appends_per_workflow(self, child_root):
        """Each workflow run appends exactly one JSONL record."""
        orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="task one",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="task two",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        log_path = child_root / ".ai" / "runtime" / "interaction-log.jsonl"
        assert log_path.is_file()
        lines = [l for l in log_path.read_text().strip().split("\n") if l.strip()]
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert "ts" in record
        assert "workflow" in record
        assert "status" in record
        assert "provider" in record


@pytest.mark.critical_path
@pytest.mark.unit
class TestHandoffIsolation:
    """Tests for TaskHandoff.json — only published artifacts, no leakage."""

    def test_handoff_contains_only_artifact_paths(self, child_root):
        """TaskHandoff.json must reference only stage artifact paths."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        handoff_path = Path(run_dir) / "TaskHandoff.json"
        if handoff_path.is_file():
            handoff = json.loads(handoff_path.read_text())
            for artifact in handoff.get("published_artifacts", []):
                assert "stage-" in artifact or ".ai/runtime/" in artifact


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderAdapter:
    """Tests for make_provider() — honest errors for missing credentials."""

    def test_mock_provider_resolves(self):
        """make_provider('mock') should return the mock provider."""
        provider = orchestrator.make_provider("mock")
        assert provider is not None
        result = provider("test prompt")
        assert isinstance(result, str)

    def test_unknown_provider_exits(self):
        """make_provider('bogus') should raise SystemExit."""
        with pytest.raises(SystemExit):
            orchestrator.make_provider("bogus")
