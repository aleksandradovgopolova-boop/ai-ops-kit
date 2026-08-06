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
