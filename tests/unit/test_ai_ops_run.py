"""Unit tests for tools/ai_ops_run.py — the main run() entry point.

Tests the run() function: provider fallback, planned path, resume policy,
engine delegation, exit codes, and delivery outbox. Complements the selftest
wrapper with granular assertions.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import ai_ops_run


@pytest.mark.critical_path
@pytest.mark.unit
class TestPlannedPath:
    """Tests for the planned path — run() with controller engine."""

    def test_planned_status(self, child_root):
        """run() with engine=controller should return planned status."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        report = ai_ops_run.run(
            task_text="fix a typo",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="test-planned",
            engine="controller",
        )
        assert report["status"] == "planned"

    def test_planned_writes_artifacts(self, child_root):
        """Planned path should write WorkItem and RunPlan to disk."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        report = ai_ops_run.run(
            task_text="test task",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="test-artifacts",
            engine="controller",
        )
        wid = report["workitem_id"]
        features_dir = child_root / "features" / wid
        assert (features_dir / "workitem.yaml").is_file()
        assert (features_dir / "run-plan.yaml").is_file()
        assert (features_dir / "run-report.json").is_file()


@pytest.mark.critical_path
@pytest.mark.unit
class TestNamedFeatureBinding:
    """Tests for feature naming — workitem_id derivation."""

    def test_named_feature(self, child_root):
        """feature='library-view' should bind to that name."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        report = ai_ops_run.run(
            task_text="add library view",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="library-view",
            engine="controller",
        )
        assert report["workitem_id"] == "library-view"

    def test_unnamed_feature_gets_hash(self, child_root):
        """Without feature name, workitem_id should be wi-<hash>."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        report = ai_ops_run.run(
            task_text="test task",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            engine="controller",
        )
        assert report["workitem_id"].startswith("wi-")


@pytest.mark.critical_path
@pytest.mark.unit
class TestExitCode:
    """Tests for exit_code() — CLI exit code derivation."""

    def test_exit_code_ready(self):
        """ready_for_pr=True should return exit code 0."""
        report = {"kind": "execution-pipeline", "status": "done", "ready_for_pr": True, "overall_status": "delivered"}
        assert ai_ops_run.exit_code(report) == 0

    def test_exit_code_blocked(self):
        """ready_for_pr=False should return exit code 1."""
        report = {"kind": "execution-pipeline", "status": "blocked", "ready_for_pr": False}
        assert ai_ops_run.exit_code(report) == 1

    def test_exit_code_error(self):
        """status=error should return exit code 2."""
        report = {"kind": "execution-pipeline", "status": "error"}
        assert ai_ops_run.exit_code(report) == 2

    def test_exit_code_delivery_failed(self):
        """overall_status=delivery-failed should return exit code 1."""
        report = {"kind": "execution-pipeline", "status": "done", "ready_for_pr": True, "overall_status": "delivery-failed"}
        assert ai_ops_run.exit_code(report) == 1


@pytest.mark.critical_path
@pytest.mark.unit
class TestEnginePipeline:
    """Tests for engine=pipeline — delegation to execution_pipeline."""

    def test_pipeline_engine_delegates(self, child_root):
        """engine=pipeline should delegate to execution_pipeline.run_pipeline."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = ai_ops_run.run(
            task_text="test task",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="test-pipeline",
            engine="pipeline",
            proposer=mock_proposer,
        )
        assert report["kind"] == "execution-pipeline"
        assert "gates" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFallback:
    """Tests for _with_provider_fallback — retryable infra failure handling."""

    def test_fallback_on_timeout(self):
        """Retryable infra failure should trigger fallback provider."""
        def primary(prompt):
            raise TimeoutError("connection timeout")

        def secondary(prompt):
            return "fallback response"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        result = wrapped("test prompt")
        assert result == "fallback response"

    def test_non_retryable_not_caught(self):
        """Non-retryable errors should propagate, not trigger fallback."""
        def primary(prompt):
            raise ValueError("invalid input")

        def secondary(prompt):
            return "fallback"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        with pytest.raises(ValueError):
            wrapped("test")

    def test_no_secondary_returns_primary(self):
        """secondary=None should return primary unwrapped."""
        def primary(prompt):
            return "primary"

        wrapped = ai_ops_run._with_provider_fallback(primary, None)
        assert wrapped is primary


@pytest.mark.critical_path
@pytest.mark.unit
class TestPrintHuman:
    """Tests for print_human — human-readable report output."""

    def test_print_human_no_crash(self, child_root):
        """print_human should not crash on pipeline reports."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test",
            "loop": {"stopped": "done"},
            "gates": {"blocked": False, "unmet_gates": []},
        }
        # Should not raise
        ai_ops_run.print_human(report)
