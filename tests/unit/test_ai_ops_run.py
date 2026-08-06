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


@pytest.mark.critical_path
@pytest.mark.unit
class TestMainCli:
    """Tests for main() — CLI argument parsing and dispatch."""

    def test_main_with_no_task(self):
        """main() with no subcommand should return non-zero (argparse required=True)."""
        with pytest.raises(SystemExit):
            ai_ops_run.main([])

    def test_main_with_run_subcommand(self, child_root):
        """main(['run', ...]) should dispatch to run() and return an exit code."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "controller", "--json",
        ])
        assert isinstance(exit_code, int)

    def test_main_with_execute_flag(self, child_root):
        """main(['run', ..., '--execute']) should trigger pipeline execution."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "pipeline", "--execute", "--provider", "mock", "--json",
        ])
        assert isinstance(exit_code, int)


@pytest.mark.critical_path
@pytest.mark.unit
class TestRouteSelection:
    """Tests for task routing — QUICK vs ENGINEERING."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_quick_route_returns_planned(self, child_root):
        """QUICK task with controller engine -> planned status."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="fix typo",
            signals={"task_type": "QUICK", "size": "small", "risk": "low"},
            child_root=child_root,
            feature="quick-test",
            engine="controller",
        )
        assert report["status"] == "planned"

    def test_engineering_route_returns_planned(self, child_root):
        """ENGINEERING task with controller engine -> planned status."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="refactor module",
            signals={"task_type": "ENGINEERING", "size": "medium", "risk": "medium"},
            child_root=child_root,
            feature="eng-test",
            engine="controller",
        )
        assert report["status"] == "planned"


@pytest.mark.critical_path
@pytest.mark.unit
class TestArtifactWriting:
    """Tests for artifact writing — plan, workitem files created."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_artifact_writing_plan_and_workitem(self, child_root):
        """Controller path writes workitem.yaml, run-plan.yaml, and run-report.json."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="add feature",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="artifact-test",
            engine="controller",
        )
        wid = report["workitem_id"]
        features_dir = child_root / "features" / wid
        assert (features_dir / "workitem.yaml").is_file()
        assert (features_dir / "run-plan.yaml").is_file()
        assert (features_dir / "run-report.json").is_file()

    def test_run_report_is_valid_json(self, child_root):
        """run-report.json must be parseable JSON."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="test task",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            feature="json-test",
            engine="controller",
        )
        wid = report["workitem_id"]
        import json as _json
        report_path = child_root / "features" / wid / "run-report.json"
        data = _json.loads(report_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


@pytest.mark.critical_path
@pytest.mark.unit
class TestExitCodesExtended:
    """Extended exit code tests — covers more report shapes."""

    def test_exit_code_planned_is_zero(self):
        """Planned status (controller success) -> exit code 0."""
        report = {"status": "planned", "workitem_id": "test"}
        assert ai_ops_run.exit_code(report) == 0

    def test_exit_code_pipeline_error(self):
        """Pipeline status=error -> exit code 2."""
        report = {"kind": "execution-pipeline", "status": "error", "ready_for_pr": False}
        assert ai_ops_run.exit_code(report) == 2

    def test_exit_code_pipeline_not_ready(self):
        """Pipeline ready_for_pr=False -> exit code 1."""
        report = {"kind": "execution-pipeline", "status": "done", "ready_for_pr": False}
        assert ai_ops_run.exit_code(report) == 1


@pytest.mark.critical_path
@pytest.mark.unit
class TestReviewFixContext:
    """Tests for _review_fix_context — blocker context for writer iteration."""

    def test_returns_none_when_ready(self):
        """ready_for_pr=True -> no fix context needed."""
        report = {"ready_for_pr": True}
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_for_non_dict(self):
        """Non-dict input -> None."""
        assert ai_ops_run._review_fix_context(None) is None
        assert ai_ops_run._review_fix_context("string") is None

    def test_returns_none_for_preflight_blocked(self):
        """blocked-preflight -> not model-fixable -> None."""
        report = {"ready_for_pr": False, "overall_status": "blocked-preflight"}
        assert ai_ops_run._review_fix_context(report) is None
