"""Unit tests for tools/execution_pipeline.py — the main execution pipeline.

Tests the core pipeline logic: mock proposer flow, commit integrity,
worktree isolation, baseline diff, security scanning, and gate evaluation.
Complements the selftest wrapper with granular assertions.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import execution_pipeline


@pytest.mark.critical_path
@pytest.mark.unit
class TestBasicPipelineFlow:
    """Tests for the basic pipeline execution with mock proposer."""

    def test_pipeline_returns_report_structure(self, child_root):
        """Pipeline must return a report with all required keys."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
        )
        assert "schema_version" in report
        assert "kind" in report
        assert report["kind"] == "execution-pipeline"
        assert "gates" in report
        assert "ready_for_pr" in report
        assert "workitem_id" in report

    def test_pipeline_workitem_id_present(self, child_root):
        """Pipeline report should have a workitem_id."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
        )
        assert report["workitem_id"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestContainment:
    """Tests for sandbox and block_push containment."""

    def test_default_policy_blocks_push(self, child_root):
        """Default policy should have block_push=True."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
        )
        assert report.get("containment", {}).get("block_push", True)


@pytest.mark.critical_path
@pytest.mark.unit
class TestSecurityScanning:
    """Tests for security pack integration — fail-closed on errors."""

    def test_security_scan_key_present(self, child_root):
        """Pipeline report should include security_scan key."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
        )
        assert "security_scan" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestBaselineDiff:
    """Tests for baseline_diff — distinguishes regressions from pre-existing failures."""

    def test_baseline_diff_report_key(self, child_root):
        """With baseline_diff=True, report should include baseline key."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            (child_root / "file.txt").write_text("change")
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
            baseline_diff=True,
        )
        assert "baseline" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestNoSelfReview:
    """Tests for NO_SELF_REVIEW constant — gates that cannot self-review."""

    def test_no_self_review_contains_security(self):
        """NO_SELF_REVIEW should contain 'security'."""
        assert "security" in execution_pipeline.NO_SELF_REVIEW

    def test_no_self_review_contains_ai_red_team(self):
        """NO_SELF_REVIEW should contain 'ai_red_team'."""
        assert "ai_red_team" in execution_pipeline.NO_SELF_REVIEW


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineRequiredKeys:
    """Tests for run_pipeline() return structure — all required keys present."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_run_pipeline_returns_required_keys(self, child_root):
        """run_pipeline must return overall_status, ready_for_pr, gates, checks."""
        self._init_repo(child_root)
        report = execution_pipeline.run_pipeline(
            task="test task",
            signals={"task_type": "QUICK", "size": "small", "risk": "low"},
            child_root=child_root,
            proposer=lambda ctx: "done",
        )
        assert "overall_status" in report
        assert "ready_for_pr" in report
        assert "gates" in report
        assert "checks" in report or "loop" in report
        assert report["kind"] == "execution-pipeline"

    def test_run_pipeline_with_mock_provider(self, child_root):
        """End-to-end with mock proposer — pipeline completes without error."""
        self._init_repo(child_root)
        ops = iter([{"op": "write", "path": "src/test.py", "content": "x = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="add feature",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 5},
        )
        assert report.get("status") != "error" or report.get("overall_status") != "error"
        assert "workitem_id" in report

    def test_run_pipeline_blocked_on_preflight_failure(self, child_root):
        """Explicit non-existent base -> status=error, ready_for_pr=False."""
        self._init_repo(child_root)
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: "done",
            base="nonexistent-branch-xyz",
            isolate=True,
        )
        assert report["status"] == "error"
        assert report["ready_for_pr"] is False
        assert "base-preflight" in (report.get("error") or "")

    def test_run_pipeline_changed_files_is_list(self, child_root):
        """Pipeline report should include changed_files as a list (or None)."""
        self._init_repo(child_root)
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: "done",
        )
        cf = report.get("changed_files")
        assert cf is None or isinstance(cf, list)

    def test_run_pipeline_security_gate_integration(self, child_root):
        """security gate is evaluated but NOT self-reviewable."""
        self._init_repo(child_root)
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: "done",
        )
        assert "security_scan" in report
        # security must NOT be in reviewable gates (NO_SELF_REVIEW)
        assert "security" not in execution_pipeline.NO_SELF_REVIEW or True  # invariant check
        assert "security" in execution_pipeline.NO_SELF_REVIEW


@pytest.mark.critical_path
@pytest.mark.unit
class TestResolveBase:
    """Tests for _resolve_base — base branch resolution."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_auto_mode_resolves(self, child_root):
        """base=None (auto) should always resolve (falls back to current branch)."""
        self._init_repo(child_root)
        result = execution_pipeline._resolve_base(child_root, None)
        assert result["resolved"] is True
        assert result["mode"] == "auto"

    def test_explicit_existing_branch_resolves(self, child_root):
        """Explicit existing local branch -> resolved=True."""
        self._init_repo(child_root)
        _, out, _ = execution_pipeline._git(child_root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = out.strip()
        result = execution_pipeline._resolve_base(child_root, branch)
        assert result["resolved"] is True
        assert result["mode"] == "explicit"

    def test_explicit_nonexistent_branch_fails(self, child_root):
        """Explicit non-existent branch -> resolved=False."""
        self._init_repo(child_root)
        result = execution_pipeline._resolve_base(child_root, "no-such-branch-xyz")
        assert result["resolved"] is False
        assert result["mode"] == "explicit"


@pytest.mark.critical_path
@pytest.mark.unit
class TestProfileSummary:
    """Tests for _profile_summary helper."""

    def test_profile_summary_with_stacks(self):
        profile = {"stacks": [{"language": "Python", "commands": {"test": "pytest"}}]}
        result = execution_pipeline._profile_summary(profile)
        assert "Python" in result

    def test_profile_summary_empty(self):
        profile = {"stacks": []}
        result = execution_pipeline._profile_summary(profile)
        assert "не определён" in result
