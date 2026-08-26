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


# ============================================================================
# NEW TESTS — targeting uncovered helper functions and pipeline paths
# ============================================================================

def _init_git(child_root):
    """Helper: init a git repo with one commit."""
    subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
    (child_root / "dummy.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)


@pytest.mark.unit
class TestIntakeEvidence:
    """Tests for _intake_evidence — evidence from signal classification."""

    def test_intake_evidence_with_all_signals(self):
        # mapping: classified_type->task_type, size->size, risk->risk
        signals = {"task_type": "QUICK", "size": "small", "risk": "low"}
        result = execution_pipeline._intake_evidence(signals)
        assert result is not None
        assert result["status"] == "pass"
        assert "classified_type" in result["provided"]
        assert "size" in result["provided"]
        assert "risk" in result["provided"]

    def test_intake_evidence_with_partial_signals(self):
        signals = {"size": "small"}
        result = execution_pipeline._intake_evidence(signals)
        assert result is not None
        assert result["status"] == "pass"
        assert "size" in result["provided"]
        assert "classified_type" not in result["provided"]

    def test_intake_evidence_with_no_signals(self):
        result = execution_pipeline._intake_evidence({})
        assert result is None

    def test_intake_evidence_with_none(self):
        result = execution_pipeline._intake_evidence(None)
        assert result is None


@pytest.mark.unit
class TestGateChecklist:
    """Tests for _gate_checklist — compact reviewer orientation."""

    def test_gate_checklist_with_evidence(self):
        gate = {"required_evidence": ["test_pass", "build_ok"], "responsible_role": "developer"}
        result = execution_pipeline._gate_checklist(gate)
        assert "developer" in result
        assert "test_pass" in result
        assert "build_ok" in result

    def test_gate_checklist_without_evidence(self):
        gate = {"responsible_role": "reviewer"}
        result = execution_pipeline._gate_checklist(gate)
        assert "reviewer" in result

    def test_gate_checklist_default_role(self):
        gate = {}
        result = execution_pipeline._gate_checklist(gate)
        assert "reviewer" in result


@pytest.mark.unit
class TestVerifyRemoteBase:
    """Tests for _verify_remote_base — remote base verification."""

    def test_no_base_ref_returns_unverifiable(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._verify_remote_base(child_root, None, "abc123")
        assert result["verdict"] == "unverifiable"

    def test_no_base_sha_returns_unverifiable(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._verify_remote_base(child_root, "main", None)
        assert result["verdict"] == "unverifiable"

    def test_no_origin_returns_unverifiable(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._verify_remote_base(child_root, "main", "abc123")
        assert result["verdict"] == "unverifiable"


@pytest.mark.unit
class TestChangeContext:
    """Tests for _change_context — diff context for reviewers."""

    def test_empty_revision_returns_empty(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._change_context(child_root, None) == ""
        assert execution_pipeline._change_context(child_root, "") == ""

    def test_valid_revision_returns_context(self, child_root):
        _init_git(child_root)
        (child_root / "new.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add new"], cwd=child_root, capture_output=True)
        rc, sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._change_context(child_root, sha.strip())
        assert "new.py" in result
        assert "x = 1" in result

    def test_invalid_revision_returns_empty(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._change_context(child_root, "nonexistent-sha-xyz")
        assert result == ""


@pytest.mark.unit
class TestChangeContextRange:
    """Tests for _change_context_range — integrated diff context."""

    def test_with_both_revisions(self, child_root):
        _init_git(child_root)
        rc, base_sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        base_sha = base_sha.strip()
        (child_root / "a.py").write_text("a = 1\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add a"], cwd=child_root, capture_output=True)
        (child_root / "b.py").write_text("b = 2\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add b"], cwd=child_root, capture_output=True)
        rc, head_sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._change_context_range(child_root, base_sha, head_sha.strip())
        assert "a.py" in result
        assert "b.py" in result

    def test_without_base_degrades_to_single(self, child_root):
        _init_git(child_root)
        (child_root / "single.py").write_text("s = 1\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add single"], cwd=child_root, capture_output=True)
        rc, head_sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._change_context_range(child_root, None, head_sha.strip())
        assert "single.py" in result


@pytest.mark.unit
class TestParseYamlBlock:
    """Tests for _parse_yaml_block — YAML extraction from model output."""

    def test_dict_passthrough(self):
        data = {"kind": "test"}
        assert execution_pipeline._parse_yaml_block(data) is data

    def test_fenced_yaml_block(self):
        text = "```yaml\nschema_version: 1\nkind: test\n```"
        result = execution_pipeline._parse_yaml_block(text)
        assert result is not None
        assert result["kind"] == "test"

    def test_yaml_without_fence(self):
        text = "Some prose\n\nschema_version: 1\nkind: requirements-artifact\nrequirements: []\n"
        result = execution_pipeline._parse_yaml_block(text)
        assert result is not None
        assert result["kind"] == "requirements-artifact"

    def test_multiple_fenced_blocks(self):
        text = "```text\nblah\n```\ntext\n```yaml\nschema_version: 1\nkind: plan-artifact\n```"
        result = execution_pipeline._parse_yaml_block(text)
        assert result is not None
        assert result["kind"] == "plan-artifact"

    def test_garbage_returns_none(self):
        result = execution_pipeline._parse_yaml_block("just text no yaml")
        assert result is None

    def test_none_input(self):
        result = execution_pipeline._parse_yaml_block(None)
        assert result is None

    def test_empty_string(self):
        result = execution_pipeline._parse_yaml_block("")
        assert result is None


@pytest.mark.unit
class TestEnvHelpers:
    """Tests for environment qualification helpers."""

    def test_env_proven_ok_with_pass(self):
        checks = {"test": {"status": "pass"}}
        assert execution_pipeline._env_proven_ok(checks) is True

    def test_env_proven_ok_with_honest_fail(self):
        checks = {"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 1,
                                                       "output_tail": "AssertionError"}]}}
        assert execution_pipeline._env_proven_ok(checks) is True

    def test_env_proven_ok_with_exit_127(self):
        checks = {"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 127}]}}
        assert execution_pipeline._env_proven_ok(checks) is False

    def test_env_proven_ok_with_module_not_found(self):
        checks = {"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 1,
                                                       "output_tail": "ModuleNotFoundError: No module named 'foo'"}]}}
        assert execution_pipeline._env_proven_ok(checks) is False

    def test_env_proven_ok_empty_checks(self):
        assert execution_pipeline._env_proven_ok({}) is False

    def test_env_proven_ok_not_run_only(self):
        checks = {"build": {"status": "not_run"}, "test": {"status": "not_run"}}
        assert execution_pipeline._env_proven_ok(checks) is False

    def test_env_unqualified_inverse(self):
        assert execution_pipeline._env_unqualified({"test": {"status": "pass"}}) is False
        assert execution_pipeline._env_unqualified({}) is True

    def test_check_has_env_symptom_exit_127(self):
        check = {"runs": [{"ok": False, "exit_code": 127}]}
        assert execution_pipeline._check_has_env_symptom(check) is True

    def test_check_has_env_symptom_command_not_found(self):
        check = {"runs": [{"ok": False, "exit_code": 1, "output_tail": "bash: command not found"}]}
        assert execution_pipeline._check_has_env_symptom(check) is True

    def test_check_has_env_symptom_no_symptom(self):
        check = {"runs": [{"ok": False, "exit_code": 1, "output_tail": "AssertionError"}]}
        assert execution_pipeline._check_has_env_symptom(check) is False

    def test_check_has_env_symptom_pass_skipped(self):
        check = {"runs": [{"ok": True, "exit_code": 0}]}
        assert execution_pipeline._check_has_env_symptom(check) is False


@pytest.mark.unit
class TestBaselineFailureSummary:
    """Tests for _baseline_failure_summary — failure context for model."""

    def test_summary_includes_failing_check(self):
        checks = {
            "test": {"status": "fail", "runs": [
                {"command": "pytest", "exit_code": 1, "ok": False,
                 "output_tail": "expected 'A' got 'B'"}]},
            "build": {"status": "pass", "runs": [{"command": "build", "ok": True}]}
        }
        result = execution_pipeline._baseline_failure_summary(checks)
        assert "expected 'A' got 'B'" in result
        assert "pytest" in result
        assert "build" not in result

    def test_summary_empty_for_all_pass(self):
        checks = {"test": {"status": "pass", "runs": [{"ok": True}]}}
        result = execution_pipeline._baseline_failure_summary(checks)
        assert result == ""


@pytest.mark.unit
class TestFailureSignal:
    """Tests for _failure_signal — severity metric from output."""

    def test_counts_failed(self):
        check = {"runs": [{"output_tail": "5 failed, 100 passed"}]}
        assert execution_pipeline._failure_signal(check) == 5

    def test_counts_errors(self):
        check = {"runs": [{"output_tail": "3 errors found"}]}
        assert execution_pipeline._failure_signal(check) == 3

    def test_takes_max_across_runs(self):
        check = {"runs": [
            {"output_tail": "2 failed"},
            {"output_tail": "8 failed"}
        ]}
        assert execution_pipeline._failure_signal(check) == 8

    def test_zero_when_no_pattern(self):
        check = {"runs": [{"output_tail": "all good"}]}
        assert execution_pipeline._failure_signal(check) == 0

    def test_empty_runs(self):
        assert execution_pipeline._failure_signal({}) == 0
        assert execution_pipeline._failure_signal({"runs": []}) == 0


@pytest.mark.unit
class TestNormalizeFailureId:
    """Tests for _normalize_failure_id — volatile token removal."""

    def test_removes_duration(self):
        result = execution_pipeline._normalize_failure_id("Build failed in 1.41s")
        assert "1.41s" not in result

    def test_removes_hex_addresses(self):
        result = execution_pipeline._normalize_failure_id("error at 0x7fff1234")
        assert "0x7fff1234" not in result

    def test_removes_ms_duration(self):
        result = execution_pipeline._normalize_failure_id("test (123 ms)")
        assert "123 ms" not in result


@pytest.mark.unit
class TestFailureIds:
    """Tests for _failure_ids — structured failure extraction."""

    def test_pytest_failure_id(self):
        check = {"runs": [{"output_tail": "FAILED tests/test_a.py::test_foo"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("test_a.py" in i or "test_foo" in i for i in ids)

    def test_strips_ansi_colors(self):
        check = {"runs": [{"output_tail": "FAILED\x1b[0m tests/test_b.py::test_bar"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("test_b.py" in i or "test_bar" in i for i in ids)

    def test_empty_for_no_failures(self):
        check = {"runs": [{"output_tail": "all passed"}]}
        assert execution_pipeline._failure_ids(check) == set()


@pytest.mark.unit
class TestDiffChecks:
    """Tests for _diff_checks — regression/fixed detection."""

    def test_pass_to_fail_is_regression(self):
        base = {"build": {"status": "pass"}}
        after = {"build": {"status": "fail"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == ["build"]
        assert fixed == []

    def test_fail_to_pass_is_fixed(self):
        base = {"test": {"status": "fail"}}
        after = {"test": {"status": "pass"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == []
        assert fixed == ["test"]

    def test_fail_to_fail_same_no_change(self):
        base = {"x": {"status": "fail"}}
        after = {"x": {"status": "fail"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == []
        assert fixed == []

    def test_fail_to_fail_worse_is_regression(self):
        base = {"test": {"status": "fail", "runs": [{"output_tail": "1 failed"}]}}
        after = {"test": {"status": "fail", "runs": [{"output_tail": "8 failed"}]}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == ["test"]

    def test_pass_to_warn_is_regression(self):
        base = {"test": {"status": "pass"}}
        after = {"test": {"status": "warn"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == ["test"]

    def test_warn_to_fail_is_regression(self):
        base = {"test": {"status": "warn"}}
        after = {"test": {"status": "fail"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == ["test"]

    def test_warn_to_warn_no_change(self):
        base = {"test": {"status": "warn"}}
        after = {"test": {"status": "warn"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == []
        assert fixed == []

    def test_warn_to_pass_is_improvement(self):
        base = {"test": {"status": "warn"}}
        after = {"test": {"status": "pass"}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == []
        assert fixed == []

    def test_none_to_fail_is_regression(self):
        regr, fixed = execution_pipeline._diff_checks({}, {"x": {"status": "fail"}})
        assert regr == ["x"]

    def test_empty_inputs(self):
        regr, fixed = execution_pipeline._diff_checks(None, None)
        assert regr == []
        assert fixed == []

    def test_new_failure_id_in_same_fail_is_regression(self):
        base = {"test": {"status": "fail",
                         "runs": [{"output_tail": "FAILED tests/a.py::test_old"}]}}
        after = {"test": {"status": "fail",
                          "runs": [{"output_tail": "FAILED tests/a.py::test_old\nFAILED tests/b.py::test_new"}]}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert "test" in regr

    def test_vite_time_normalization(self):
        vite_err = 'src/a.tsx (19:9): "X" is not exported'
        base = {"build": {"status": "fail", "runs": [{"output_tail": f"Build failed in 1.38s\n{vite_err}"}]}}
        after = {"build": {"status": "fail", "runs": [{"output_tail": f"Build failed in 1.41s\n{vite_err}"}]}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert regr == []  # same error, different time = NOT regression


@pytest.mark.unit
class TestTreeCleanHelpers:
    """Tests for _tree_clean, _tree_clean_after_checks, _untracked, _has_changes."""

    def test_tree_clean_on_clean_repo(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._tree_clean(child_root) is True

    def test_tree_clean_on_dirty_repo(self, child_root):
        _init_git(child_root)
        (child_root / "new_file.txt").write_text("dirty")
        assert execution_pipeline._tree_clean(child_root) is False

    def test_has_changes_false_on_clean(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._has_changes(child_root) is False

    def test_has_changes_true_on_dirty(self, child_root):
        _init_git(child_root)
        (child_root / "new.txt").write_text("change")
        assert execution_pipeline._has_changes(child_root) is True

    def test_untracked_empty_on_clean(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._untracked(child_root) == set()

    def test_untracked_finds_new_file(self, child_root):
        _init_git(child_root)
        (child_root / "untracked.txt").write_text("new")
        result = execution_pipeline._untracked(child_root)
        assert "untracked.txt" in result

    def test_tree_clean_after_checks_ignores_pycache(self, child_root):
        _init_git(child_root)
        (child_root / "__pycache__").mkdir()
        (child_root / "__pycache__" / "mod.cpython-39.pyc").write_text("x")
        assert execution_pipeline._tree_clean_after_checks(child_root) is True

    def test_tree_clean_after_checks_ignores_pytest_cache(self, child_root):
        _init_git(child_root)
        (child_root / ".pytest_cache").mkdir()
        (child_root / ".pytest_cache" / "v").write_text("x")
        assert execution_pipeline._tree_clean_after_checks(child_root) is True

    def test_tree_clean_after_checks_fails_on_real_untracked(self, child_root):
        _init_git(child_root)
        (child_root / "leftover.txt").write_text("real")
        assert execution_pipeline._tree_clean_after_checks(child_root) is False

    def test_tree_clean_after_checks_fails_on_tracked_modification(self, child_root):
        _init_git(child_root)
        (child_root / "dummy.txt").write_text("modified")
        assert execution_pipeline._tree_clean_after_checks(child_root) is False


@pytest.mark.unit
class TestCommittedChangedFiles:
    """Tests for _committed_changed_files."""

    def test_returns_changed_files(self, child_root):
        _init_git(child_root)
        (child_root / "added.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add"], cwd=child_root, capture_output=True)
        rc, sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._committed_changed_files(child_root, sha.strip())
        assert "added.py" in result

    def test_returns_empty_for_none(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._committed_changed_files(child_root, None)
        assert result == []

    def test_returns_empty_for_invalid_sha(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._committed_changed_files(child_root, "invalid-sha-xyz")
        assert result == []


@pytest.mark.unit
class TestCommitOnBranch:
    """Tests for _commit_on_branch."""

    def test_commit_creates_sha(self, child_root):
        _init_git(child_root)
        (child_root / "change.py").write_text("x = 1\n")
        sha = execution_pipeline._commit_on_branch(child_root, "test-branch", "test commit")
        assert sha is not None
        assert len(sha) == 40

    def test_commit_no_changes_returns_none(self, child_root):
        _init_git(child_root)
        sha = execution_pipeline._commit_on_branch(child_root, "test-branch", "empty commit")
        assert sha is None


@pytest.mark.unit
class TestToolCacheRegex:
    """Tests for _TOOL_CACHE_RE — tool cache pattern matching."""

    def test_matches_pycache(self):
        assert execution_pipeline._TOOL_CACHE_RE.search("__pycache__/mod.pyc")

    def test_matches_pytest_cache(self):
        assert execution_pipeline._TOOL_CACHE_RE.search(".pytest_cache/v")

    def test_matches_node_modules(self):
        assert execution_pipeline._TOOL_CACHE_RE.search("node_modules/pkg/index.js")

    def test_matches_pyc_files(self):
        assert execution_pipeline._TOOL_CACHE_RE.search("module.pyc")

    def test_does_not_match_regular_file(self):
        assert not execution_pipeline._TOOL_CACHE_RE.search("src/main.py")

    def test_matches_coverage(self):
        assert execution_pipeline._TOOL_CACHE_RE.search("coverage/lcov.info")

    def test_matches_build_dir(self):
        assert execution_pipeline._TOOL_CACHE_RE.search("dist/bundle.js")


@pytest.mark.unit
class TestEvidenceRefErrors:
    """Tests for _evidence_ref_errors — evidence reference validation."""

    def test_empty_evidence_list(self):
        errs = execution_pipeline._evidence_ref_errors("dom", [])
        assert len(errs) > 0

    def test_non_list_evidence(self):
        errs = execution_pipeline._evidence_ref_errors("dom", "not a list")
        assert len(errs) > 0

    def test_code_read_with_path(self):
        ev = [{"type": "code-read", "path": "src/main.py", "lines": "1-10"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_code_read_without_path(self):
        ev = [{"type": "code-read"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_code_read_fabricated_path(self):
        ev = [{"type": "code-read", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["other.py"])
        assert any("сфабрикован" in e for e in errs)

    def test_code_read_matching_path(self):
        ev = [{"type": "code-read", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["src/main.py"])
        assert errs == []

    def test_test_evidence_with_command(self):
        ev = [{"type": "test", "command": "pytest"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_test_evidence_without_command(self):
        ev = [{"type": "test"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_finding_evidence_with_id(self):
        ev = [{"type": "finding", "id": "SEC001"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_finding_evidence_without_id(self):
        ev = [{"type": "finding"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_file_type_treated_as_code_read(self):
        ev = [{"type": "file", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["src/main.py"])
        assert errs == []

    def test_unknown_type_without_path(self):
        ev = [{"type": "vibes"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_non_dict_evidence(self):
        errs = execution_pipeline._evidence_ref_errors("dom", ["just a string"])
        assert len(errs) > 0


@pytest.mark.unit
class TestSecurityVerdictErrors:
    """Tests for _security_verdict_errors — security reviewer verdict validation."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def test_non_dict_result(self):
        errs = execution_pipeline._security_verdict_errors(None, "rev", [], self._make_vrr())
        assert len(errs) > 0

    def test_bare_pass_is_invalid(self):
        errs = execution_pipeline._security_verdict_errors(
            {"status": "pass"}, "abc123", ["injection"], self._make_vrr())
        assert len(errs) > 0

    def test_valid_structured_pass(self):
        good = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "injection", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "no_inj", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py", "lines": "1-5"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(good, "abc123", ["injection"], self._make_vrr())
        assert errs == []

    def test_wrong_revision(self):
        good = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "OTHER",
            "checks": [{"id": "injection", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "no_inj", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py", "lines": "1-5"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(good, "abc123", ["injection"], self._make_vrr())
        assert any("revision" in e for e in errs)

    def test_missing_domain_results(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc123", ["injection"], self._make_vrr())
        assert any("domain_results" in e for e in errs)

    def test_domain_results_missing_domain(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc123", ["injection", "secrets"], self._make_vrr())
        assert any("не покрывает" in e for e in errs)

    def test_warn_domain_with_pass_overall(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "warn",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc123", ["injection"], self._make_vrr())
        assert any("несогласованно" in e for e in errs)


@pytest.mark.unit
class TestReviewableGates:
    """Tests for _reviewable_gates — which gates can be self-reviewed."""

    def test_security_excluded(self):
        result = execution_pipeline._reviewable_gates(["security", "ux_review"], {})
        assert "security" not in result

    def test_ai_red_team_excluded(self):
        result = execution_pipeline._reviewable_gates(["ai_red_team", "ux_review"], {})
        assert "ai_red_team" not in result

    def test_empty_gates(self):
        result = execution_pipeline._reviewable_gates([], {})
        assert result == []


@pytest.mark.unit
class TestOpenspecValidate:
    """Tests for _openspec_validate — openspec CLI integration."""

    def test_cli_not_found(self, child_root):
        _init_git(child_root)
        available, ok, output = execution_pipeline._openspec_validate(child_root, "test-change")
        # openspec CLI is likely not installed in test env
        if not available:
            assert "не найден" in output


@pytest.mark.unit
class TestAuthoredContext:
    """Tests for _authored_context — spec-first context for implementation."""

    def test_empty_authored_returns_empty(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._authored_context([], child_root, "wid")
        assert result == ""

    def test_none_authored_returns_empty(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._authored_context(None, child_root, "wid")
        assert result == ""


@pytest.mark.unit
class TestInstallDependencies:
    """Tests for _install_dependencies — stack dependency installation."""

    def test_install_with_valid_command(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [{"language": "python", "install_command": "true"}]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 1
        assert results[0]["ok"] is True

    def test_install_skips_none_command(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [{"language": "go", "install_command": None}]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 0

    def test_install_deduplicates_commands(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [
            {"language": "node", "install_command": "true"},
            {"language": "python", "install_command": "true"},
        ]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 1

    def test_install_empty_stacks(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": []}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert results == []


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineCommit:
    """Tests for run_pipeline with commit=True — SHA, tree cleanliness, evidence."""

    def test_commit_creates_sha_and_branch(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        ops = iter([{"op": "write", "path": "src/feat.py", "content": "x = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="add feature",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 10},
            feature="commit-test",
            commit=True,
        )
        assert report["commit"]["sha"] is not None
        assert len(report["commit"]["sha"]) == 40
        assert report["commit"]["branch"] == "ai-ops/commit-test"
        assert report["commit"]["evidence_on_exact_sha"] is True
        assert report["commit"]["tree_clean_before_checks"] is True

    def test_commit_false_never_ready(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/x.py", "content": "x = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 5},
            commit=False,
        )
        assert report["ready_for_pr"] is False

    def test_pipeline_report_contains_all_sections(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/y.py", "content": "y = 2\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="full report test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="full-report",
            commit=True,
        )
        # Verify all major report sections exist
        assert "loop" in report
        assert "checks" in report
        assert "gates" in report
        assert "commit" in report
        assert "containment" in report
        assert "base_binding" in report
        assert "delivery" in report
        assert "overall_status" in report
        assert "not_yet" in report
        assert "exemptions" in report
        assert "spec_depth" in report
        assert "spec_first" in report
        assert "approval_recheck" in report
        assert isinstance(report["loop"]["transcript"], list)
        assert isinstance(report["loop"]["denied_reasons"], list)


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineIsolate:
    """Tests for run_pipeline with isolate=True — worktree isolation."""

    def test_isolate_creates_worktree(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/iso.py", "content": "z = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="isolated work",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="iso-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report["isolation"]["worktree"] == ".ai/worktrees/iso-test"
        assert (child_root / ".ai" / "worktrees" / "iso-test" / "src" / "iso.py").exists()
        # main tree NOT touched
        assert not (child_root / "src" / "iso.py").exists()

    def test_isolate_discard_previous(self, child_root):
        _init_git(child_root)
        # First run
        ops1 = iter([{"op": "write", "path": "src/first.py", "content": "a = 1\n"}, {"done": True}])
        execution_pipeline.run_pipeline(
            task="first", signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root, proposer=lambda ctx: next(ops1),
            budget={"max_model_calls": 10}, feature="discard-test",
            commit=True, isolate=True, install_deps=False,
        )
        # Second run with discard
        ops2 = iter([{"op": "write", "path": "src/second.py", "content": "b = 2\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="second", signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root, proposer=lambda ctx: next(ops2),
            budget={"max_model_calls": 10}, feature="discard-test",
            commit=True, isolate=True, install_deps=False, discard_previous=True,
        )
        assert report.get("status") != "error"


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineBaselineDiff:
    """Tests for run_pipeline with baseline_diff=True."""

    def test_baseline_diff_report_structure(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/bd.py", "content": "bd = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="baseline test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="bd-test",
            commit=True,
            baseline_diff=True,
        )
        assert report["baseline"] is not None
        assert "checks" in report["baseline"]
        assert "regressions" in report["baseline"]
        assert "fixed" in report["baseline"]
        assert "no_regressions" in report["baseline"]
        assert report["ready_criterion"] == "no-regressions"

    def test_baseline_diff_no_regressions_ready(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/bd2.py", "content": "bd2 = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="baseline no regression",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="bd2-test",
            commit=True,
            baseline_diff=True,
        )
        assert report["baseline"]["no_regressions"] is True
        assert report["ready_for_pr"] is True

    def test_require_fix_without_fixed_not_ready(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/rf.py", "content": "rf = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="require fix",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="rf-test",
            commit=True,
            baseline_diff=True,
            require_fix=True,
        )
        assert report["ready_criterion"] == "no-regressions+require-fix"
        assert report["ready_for_pr"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSandbox:
    """Tests for run_pipeline with sandbox=True."""

    def test_sandbox_containment_report(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/sb.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="sandbox test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="sb-test",
            commit=True,
            sandbox=True,
            install_deps=False,
        )
        assert report["containment"]["sandbox"] is True
        assert report["containment"]["shell_mode"] == "allowlist"
        assert report["containment"]["block_push"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineAllowMissingTests:
    """Tests for allow_missing_tests flag."""

    def test_allow_missing_tests_exempts(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/nt.py", "content": "n = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="no tests",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="nt-test",
            commit=True,
            allow_missing_tests=True,
        )
        assert "tests_passed" in report["exemptions"]
        assert report["tests_warn"] is not None

    def test_require_tests_blocks(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/rt.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="require tests",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="rt-test",
            commit=True,
            allow_missing_tests=False,
        )
        assert "implementation_verification" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineDelivery:
    """Tests for delivery plan generation."""

    def test_open_pr_creates_delivery_plan(self, child_root):
        _init_git(child_root)
        import os
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            ops = iter([{"op": "write", "path": "src/pr.py", "content": "p = 1\n"}, {"done": True}])
            report = execution_pipeline.run_pipeline(
                task="pr test",
                signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
                child_root=child_root,
                proposer=lambda ctx: next(ops),
                budget={"max_model_calls": 10},
                feature="pr-test",
                commit=True,
                isolate=True,
                open_pr=True,
                install_deps=False,
            )
            assert report["delivery"]["requested"] is True
            assert report["delivery"]["status"] == "planned"
            assert report.get("delivery_plan") is not None
            assert report["delivery_plan"]["ready_for_delivery"] is True
            assert report["overall_status"] == "ready-undelivered"
            assert report.get("draft_pr") is None
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_no_open_pr_delivery_not_requested(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/npr.py", "content": "n = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="no pr",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="npr-test",
            commit=True,
            open_pr=False,
        )
        assert report["delivery"]["requested"] is False


@pytest.mark.unit
class TestResolveBaseAdditional:
    """Additional tests for _resolve_base edge cases."""

    def test_not_git_repo(self, tmp_path):
        result = execution_pipeline._resolve_base(tmp_path, None)
        assert result["resolved"] is False
        assert result["mode"] == "auto"

    def test_explicit_local_branch_has_sha(self, child_root):
        _init_git(child_root)
        rc, branch, _ = execution_pipeline._git(child_root, "rev-parse", "--abbrev-ref", "HEAD")
        result = execution_pipeline._resolve_base(child_root, branch.strip())
        assert result["resolved"] is True
        assert result["source"] == "explicit-local"
        assert result.get("base_sha")

    def test_auto_mode_source(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._resolve_base(child_root, None)
        assert result["resolved"] is True
        assert result["mode"] == "auto"
        assert result.get("base_sha")


@pytest.mark.unit
class TestProfileSummaryAdditional:
    """Additional tests for _profile_summary."""

    def test_multiple_stacks(self):
        profile = {"stacks": [
            {"language": "Python", "commands": {"test": "pytest"}},
            {"language": "JavaScript", "commands": {"test": "jest"}},
        ]}
        result = execution_pipeline._profile_summary(profile)
        assert "Python" in result
        assert "JavaScript" in result

    def test_no_commands(self):
        profile = {"stacks": [{"language": "Rust"}]}
        result = execution_pipeline._profile_summary(profile)
        assert "Rust" in result
        assert "нет" in result

    def test_none_stacks(self):
        profile = {}
        result = execution_pipeline._profile_summary(profile)
        assert "не определён" in result

    def test_commands_dedup(self):
        # _profile_summary deduplicates by command KEY (first wins), not by value
        profile = {"stacks": [
            {"language": "Python", "commands": {"test": "pytest"}},
            {"language": "Go", "commands": {"build": "go build"}},
        ]}
        result = execution_pipeline._profile_summary(profile)
        assert "pytest" in result
        assert "go build" in result


# ============================================================================
# ADDITIONAL TESTS — targeting remaining uncovered blocks (50%+ goal)
# ============================================================================

@pytest.mark.unit
class TestAuthorWithRetry:
    """Tests for _author_with_retry — retry logic for flaky author output."""

    def test_first_attempt_valid(self):
        import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        author = lambda prompt: "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud)
        assert errs == []
        assert data is not None
        assert data["kind"] == "requirements-artifact"

    def test_flaky_first_then_valid(self):
        import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        calls = {"n": 0}
        def flaky_author(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return "garbage not yaml"
            return "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(flaky_author, "prompt", check, bud)
        assert errs == []
        assert calls["n"] == 2

    def test_always_invalid(self):
        import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        author = lambda prompt: "always garbage"
        check = lambda data: ["invalid"] if not isinstance(data, dict) else ["still invalid"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud, attempts=2)
        assert len(errs) > 0

    def test_budget_exceeded(self):
        import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 0})
        author = lambda prompt: "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud)
        assert any("budget" in str(e) for e in errs)


@pytest.mark.unit
class TestRunAuthoring:
    """Tests for _run_authoring — artifact production pipeline."""

    def test_authoring_closes_requirements(self, child_root):
        _init_git(child_root)
        def author(prompt):
            if "requirements-artifact" in prompt:
                return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                        "  - id: R1\n    statement: test requirement\n"
                        "    acceptance:\n      - when x then y\n")
            return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                    "  - id: WP1\n    summary: test\n    depends_on: []\n"
                    "write_scope:\n  - src/\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements", "plan_readiness"], {}, "test-wid",
            "test task", {"max_model_calls": 10})
        assert "requirements" in gate_ev
        assert gate_ev["requirements"]["status"] == "pass"
        assert "plan_readiness" in gate_ev
        assert gate_ev["plan_readiness"]["status"] == "pass"
        assert wrote is True
        # artifact on disk
        assert (child_root / ".ai" / "runplan" / "test-wid" / "requirements.yaml").is_file()

    def test_authoring_invalid_artifact(self, child_root):
        _init_git(child_root)
        author = lambda prompt: "not valid yaml artifact"
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements"], {}, "bad-wid",
            "test task", {"max_model_calls": 5})
        assert "requirements" not in gate_ev
        assert any(not a["valid"] for a in authored)

    def test_authoring_skips_existing_evidence(self, child_root):
        _init_git(child_root)
        author = lambda prompt: "should not be called"
        existing_ev = {"requirements": {"status": "pass", "provided": ["existing"]}}
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements"], existing_ev, "skip-wid",
            "test task", {"max_model_calls": 5})
        assert gate_ev["requirements"]["status"] == "pass"
        assert gate_ev["requirements"]["provided"] == ["existing"]

    def test_authoring_spec_with_valid_openspec(self, child_root):
        _init_git(child_root)
        def spec_author(prompt):
            return ("schema_version: 1\nkind: spec-change\ncapability: test\nwhy: testing\n"
                    "what_changes:\n  - add feature\ntasks:\n  - implement\n"
                    "requirements:\n  - name: Fmt\n    text: The system SHALL format.\n"
                    "    scenarios:\n      - {name: T, when: x, then: y}\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            spec_author, child_root, ["specification"], {}, "spec-wid",
            "spec task", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" in gate_ev
        assert gate_ev["specification"]["status"] == "pass"

    def test_authoring_spec_cli_absent(self, child_root):
        _init_git(child_root)
        def spec_author(prompt):
            return ("schema_version: 1\nkind: spec-change\ncapability: test\nwhy: testing\n"
                    "what_changes:\n  - add feature\ntasks:\n  - implement\n"
                    "requirements:\n  - name: Fmt\n    text: The system SHALL format.\n"
                    "    scenarios:\n      - {name: T, when: x, then: y}\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            spec_author, child_root, ["specification"], {}, "spec-absent",
            "spec task", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (False, False, "no CLI"))
        assert "specification" not in gate_ev
        assert any(a["gate"] == "specification" and a.get("closed") is False for a in authored)


@pytest.mark.unit
class TestAuthoredContextWithArtifacts:
    """Tests for _authored_context with actual artifacts on disk."""

    def test_context_from_valid_artifacts(self, child_root):
        _init_git(child_root)
        # Create artifact files
        out_dir = child_root / ".ai" / "runplan" / "ctx-wid"
        out_dir.mkdir(parents=True)
        (out_dir / "requirements.yaml").write_text("requirements:\n  - id: R1\n", encoding="utf-8")
        authored = [{"gate": "requirements", "artifact": "requirements.yaml", "valid": True}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert "SPECIFICATION" in result or "requirements" in result
        assert "R1" in result

    def test_context_skips_invalid_artifacts(self, child_root):
        _init_git(child_root)
        authored = [{"gate": "requirements", "artifact": "requirements.yaml", "valid": False}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert result == ""

    def test_context_skips_openspec(self, child_root):
        _init_git(child_root)
        authored = [{"gate": "specification", "artifact": "openspec/changes/wid", "valid": True}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert result == ""


@pytest.mark.unit
class TestReevaluateArtifactEvidence:
    """Tests for _reevaluate_artifact_evidence — re-derive evidence from disk."""

    def test_reevaluate_with_existing_artifacts(self, child_root):
        _init_git(child_root)
        out_dir = child_root / ".ai" / "runplan" / "reeval-wid"
        out_dir.mkdir(parents=True)
        (out_dir / "requirements.yaml").write_text(
            "schema_version: 1\nkind: requirements-artifact\n"
            "requirements:\n  - id: R1\n    statement: test requirement\n"
            "    acceptance:\n      - when x then y\n",
            encoding="utf-8")
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "reeval-wid",
                                                              ["requirements"])
        assert "requirements" in ev
        assert ev["requirements"]["status"] == "pass"

    def test_reevaluate_missing_artifacts(self, child_root):
        _init_git(child_root)
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "no-wid",
                                                              ["requirements"])
        assert "requirements" not in ev

    def test_reevaluate_skips_nonexistent_gate(self, child_root):
        _init_git(child_root)
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "no-wid",
                                                              ["nonexistent_gate"])
        assert ev == {}


@pytest.mark.unit
class TestFailureIdsAdditionalPatterns:
    """Tests for _failure_ids — additional language patterns."""

    def test_go_test_failure(self):
        check = {"runs": [{"output_tail": "--- FAIL: TestSub (0.00s)"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("TestSub" in i for i in ids)

    def test_tsc_error(self):
        check = {"runs": [{"output_tail": "src/a.ts(3,5): error TS2322: Type error"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("TS2322" in i or "a.ts" in i for i in ids)

    def test_rust_error(self):
        check = {"runs": [{"output_tail": "error[E0308]: mismatched types"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("E0308" in i for i in ids)

    def test_jest_file_failure(self):
        check = {"runs": [{"output_tail": "FAIL src/app.test.ts"}]}
        ids = execution_pipeline._failure_ids(check)
        assert any("app.test.ts" in i for i in ids)

    def test_generic_assertion_error(self):
        check = {"runs": [{"output_tail": "AssertionError: expected 1 got 2"}]}
        ids = execution_pipeline._failure_ids(check)
        assert len(ids) > 0


@pytest.mark.unit
class TestDiffChecksStructuredIds:
    """Tests for _diff_checks with structured failure IDs."""

    def test_fail_to_fail_new_id_is_regression(self):
        base = {"test": {"status": "fail",
                         "runs": [{"output_tail": "FAILED tests/a.py::test_old"}]}}
        after = {"test": {"status": "fail",
                          "runs": [{"output_tail": "FAILED tests/a.py::test_old\nFAILED tests/b.py::test_new"}]}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert "test" in regr

    def test_fail_to_fail_removed_id_is_fixed(self):
        base = {"test": {"status": "fail",
                         "runs": [{"output_tail": "FAILED tests/a.py::test_old\nFAILED tests/b.py::test_removed"}]}}
        after = {"test": {"status": "fail",
                          "runs": [{"output_tail": "FAILED tests/a.py::test_old"}]}}
        regr, fixed = execution_pipeline._diff_checks(base, after)
        assert "test" in fixed

    def test_vite_same_error_different_time_not_regression(self):
        vite_err = 'src/a.tsx (19:9): "X" is not exported'
        base = {"build": {"status": "fail",
                          "runs": [{"output_tail": f"Build failed in 1.38s\n{vite_err}"}]}}
        after = {"build": {"status": "fail",
                           "runs": [{"output_tail": f"Build failed in 1.41s\n{vite_err}"}]}}
        regr, _ = execution_pipeline._diff_checks(base, after)
        assert regr == []

    def test_vite_new_error_is_regression(self):
        base_err = 'src/a.tsx (19:9): "X" is not exported'
        new_err = 'src/b.tsx (5:3): "Y" is not defined'
        base = {"build": {"status": "fail",
                          "runs": [{"output_tail": f"Build failed in 1.38s\n{base_err}"}]}}
        after = {"build": {"status": "fail",
                           "runs": [{"output_tail": f"Build failed in 1.55s\n{new_err}"}]}}
        regr, _ = execution_pipeline._diff_checks(base, after)
        assert "build" in regr

    def test_java_surefire_swap(self):
        base = {"test": {"status": "fail", "runs": [{"output_tail":
                  "[ERROR] CalcTest.testSub -- Time elapsed: 0.01 s <<< FAILURE!"}]}}
        after = {"test": {"status": "fail", "runs": [{"output_tail":
                   "[ERROR] CalcTest.testAdd -- Time elapsed: 0.008 s <<< FAILURE!"}]}}
        regr, _ = execution_pipeline._diff_checks(base, after)
        assert "test" in regr


@pytest.mark.unit
class TestChangeContextTruncation:
    """Tests for _change_context and _change_context_range with large diffs."""

    def test_change_context_truncates_large_diff(self, child_root):
        _init_git(child_root)
        # Create a large file
        large_content = "x\n" * 5000
        (child_root / "large.py").write_text(large_content)
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "large"], cwd=child_root, capture_output=True)
        rc, sha, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._change_context(child_root, sha.strip(), max_chars=500)
        assert "large.py" in result
        # Should contain truncation marker if diff is large
        assert len(result) < 5000

    def test_change_context_range_degrades_without_base(self, child_root):
        _init_git(child_root)
        (child_root / "only.py").write_text("only = 1\n")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "only"], cwd=child_root, capture_output=True)
        rc, head, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        result = execution_pipeline._change_context_range(child_root, "", head.strip())
        assert "only.py" in result


@pytest.mark.unit
class TestSecurityVerdictErrorsAdditional:
    """Additional tests for _security_verdict_errors — deeper branches."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def test_duplicate_domains(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "a.py"}]},
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok2", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "b.py"}]},
            ]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("дубли" in e for e in errs)

    def test_extra_domain(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "a.py"}]},
                {"domain": "unknown_domain", "status": "pass",
                 "checks": [{"id": "ok2", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "b.py"}]},
            ]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("лишние" in e or "неизвестные" in e for e in errs)

    def test_pass_domain_without_evidence(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("evidence" in e for e in errs)

    def test_domain_without_checks(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("checks" in e for e in errs)

    def test_nested_check_without_id(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("nested-check" in e for e in errs)

    def test_warn_domain_without_blockers(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "warn",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("blockers" in e for e in errs)

    def test_file_type_evidence_with_reads_match(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "input_validation", "status": "pass",
                                "checks": [{"id": "iv", "status": "pass"}],
                                "evidence": [{"type": "file", "path": "pricing.py", "lines": "10-11"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc", ["input_validation"], self._make_vrr(), reviewer_reads=["pricing.py"])
        assert errs == []

    def test_file_type_evidence_fabricated(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "input_validation", "status": "pass",
                                "checks": [{"id": "iv", "status": "pass"}],
                                "evidence": [{"type": "file", "path": "pricing.py", "lines": "10-11"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc", ["input_validation"], self._make_vrr(), reviewer_reads=["other.py"])
        assert any("сфабрикован" in e for e in errs)

    def test_pass_domain_check_without_pass_check(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "warn"}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("ни один" in e for e in errs)


@pytest.mark.unit
class TestRunPipelineContextPrelude:
    """Tests for run_pipeline with context_prelude and resume_context."""

    def test_context_prelude_in_prompt(self, child_root):
        _init_git(child_root)
        seen = {}
        def capturing_proposer(ctx):
            seen["ctx"] = ctx
            return {"done": True}
        execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=capturing_proposer,
            budget={"max_model_calls": 5},
            context_prelude="PRELUDE_MARKER_XYZ",
        )
        assert "PRELUDE_MARKER_XYZ" in seen.get("ctx", "")

    def test_resume_context_in_prompt(self, child_root):
        _init_git(child_root)
        seen = {}
        def capturing_proposer(ctx):
            seen["ctx"] = ctx
            return {"done": True}
        execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=capturing_proposer,
            budget={"max_model_calls": 5},
            resume_context="RESUME_STATE_ABC",
        )
        assert "RESUME_STATE_ABC" in seen.get("ctx", "")


@pytest.mark.unit
class TestRunPipelinePlan:
    """Tests for run_pipeline with pre-built plan."""

    def test_external_plan_used(self, child_root):
        _init_git(child_root)
        import run_plan
        plan = run_plan.build_plan({"task_type": "QUICK"}, workitem_id="ext-plan")
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
            plan=plan,
        )
        assert report["workitem_id"] == "ext-plan"


@pytest.mark.unit
class TestRunPipelineWriteScope:
    """Tests for run_pipeline with write_scope restriction."""

    def test_write_out_of_scope_denied(self, child_root):
        _init_git(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        ops = iter([{"op": "write", "path": "config/x", "content": "y"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="out of scope",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 5},
        )
        assert report["loop"]["denied"] >= 1


@pytest.mark.unit
class TestGitHelper:
    """Tests for _git wrapper."""

    def test_git_success(self, child_root):
        _init_git(child_root)
        rc, out, err = execution_pipeline._git(child_root, "status")
        assert rc == 0

    def test_git_failure(self, child_root):
        _init_git(child_root)
        rc, out, err = execution_pipeline._git(child_root, "log", "--oneline", "nonexistent-branch")
        assert rc != 0


@pytest.mark.unit
class TestHasChanges:
    """Tests for _has_changes."""

    def test_no_changes_after_commit(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._has_changes(child_root) is False

    def test_changes_with_new_file(self, child_root):
        _init_git(child_root)
        (child_root / "new.txt").write_text("new")
        assert execution_pipeline._has_changes(child_root) is True

    def test_changes_with_modified_file(self, child_root):
        _init_git(child_root)
        (child_root / "dummy.txt").write_text("modified content")
        assert execution_pipeline._has_changes(child_root) is True


@pytest.mark.unit
class TestRunPipelineOverallStatus:
    """Tests for overall_status computation."""

    def test_error_status_on_preflight_fail(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
            base="nonexistent-branch-xyz",
            isolate=True,
        )
        assert report["overall_status"] == "error"

    def test_ready_undelivered_with_open_pr(self, child_root):
        _init_git(child_root)
        import os
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            ops = iter([{"op": "write", "path": "src/st.py", "content": "s = 1\n"}, {"done": True}])
            report = execution_pipeline.run_pipeline(
                task="status test",
                signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
                child_root=child_root,
                proposer=lambda ctx: next(ops),
                budget={"max_model_calls": 10},
                feature="status-test",
                commit=True,
                isolate=True,
                open_pr=True,
                install_deps=False,
            )
            if report["ready_for_pr"]:
                assert report["overall_status"] == "ready-undelivered"
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


@pytest.mark.unit
class TestReviewableGatesAdditional:
    """Additional tests for _reviewable_gates with real gate loading."""

    def test_ux_review_is_reviewable(self):
        # ux_review should be ai-review type and thus reviewable
        result = execution_pipeline._reviewable_gates(["ux_review"], {"ui_changed": True})
        assert "ux_review" in result

    def test_code_review_is_reviewable(self):
        result = execution_pipeline._reviewable_gates(["code_review"], {})
        assert "code_review" in result

    def test_deterministic_gates_not_reviewable(self):
        # requirements/specification are deterministic, not ai-review
        result = execution_pipeline._reviewable_gates(["requirements", "specification"], {})
        assert "requirements" not in result
        assert "specification" not in result


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineReview:
    """Tests for run_pipeline with review=True — independent reviewer integration."""

    def test_review_without_review_proposer(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        ops = iter([{"op": "write", "path": "src/rv.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="rv-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        # review not requested -> reviews is None
        assert report["reviews"] is None

    def test_review_with_fail_reviewer(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        fail_reviewer = lambda prompt: (
            '{"kind":"reviewer-result","status":"fail",'
            '"checks":[{"id":"ux","status":"fail"}],'
            '"blockers":["no states"]}')
        ops = iter([{"op": "write", "path": "src/rvf.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review fail test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rvf-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=fail_reviewer,
        )
        # review ran -> reviews is not None
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "fail" for r in report["reviews"])
        # ux_review should be in unmet (reviewer said fail)
        assert "ux_review" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSecurityPack:
    """Tests for security pack integration in run_pipeline."""

    def test_security_scan_present_with_commit(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/sec.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="security test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="sec-pack-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        # security_scan should be present (may be None if no committed_sha path, but with commit it runs)
        # The key is that security gate evaluation happened
        assert "security_scan" in report
        assert "gates" in report

    def test_security_secret_blocks(self, child_root):
        _init_git(child_root)
        # Не канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — публичный образец, и
        # детектор с 19.08.2026 его не считает утечкой. Позитивной фикстуре нужен ключ,
        # похожий на настоящий.
        _aws = "AKIA" + "QRSTUVWX9012YZAB"
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "medium", "affected_areas": ["core"]}
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        ops = iter([{"op": "write", "path": "src/leak.py",
                     "content": f'KEY = "{_aws}"\n'}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="secret test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 10},
            feature="sec-secret",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report.get("security_scan") is not None
        assert "secrets" in report["security_scan"]["blocking"]
        assert "security" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSpecDepth:
    """Tests for spec-depth and spec-first integration."""

    def test_spec_depth_in_report(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/sd.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="spec depth",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="sd-test",
            commit=True,
        )
        assert "spec_depth" in report
        assert "spec_first" in report
        assert isinstance(report["spec_depth"]["missing"], list)
        assert isinstance(report["spec_first"]["incomplete_sections"], list)

    def test_spec_first_prestage_without_author(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="no author",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
        )
        assert report["spec_first"]["prestage"]["ran"] is False
        assert report["spec_first"]["prestage"]["implementation_skipped"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineContextOverflow:
    """Tests for context budget overflow detection."""

    def test_context_overflow_blocks_ready(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/ov.py", "content": "o = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="overflow test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low",
                     "affected_areas": ["core"], "context_budget": 1},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="ov-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report["context_overflow"] is True
        assert report["ready_for_pr"] is False
        assert any("декомпоз" in n for n in report["not_yet"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSeamScan:
    """Tests for seam-scan advisory integration."""

    def test_seam_scan_in_report(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/ss.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="seam scan test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="ss-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert "seam_scan" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineAuthoring:
    """Tests for run_pipeline with author=True — product authoring integration."""

    def test_authoring_without_author_proposer(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="no author",
            signals={"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
            feature="na-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report["authored"] is None

    def test_authoring_with_valid_author(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}
        def author(prompt):
            if "requirements-artifact" in prompt:
                return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                        "  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n")
            return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                    "  - id: WP1\n    summary: test\n    depends_on: []\nwrite_scope:\n  - src/\n")
        ops = iter([{"op": "write", "path": "src/au.py", "content": "a = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="authoring test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="auth-test",
            commit=True,
            isolate=True,
            install_deps=False,
            author=True,
            author_proposer=author,
        )
        assert report["authored"] is not None
        assert all(a["valid"] for a in report["authored"] if a.get("gate") in ("requirements", "plan_readiness"))
        assert "requirements" not in report["gates"]["unmet"]
        assert "plan_readiness" not in report["gates"]["unmet"]

    def test_authoring_with_invalid_author(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}
        bad_author = lambda prompt: "not valid yaml"
        ops = iter([{"op": "write", "path": "src/bad.py", "content": "b = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="bad author",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="bad-auth",
            commit=True,
            isolate=True,
            install_deps=False,
            author=True,
            author_proposer=bad_author,
        )
        # Invalid spec -> implementation skipped (spec-prestage-failed)
        assert report["loop"]["stopped"] == "spec-prestage-failed"
        assert report["spec_first"]["prestage"]["implementation_skipped"] is True
        assert report["ready_for_pr"] is False


@pytest.mark.unit
class TestRunPipelineApprovalRecheck:
    """Tests for approval_recheck in report."""

    def test_approval_recheck_present(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/ar.py", "content": "a = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="approval test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="ar-test",
            commit=True,
        )
        assert "approval_recheck" in report
        assert isinstance(report["approval_recheck"], dict)
        assert "ok" in report["approval_recheck"]


@pytest.mark.unit
class TestRunPipelineProfile:
    """Tests for profile detection in report."""

    def test_profile_in_report(self, child_root):
        _init_git(child_root)
        # Create a Python project marker
        (child_root / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "pyproject"], cwd=child_root, capture_output=True)
        ops = iter([{"op": "write", "path": "src/pf.py", "content": "p = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="profile test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="pf-test",
            commit=True,
        )
        assert "profile" in report
        assert isinstance(report["profile"]["stacks"], list)


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineReviewPass:
    """Tests for run_pipeline review with pass reviewer — exercises _run_reviews."""

    def test_review_pass_closes_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # Reviewer reads the file first, then passes
        def pass_reviewer(prompt):
            if "--- src/rp2.py ---" in prompt:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            if "src/rp2.py" in prompt:
                return '{"op":"read","path":"src/rp2.py"}'
            return '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["no context"]}'
        ops = iter([{"op": "write", "path": "src/rp2.py", "content": "p = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review pass",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rp2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=pass_reviewer,
        )
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "pass" for r in report["reviews"])
        assert "ux_review" not in report["gates"]["unmet"]

    def test_review_warn_blocks_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        warn_reviewer = lambda prompt: (
            '{"kind":"reviewer-result","status":"warn",'
            '"checks":[{"id":"x","status":"warn"}],'
            '"blockers":["state not covered"]}')
        ops = iter([{"op": "write", "path": "src/rw2.py", "content": "w = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review warn",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rw2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=warn_reviewer,
        )
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "warn" for r in report["reviews"])
        assert "ux_review" in report["gates"]["unmet"]

    def test_review_rubber_stamp_blocked(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # Rubber-stamp: pass without reading anything
        rubber = lambda prompt: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        ops = iter([{"op": "write", "path": "src/rs2.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="rubber stamp",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rs2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=rubber,
        )
        # 0 reads on blocking gate -> blocked as rubber-stamp
        assert any(r["gate"] == "ux_review" and r.get("closed_as") == "blocked"
                    for r in (report["reviews"] or []))
        assert "ux_review" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSecurityReviewer:
    """Tests for security reviewer integration in run_pipeline."""

    def test_security_reviewer_pass_closes_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "medium", "affected_areas": ["core"]}
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        # Clean code + reviewer pass
        sec_reviewer = lambda c: '{"kind":"reviewer-result","status":"pass","summary":"clean"}'
        ops = iter([{"op": "write", "path": "src/clean.py", "content": "def f():\n    return 1\n"},
                     {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="security reviewer pass",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 15},
            feature="sec-rev-pass",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=sec_reviewer,
        )
        # Security reviewer was invoked (reviews ran)
        assert report["reviews"] is not None


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineNewDependency:
    """Tests for new dependency detection in security pack."""

    def test_new_dependency_triggers_security(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        import tool_broker
        pol = tool_broker.Policy(level="execution", block_push=True)
        ops = iter([{"op": "write", "path": "requirements.txt", "content": "flask\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="add dependency",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 10},
            feature="dep-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report.get("security_scan") is not None
        assert "dependencies" in (report["security_scan"].get("needs_review") or [])
        assert "security" in report["gates"]["unmet"]
        assert report["ready_for_pr"] is False


# ============================================================================
# MIGRATED FROM MONOLITH — test_execution_pipeline_selftest (weed round)
# Каждое поведение перенесено с НАСТОЯЩЕЙ проверкой значения (не только наличия
# ключа/верхнего status). Точные вызовы/фикстуры/фейковые proposer'ы — из монолита.
# ============================================================================


def _init_python_repo(child_root):
    """Git-репо с python-профилем БЕЗ тулчейна (нет ruff/mypy/pytest, нет tests/).

    Все проверки -> not_applicable детерминированно, независимо от среды теста.
    Повторяет фикстуру монолита (test_execution_pipeline_selftest, строки 51-62).
    """
    subprocess.run(["git", "init", "-q"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=child_root, capture_output=True)
    (child_root / "src").mkdir(exist_ok=True)
    (child_root / "pyproject.toml").write_text(
        "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\n", encoding="utf-8")
    (child_root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=child_root, capture_output=True)


def _head_branch(child_root):
    """Имя текущей ветки — default-ветка после git init варьируется (master/main)."""
    return execution_pipeline._git(child_root, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()


_QUICK_SIG = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}


@pytest.mark.unit
class TestPipelineLoopReport:
    """Петля/отчёт run_pipeline: точные значения полей (dry QUICK, python-профиль)."""

    def _run_dry(self, child_root):
        import tool_broker
        script = [
            {"op": "write", "path": "src/add.py", "content": "def add(a,b): return a+b\n"},
            {"op": "read", "path": "src/add.py"},
            {"done": True, "summary": "добавил add"},
        ]
        it = iter(script)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        return execution_pipeline.run_pipeline(
            "добавить функцию add", _QUICK_SIG, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 10}, feature="add-fn")

    def test_loop_stopped_done(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert rep["loop"]["stopped"] == "done"

    def test_applied_writes_one_and_file_exists(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert rep["loop"]["applied_writes"] == 1
        assert (child_root / "src" / "add.py").exists()

    def test_profile_detected_python(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert "python" in rep["profile"]["stacks"]

    def test_checks_nonempty_dict(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert isinstance(rep["checks"], dict) and rep["checks"]

    def test_gates_have_blocked_verdict_and_evaluated_list(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert "blocked" in rep["gates"]
        assert isinstance(rep["gates"]["evaluated"], list)

    def test_intake_completeness_closed_from_signals(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert "intake_completeness" not in rep["gates"]["unmet"]

    def test_workitem_bound_to_named_feature(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        assert rep["workitem_id"] == "add-fn"

    def test_dry_quick_not_yet_len_three(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        # dry-run (commit=False) — честный not_yet: commit/PR/живой
        assert len(rep["not_yet"]) == 3

    def test_dry_quick_never_ready_for_pr(self, child_root):
        _init_python_repo(child_root)
        rep = self._run_dry(child_root)
        # P0.5: commit=False НИКОГДА не ready_for_pr — нет ревизии для draft PR
        assert rep["ready_for_pr"] is False

    def test_out_of_scope_write_file_not_created(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it2 = iter([{"op": "write", "path": "config/x", "content": "y"}, {"done": True}])
        rep2 = execution_pipeline.run_pipeline(
            "вне scope", _QUICK_SIG, child_root, lambda c: next(it2),
            policy=pol, budget={"max_model_calls": 5})
        assert rep2["loop"]["denied"] >= 1
        assert not (child_root / "config" / "x").exists()


@pytest.mark.unit
class TestCommitNonIsolate:
    """commit=True без isolate: ветка ai-ops/*, evidence на точном SHA, ready True."""

    def _run_commit(self, child_root, feature="mul-fn"):
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it_c = iter([
            {"op": "write", "path": "src/mul.py", "content": "def mul(a,b): return a*b\n"},
            {"done": True, "summary": "mul"},
        ])
        return execution_pipeline.run_pipeline(
            "добавить mul", _QUICK_SIG, child_root, lambda c: next(it_c),
            policy=pol, budget={"max_model_calls": 10}, feature=feature, commit=True)

    def test_commit_on_working_branch_not_main(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        assert rep_c["commit"]["sha"]
        assert rep_c["commit"]["branch"] == "ai-ops/mul-fn"

    def test_evidence_on_exact_committed_sha(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        assert rep_c["commit"]["evidence_on_exact_sha"] is True
        assert rep_c["commit"]["evidence_revision"] == rep_c["commit"]["sha"]

    def test_main_not_touched_head_on_ai_ops_branch(self, child_root):
        _init_python_repo(child_root)
        self._run_commit(child_root)
        # работа на ветке ai-ops/*, HEAD переключён туда (main не тронут)
        assert _head_branch(child_root) == "ai-ops/mul-fn"

    def test_commit_clean_matched_sha_ready_true(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        assert rep_c["commit"]["tree_clean_before_checks"] is True
        assert rep_c["ready_for_pr"] is True

    def test_approval_recheck_ok_true_for_quick(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        # для QUICK одобрений нет -> recheck ok
        assert isinstance(rep_c.get("approval_recheck"), dict)
        assert rep_c["approval_recheck"]["ok"] is True

    def test_committed_changed_files_lists_diff(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        chg = execution_pipeline._committed_changed_files(child_root, rep_c["commit"]["sha"])
        assert "src/mul.py" in chg

    def test_smart_relaxation_tests_exempted_and_warn(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        # нет тестов -> освобождено + громкий tests_warn (allow_missing_tests по умолчанию)
        assert "tests_passed" in rep_c["exemptions"]
        assert rep_c["tests_warn"]

    def test_smart_relaxation_impl_verification_not_blocked(self, child_root):
        _init_python_repo(child_root)
        rep_c = self._run_commit(child_root)
        assert "implementation_verification" not in rep_c["gates"]["unmet"]


@pytest.mark.unit
class TestApprovalsRecheckAfterDiff:
    """approvals.recheck_after_diff: одобрение со scope, не покрывающим путь -> uncovered."""

    def test_scope_not_covering_path_uncovered_secrets(self, child_root):
        _init_python_repo(child_root)
        import approvals as appr
        appr.write_record(child_root, "mul-fn", "secrets", "u@x", "config/other.py", "ротация",
                          created_at="2026-07-05T00:00:00Z", binds_to="P",
                          expires_at="2027-01-01T00:00:00Z", risk="secret", source="user")
        rc_bad = appr.recheck_after_diff(child_root, "mul-fn", ["src/mul.py"],
                                         signals={"secret_boundary": True},
                                         now="2026-07-05T00:00:00Z", plan_hash="P")
        assert rc_bad["ok"] is False
        assert rc_bad["uncovered"][0]["domain"] == "secrets"


@pytest.mark.unit
class TestRequireTestsEscalation:
    """allow_missing_tests=False -> отсутствие тестов БЛОКИРУЕТ implementation_verification."""

    def test_require_tests_blocks_impl_verification(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it_rt = iter([{"op": "write", "path": "src/q.py", "content": "x=1\n"}, {"done": True}])
        rep_rt = execution_pipeline.run_pipeline(
            "нужны тесты", _QUICK_SIG, child_root, lambda c: next(it_rt), policy=pol,
            budget={"max_model_calls": 5}, feature="need-tests", allow_missing_tests=False)
        assert "implementation_verification" in rep_rt["gates"]["unmet"]


@pytest.mark.unit
class TestIsolateRun:
    """isolate=True: весь прогон в отдельном worktree, основное дерево не тронуто."""

    def _run_iso(self, child_root, content="y=2\n", feature="iso-fn", **kw):
        it = iter([{"op": "write", "path": "src/iso.py", "content": content}, {"done": True}])
        return execution_pipeline.run_pipeline(
            "в изоляции", _QUICK_SIG, child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature=feature,
            commit=True, isolate=True, install_deps=False, **kw)

    def test_run_in_worktree_main_untouched(self, child_root):
        _init_python_repo(child_root)
        rep_iso = self._run_iso(child_root)
        assert rep_iso["isolation"]["worktree"] == ".ai/worktrees/iso-fn"
        assert (child_root / ".ai" / "worktrees" / "iso-fn" / "src" / "iso.py").exists()
        assert not (child_root / "src" / "iso.py").exists()

    def test_commit_on_branch_evidence_exact_sha(self, child_root):
        _init_python_repo(child_root)
        rep_iso = self._run_iso(child_root)
        assert rep_iso["commit"]["branch"] == "ai-ops/iso-fn"
        assert rep_iso["commit"]["evidence_on_exact_sha"] is True

    def test_default_engine_containment(self, child_root):
        _init_python_repo(child_root)
        rep_iso = self._run_iso(child_root)
        # дефолтная политика движка (policy не передан)
        assert isinstance(rep_iso.get("containment"), dict)
        assert rep_iso["containment"]["block_push"] is True
        assert rep_iso["containment"]["sandbox"] is False
        assert rep_iso["containment"]["shell_mode"] == "unrestricted"

    def test_rerun_without_discard_honest_error(self, child_root):
        _init_python_repo(child_root)
        self._run_iso(child_root, content="y=2\n")
        # повторный прогон того же feature с несохранённым коммитом -> honest error без discard
        it2 = iter([{"op": "write", "path": "src/iso.py", "content": "y=3\n"}, {"done": True}])
        rep_guard = execution_pipeline.run_pipeline(
            "в изоляции повторно", _QUICK_SIG, child_root, lambda c: next(it2),
            budget={"max_model_calls": 5}, feature="iso-fn",
            commit=True, isolate=True, install_deps=False)
        err = rep_guard.get("error") or ""
        assert rep_guard.get("status") == "error"
        # сообщение называет РЕАЛЬНУЮ команду `ai-ops resume`, а не внутренний `(--resume)`
        assert "ai-ops resume" in err
        assert "(--resume)" not in err

    def test_discard_previous_fresh_worktree(self, child_root):
        _init_python_repo(child_root)
        self._run_iso(child_root, content="y=2\n")
        it3 = iter([{"op": "write", "path": "src/iso.py", "content": "y=4\n"}, {"done": True}])
        rep3 = execution_pipeline.run_pipeline(
            "в изоляции c discard", _QUICK_SIG, child_root, lambda c: next(it3),
            budget={"max_model_calls": 5}, feature="iso-fn",
            commit=True, isolate=True, install_deps=False, discard_previous=True)
        assert rep3.get("status") != "error"
        assert rep3["isolation"]["worktree"] == ".ai/worktrees/iso-fn"
        assert rep3["commit"]["evidence_on_exact_sha"] is True

    def test_shell_only_edit_still_commits(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol_sh = tool_broker.Policy(level="execution", write_scope=["src/"])
        it_sh = iter([
            {"op": "shell", "command": "python3 -c \"open('shelledit.py','w').write('s=1\\n')\""},
            {"done": True, "summary": "через shell"},
        ])
        rep_sh = execution_pipeline.run_pipeline(
            "правка через shell", _QUICK_SIG, child_root, lambda c: next(it_sh),
            policy=pol_sh, budget={"max_model_calls": 5}, feature="shell-fn",
            commit=True, isolate=True, install_deps=False)
        # правка только через shell (0 write-op) всё равно коммитится (не теряем работу)
        assert rep_sh["loop"]["applied_writes"] == 0
        assert bool(rep_sh["commit"]["sha"])


@pytest.mark.unit
class TestUnsavedCommitsRefusal:
    """isolate без resume/discard: ветка ai-ops/<wid> с несохранёнными коммитами -> честный отказ.

    Характеристика ДО выноса блока изоляции/base из run_pipeline (K6-глубина): эта ветвь
    (ahead>0 и not discard_previous) не покрывалась ни одним тестом.
    """

    def test_ahead_commits_block_without_discard(self, child_root):
        _init_python_repo(child_root)
        it1 = iter([{"op": "write", "path": "src/iso.py", "content": "y=1\n"}, {"done": True}])
        rep1 = execution_pipeline.run_pipeline(
            "фаза 1", _QUICK_SIG, child_root, lambda c: next(it1),
            budget={"max_model_calls": 5}, feature="ahead-fn",
            commit=True, isolate=True, install_deps=False)
        assert bool((rep1.get("commit") or {}).get("sha"))   # ветка ai-ops/ahead-fn впереди HEAD
        # второй прогон тем же feature, БЕЗ resume/discard -> отказ (несохранённые коммиты не теряем)
        it2 = iter([{"op": "write", "path": "src/iso2.py", "content": "y=2\n"}, {"done": True}])
        rep2 = execution_pipeline.run_pipeline(
            "фаза 2", _QUICK_SIG, child_root, lambda c: next(it2),
            budget={"max_model_calls": 5}, feature="ahead-fn",
            commit=True, isolate=True, install_deps=False)
        assert rep2.get("status") == "error"
        assert "несохранённых" in (rep2.get("error") or "")
        assert rep2["isolation"]["worktree"] is None   # worktree не создан, работа не тронута


@pytest.mark.unit
class TestSnapshotDelta:
    """_untracked snapshot-delta: новый untracked подготовки vs пользовательский."""

    def test_prep_untracked_in_delta_user_not(self, child_root):
        _init_git(child_root)
        (child_root / "user_note.txt").write_text("mine\n", encoding="utf-8")
        before = execution_pipeline._untracked(child_root)
        assert "user_note.txt" in before
        # подготовка создаёт НОВЫЙ untracked (эмуляция package-lock.json от npm install)
        (child_root / "package-lock.json").write_text("{}\n", encoding="utf-8")
        delta = execution_pipeline._untracked(child_root) - before
        assert delta == {"package-lock.json"}
        assert "user_note.txt" not in delta


@pytest.mark.unit
class TestResume:
    """resume=True: продолжение поверх закоммиченной фазы 1; честный fresh без прошлого."""

    def test_resume_continues_over_phase1(self, child_root):
        _init_python_repo(child_root)
        it_r1 = iter([{"op": "write", "path": "src/first.py", "content": "a=1\n"},
                      {"done": True, "summary": "фаза 1"}])
        rep_r1 = execution_pipeline.run_pipeline(
            "resume фаза 1", _QUICK_SIG, child_root, lambda c: next(it_r1),
            budget={"max_model_calls": 5}, feature="resume-fn",
            commit=True, isolate=True, install_deps=False)
        assert bool((rep_r1.get("commit") or {}).get("sha"))

        seen_r = {}
        it_r2 = iter([{"op": "write", "path": "src/second.py", "content": "b=2\n"},
                      {"done": True, "summary": "фаза 2"}])

        def _resume_prop(c):
            seen_r.setdefault("ctx", c)
            return next(it_r2)
        rep_r2 = execution_pipeline.run_pipeline(
            "resume фаза 2", _QUICK_SIG, child_root, _resume_prop,
            budget={"max_model_calls": 5}, feature="resume-fn",
            commit=True, isolate=True, install_deps=False,
            resume=True, resume_context="MARKER_RESUME_STATE_ABC")
        rinfo = rep_r2.get("resume") or {}
        # НЕ ошибка про несохранённые коммиты (продолжаем, а не падаем)
        assert rep_r2.get("status") != "error"
        assert rinfo.get("resumed") is True
        assert rinfo.get("reused_branch") is True
        # resume_context РЕАЛЬНО в prompt модели
        assert "MARKER_RESUME_STATE_ABC" in (seen_r.get("ctx") or "")
        # работа фазы 1 сохранена в worktree (продолжили поверх, не с нуля)
        wt_r = child_root / ".ai" / "worktrees" / "resume-fn"
        assert (wt_r / "src" / "first.py").exists()
        assert (wt_r / "src" / "second.py").exists()

    def test_resume_no_previous_honest_fresh(self, child_root):
        _init_python_repo(child_root)
        it_r3 = iter([{"op": "write", "path": "src/n.py", "content": "n=1\n"}, {"done": True}])
        rep_r3 = execution_pipeline.run_pipeline(
            "resume без прошлого", _QUICK_SIG, child_root, lambda c: next(it_r3),
            budget={"max_model_calls": 5}, feature="resume-none",
            commit=True, isolate=True, install_deps=False, resume=True)
        rinfo3 = rep_r3.get("resume") or {}
        assert rinfo3.get("resumed") is False
        assert bool(rinfo3.get("reason"))
        assert rep_r3.get("status") != "error"


@pytest.mark.unit
class TestSpecFirstGate:
    """spec-first: неполный spec.yaml не пускает в implementation; полный — не блокирует."""

    def test_incomplete_spec_blocks(self, child_root):
        _init_python_repo(child_root)
        import spec_levels as sl
        sl.create_spec(child_root, "spec-fn", _QUICK_SIG)  # все разделы missing
        it_sf = iter([{"op": "write", "path": "src/sf.py", "content": "s=1\n"}, {"done": True}])
        rep_sf = execution_pipeline.run_pipeline(
            "spec-first блок", _QUICK_SIG, child_root, lambda c: next(it_sf),
            budget={"max_model_calls": 5}, feature="spec-fn",
            commit=True, isolate=True, install_deps=False, baseline_diff=True)
        assert rep_sf.get("ready_for_pr") is False
        assert rep_sf["spec_first"]["ok"] is False
        assert rep_sf["spec_first"]["incomplete_sections"]

    def test_full_spec_does_not_block(self, child_root):
        _init_python_repo(child_root)
        import spec_levels as sl
        import yaml as yaml_mod
        sp = child_root / "features" / "spec-fn2" / "spec.yaml"
        sp.parent.mkdir(parents=True, exist_ok=True)
        full_secs = {s: {"status": "complete", "content": "x"} for s in sl.required_sections(0)}
        sp.write_text(yaml_mod.safe_dump({"schema_version": 1, "kind": "spec",
                      "workitem_id": "spec-fn2", "level": 0, "sections": full_secs}),
                      encoding="utf-8")
        it_sf2 = iter([{"op": "write", "path": "src/sf2.py", "content": "s=2\n"}, {"done": True}])
        rep_sf2 = execution_pipeline.run_pipeline(
            "spec-first полон", _QUICK_SIG, child_root, lambda c: next(it_sf2),
            budget={"max_model_calls": 5}, feature="spec-fn2",
            commit=True, isolate=True, install_deps=False, baseline_diff=True)
        assert rep_sf2["spec_first"]["ok"] is True
        assert not rep_sf2["spec_first"]["incomplete_sections"]


@pytest.mark.unit
class TestEnvUnqualified:
    """_env_unqualified: env-симптомы (127/No module) -> True; честный fail -> False."""

    def test_passed_check_qualified(self):
        assert execution_pipeline._env_unqualified(
            {"test": {"status": "pass"}, "build": {"status": "not_run"}}) is False

    def test_exit_127_unqualified(self):
        assert execution_pipeline._env_unqualified(
            {"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 127}]}}) is True

    def test_no_module_named_unqualified(self):
        assert execution_pipeline._env_unqualified(
            {"test": {"status": "fail",
                      "runs": [{"ok": False, "exit_code": 1,
                                "output_tail": "ModuleNotFoundError: No module named 'foo'"}]}}) is True

    def test_honest_assertion_fail_not_env(self):
        assert execution_pipeline._env_unqualified(
            {"test": {"status": "fail",
                      "runs": [{"ok": False, "exit_code": 1,
                                "output_tail": "AssertionError: 2 != 3"}]}}) is False


@pytest.mark.unit
class TestSecurityFailClosed:
    """security pack бросил -> security=fail (fail-closed, не ложный green)."""

    def test_scan_raises_security_unmet_not_ready(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        import security_pack as sp_mod
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        orig_rp = sp_mod.run_pack
        sp_mod.run_pack = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan boom"))
        try:
            it_se = iter([{"op": "write", "path": "src/se.py", "content": "s=1\n"}, {"done": True}])
            rep_se = execution_pipeline.run_pipeline(
                "скан падает", sig_eng, child_root, lambda c: next(it_se),
                policy=pol, budget={"max_model_calls": 5}, feature="scanerr-fn",
                commit=True, isolate=True, install_deps=False)
        finally:
            sp_mod.run_pack = orig_rp
        assert "security" in rep_se["gates"]["unmet"]
        assert not rep_se["ready_for_pr"]


@pytest.mark.unit
class TestSecurityForcedInQuick:
    """QUICK + новая зависимость -> security ФОРСИРОВАН в evaluated и блокирует без ApprovalRecord."""

    def test_security_forced_evaluated(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol_dep = tool_broker.Policy(level="execution", block_push=True)
        it_dep = iter([{"op": "write", "path": "requirements.txt", "content": "flask\n"}, {"done": True}])
        rep_dep = execution_pipeline.run_pipeline(
            "добавить зависимость", _QUICK_SIG, child_root, lambda c: next(it_dep),
            policy=pol_dep, budget={"max_model_calls": 5}, feature="dep-fn",
            commit=True, isolate=True, install_deps=False)
        assert "security" in rep_dep["gates"]["evaluated"]
        assert "security" in rep_dep["gates"]["unmet"]
        assert rep_dep["ready_for_pr"] is False


@pytest.mark.unit
class TestSecurityReviewerCloses:
    """Независимый security-reviewer pass закрывает needs_review домены -> security не в unmet."""

    def test_reviewer_pass_closes_security(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                                  "summary": "injection-surface чист"}
        it = iter([{"op": "write", "path": "src/clean.py", "content": "def f():\n    return 1\n"},
                   {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "чистая правка", sig_eng, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 8}, feature="secrev-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=sec_reviewer)
        assert "security" not in rep["gates"]["unmet"]


@pytest.mark.unit
class TestSecurityGuard5:
    """#5-guard: qualified судья не берёт; нет судьи+нет ApprovalRecord -> fail + называет ApprovalRecord."""

    def _sec_result(self, rep):
        return next((g for g in rep["gates"].get("gate_results", [])
                     if g.get("gate") == "security"), {})

    @staticmethod
    def _has(g, sub):
        return any(sub in b for b in (g.get("blockers") or []))

    def _sec_reviewer(self):
        return lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                          "summary": "injection-surface чист"}

    def test_qualified_judge_skips_guard5(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig_api = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "api_change": True}
        it_q = iter([{"op": "write", "path": "src/rl_a.py", "content": "def a():\n    return 1\n"}, {"done": True}])
        rep_q = execution_pipeline.run_pipeline(
            "api rate strict-on", sig_api, child_root, lambda c: next(it_q),
            policy=pol, budget={"max_model_calls": 8}, feature="rl-q-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=self._sec_reviewer(), strict_judge_qualified=True)
        sec_a = self._sec_result(rep_q)
        # qualified судья -> reviewer-ветка: #5 pending_human-guard НЕ берётся
        assert not self._has(sec_a, "нет QUALIFIED security-судьи")

    def test_no_qualified_judge_no_approval_fails(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig_api = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "api_change": True}
        it = iter([{"op": "write", "path": "src/rl_b.py", "content": "def b():\n    return 1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "api rate strict-off", sig_api, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 8}, feature="rl-b-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=self._sec_reviewer(), strict_judge_qualified=False)
        sec_b = self._sec_result(rep)
        assert "security" in rep["gates"]["unmet"]
        assert sec_b.get("status") == "fail"
        assert self._has(sec_b, "нет QUALIFIED security-судьи")
        # блокер называет ApprovalRecord (человеку даётся путь закрыть)
        assert self._has(sec_b, "ApprovalRecord")


@pytest.mark.unit
class TestReevaluateOnly:
    """re-evaluate-only: человеко-одобрение снимает #5-блок БЕЗ переавторинга кода."""

    def test_approval_lifts_guard5_via_reevaluate(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        import security_pack as sp_re
        import approvals as appr_re
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                                  "summary": "чист"}
        sig_q = {"task_type": "QUICK", "size": "small", "risk": "low",
                 "affected_areas": ["api"], "api_change": True}
        it_q1 = iter([{"op": "write", "path": "rq.py", "content": "def rq():\n    return 1\n"}, {"done": True}])
        execution_pipeline.run_pipeline(
            "quick api sec", sig_q, child_root, lambda c: next(it_q1), policy=pol,
            budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
            install_deps=False, review=True, reviewer_proposer=sec_reviewer,
            strict_judge_qualified=False)
        nrq = sp_re.run_pack(files_content={"rq.py": "def rq():\n    return 1\n"},
                             signals=sig_q).get("needs_review") or ["rate_limiting"]
        rf = child_root / "features" / "reeval-fn"
        rf.mkdir(parents=True, exist_ok=True)
        (rf / "run-plan.yaml").write_text("base_workflow: QUICK\ngates: [security]\n", encoding="utf-8")
        for d in nrq:
            appr_re.write_record(child_root, "reeval-fn", approval=d, approved_by="human@owner",
                                 scope=f"security {d}", reason="человек одобрил (reeval тест)",
                                 created_at="2026-07-29", expires_at="2026-12-31",
                                 risk="medium", source="human")
        rep_re = execution_pipeline.run_pipeline(
            "quick api sec", sig_q, child_root, lambda c: {"done": True}, policy=pol,
            budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
            install_deps=False, review=True, reviewer_proposer=sec_reviewer,
            strict_judge_qualified=False, reevaluate_only=True)
        sec_re = next((g for g in rep_re["gates"].get("gate_results", [])
                       if g.get("gate") == "security"), {})
        assert (rep_re.get("loop") or {}).get("stopped") == "reevaluate-only"
        assert not any("нет QUALIFIED security-судьи" in b for b in (sec_re.get("blockers") or []))


@pytest.mark.unit
class TestSecretBoundary:
    """secret_boundary требует человека даже при pass ревьюера."""

    def test_secret_boundary_without_human_blocks(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "secret_boundary": True}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass", "summary": "чист"}  # noqa: E731
        it_sb = iter([{"op": "write", "path": "src/sb.py", "content": "def g():\n    return 2\n"}, {"done": True}])
        rep_sb = execution_pipeline.run_pipeline(
            "граница секретов", sig_eng, child_root, lambda c: next(it_sb),
            policy=pol, budget={"max_model_calls": 8}, feature="sb-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=sec_reviewer)
        assert "security" in rep_sb["gates"]["unmet"]


@pytest.mark.unit
class TestSpecDepthEngineering:
    """spec-depth: ENGINEERING без --author -> незакрытые разделы уровня -> блок."""

    def test_eng_without_author_blocked(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it_sd = iter([{"op": "write", "path": "src/sd.py", "content": "x=1\n"}, {"done": True}])
        rep_sd = execution_pipeline.run_pipeline(
            "eng без артефактов", sig_eng, child_root, lambda c: next(it_sd),
            policy=pol, budget={"max_model_calls": 5}, feature="sd-fn",
            commit=True, isolate=True, install_deps=False)
        assert rep_sd["spec_depth"]["ok"] is False
        assert rep_sd["spec_depth"]["missing"]
        assert rep_sd["ready_for_pr"] is False


@pytest.mark.unit
class TestDiffChecksStackSwaps:
    """structured-id diff: swap упавших тестов = регрессия; тот же id/другое время = нет."""

    def test_pytest_swap_same_count_different_test(self):
        base = {"test": {"status": "fail", "runs": [{"output_tail":
                "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        swap = {"test": {"status": "fail", "runs": [{"output_tail":
                "FAILED tests/test_b.py::test_two\n1 failed, 10 passed"}]}}
        assert execution_pipeline._diff_checks(base, swap) == (["test"], [])

    def test_pytest_same_test_same_id_no_regression(self):
        base = {"test": {"status": "fail", "runs": [{"output_tail":
                "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        same = {"test": {"status": "fail", "runs": [{"output_tail":
                "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        assert execution_pipeline._diff_checks(base, same) == ([], [])

    def test_unparseable_after_no_fabricated_fixed(self):
        s10_base = {"test": {"status": "fail", "runs": [{"output_tail":
                    "FAILED test_task.py::test_target\nFAILED test_legacy.py::test_old\n2 failed"}]}}
        after = {"test": {"status": "fail", "runs": [{"output_tail": "BUILD FAILED"}]}}
        assert execution_pipeline._diff_checks(s10_base, after) == ([], [])

    def test_red_base_node_fixed_preexisting_remains(self):
        s10_base = {"test": {"status": "fail", "runs": [{"output_tail":
                    "FAILED test_task.py::test_target\nFAILED test_legacy.py::test_old\n2 failed"}]}}
        s10_after = {"test": {"status": "fail", "runs": [{"output_tail":
                     "FAILED test_legacy.py::test_old\n1 failed, 1 passed"}]}}
        assert execution_pipeline._diff_checks(s10_base, s10_after) == ([], ["test"])

    def test_go_swap_same_package_regression(self):
        go_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "--- FAIL: TestSub (0.00s)\n    calc_test.go:13: Sub(5,2) = 3; want 999\nFAIL\nFAIL\tcalc\t0.002s\nFAIL"}]}}
        go_add = {"test": {"status": "fail", "runs": [{"output_tail":
                  "--- FAIL: TestAdd (0.00s)\n    calc_test.go:6: Add(2,3) = 6; want 5\nFAIL\nFAIL\tcalc\t0.003s\nFAIL"}]}}
        assert "TestSub" in execution_pipeline._failure_ids(go_sub["test"])
        assert execution_pipeline._diff_checks(go_sub, go_add) == (["test"], [])

    def test_go_same_test_different_time_no_regression(self):
        go_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "--- FAIL: TestSub (0.00s)\n    calc_test.go:13: Sub(5,2) = 3; want 999\nFAIL\nFAIL\tcalc\t0.002s\nFAIL"}]}}
        go_sub2 = {"test": {"status": "fail", "runs": [{"output_tail":
                   "--- FAIL: TestSub (0.01s)\n    calc_test.go:13: Sub(5,2) = 3; want 999\nFAIL\nFAIL\tcalc\t0.009s\nFAIL"}]}}
        assert execution_pipeline._diff_checks(go_sub, go_sub2) == ([], [])

    def test_rust_panic_swap_regression(self):
        rs_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "thread 'tests::test_sub' (13663) panicked at src/lib.rs:10:21:\nassertion `left == right` failed\n"
                  "failures:\n    tests::test_sub\ntest result: FAILED. 1 passed; 1 failed; finished in 0.28s\n"
                  "error: test failed, to rerun pass `--lib`"}]}}
        rs_add = {"test": {"status": "fail", "runs": [{"output_tail":
                  "thread 'tests::test_add' (13999) panicked at src/lib.rs:8:21:\nassertion `left == right` failed\n"
                  "failures:\n    tests::test_add\ntest result: FAILED. 1 passed; 1 failed; finished in 0.19s\n"
                  "error: test failed, to rerun pass `--lib`"}]}}
        assert any("tests::test_sub" in i for i in execution_pipeline._failure_ids(rs_sub["test"]))
        assert execution_pipeline._diff_checks(rs_sub, rs_add) == (["test"], [])

    def test_rust_same_test_different_pid_no_regression(self):
        rs_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "thread 'tests::test_sub' (13663) panicked at src/lib.rs:10:21:\nassertion `left == right` failed\n"
                  "failures:\n    tests::test_sub\ntest result: FAILED. 1 passed; 1 failed; finished in 0.28s\n"
                  "error: test failed, to rerun pass `--lib`"}]}}
        rs_sub2 = {"test": {"status": "fail", "runs": [{"output_tail":
                   "thread 'tests::test_sub' (55555) panicked at src/lib.rs:10:21:\nassertion `left == right` failed\n"
                   "failures:\n    tests::test_sub\ntest result: FAILED. 1 passed; 1 failed; finished in 0.30s\n"
                   "error: test failed, to rerun pass `--lib`"}]}}
        assert execution_pipeline._diff_checks(rs_sub, rs_sub2) == ([], [])

    def test_java_class_method_failure_id(self):
        jv_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "[ERROR] CalcTest.testSub -- Time elapsed: 0.007 s <<< FAILURE!\n"
                  "org.opentest4j.AssertionFailedError: expected: <999> but was: <3>\n"
                  "[ERROR]   CalcTest.testSub:5 expected: <999> but was: <3>\n"
                  "[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0"}]}}
        assert any("CalcTest.testSub" in i for i in execution_pipeline._failure_ids(jv_sub["test"]))

    def test_tsc_new_error_new_file_regression(self):
        base_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                   "src/a.ts(3,5): error TS2322: Type error"}]}}
        new_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                  "src/a.ts(3,5): error TS2322: Type error\nsrc/b.ts(9,1): error TS2531: Object is possibly null"}]}}
        assert execution_pipeline._diff_checks(base_ts, new_ts) == (["typecheck"], [])

    def test_coverage_loss_fail_to_warn_regression(self):
        assert execution_pipeline._diff_checks(
            {"test": {"status": "fail"}}, {"test": {"status": "warn"}}) == (["test"], [])

    def test_new_red_not_run_to_fail_regression(self):
        assert execution_pipeline._diff_checks(
            {"x": {"status": "not_run"}}, {"x": {"status": "fail"}}) == (["x"], [])


@pytest.mark.unit
class TestBaselineDoesNotBypassGates:
    """P0.1: baseline-diff НЕ обходит прочие блокирующие гейты (ux_review без evidence)."""

    def test_ui_changed_ux_review_blocks_despite_no_regressions(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        sig_ui = dict(_QUICK_SIG, ui_changed=True)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "baseline не обходит гейты", sig_ui, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 5}, feature="p01-fn",
            commit=True, baseline_diff=True)
        assert rep["gates"]["other_blocking_unmet"]
        assert rep["ready_for_pr"] is False

    def test_gate_results_and_tested_revision_in_report(self, child_root):
        _init_python_repo(child_root)
        import tool_broker
        sig_ui = dict(_QUICK_SIG, ui_changed=True)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "baseline gate_results", sig_ui, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 5}, feature="p01b-fn",
            commit=True, baseline_diff=True)
        assert isinstance(rep["gates"]["gate_results"], list)
        assert rep["gates"]["tested_revision"] == rep["commit"]["sha"]


@pytest.mark.unit
class TestReviewUiGateBlocksWithoutReview:
    """ui_changed -> ux_review в evaluated+unmet, reviews=None без --review."""

    def test_ux_review_blocks_without_reviewer(self, child_root):
        _init_python_repo(child_root)
        sig_rv = dict(_QUICK_SIG, ui_changed=True)
        it = iter([{"op": "write", "path": "src/nr.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "ui без ревью", sig_rv, child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="nr-fn",
            commit=True, isolate=True, install_deps=False)
        assert "ux_review" in rep["gates"]["evaluated"]
        assert "ux_review" in rep["gates"]["unmet"]
        assert rep["reviews"] is None


@pytest.mark.unit
class TestReviewContentlessWarn:
    """rc11: contentless warn (без blockers) -> вердикт невалиден (errors), гейт остаётся unmet."""

    def test_warn_without_blockers_invalid_verdict(self, child_root):
        _init_python_repo(child_root)
        sig_rv = dict(_QUICK_SIG, ui_changed=True)
        cwarn = lambda p: '{"kind":"reviewer-result","status":"warn","checks":[{"id":"x","status":"warn"}]}'  # noqa: E731
        it = iter([{"op": "write", "path": "src/cw.py", "content": "c=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "ui с ревью warn без причины", sig_rv, child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="cw-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=cwarn)
        assert "ux_review" in rep["gates"]["unmet"]
        assert any(r["gate"] == "ux_review" and r.get("errors") for r in (rep["reviews"] or []))


@pytest.mark.unit
class TestChangeContextRangeDegradation:
    """_change_context_range без base -> только последний коммит (rA не виден)."""

    def test_without_base_only_last_commit(self, child_root):
        _init_git(child_root)
        (child_root / "src").mkdir(exist_ok=True)
        (child_root / "src" / "rA.py").write_text("A = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "pkgA"], cwd=child_root, capture_output=True)
        (child_root / "src" / "rB.py").write_text("B = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "pkgB"], cwd=child_root, capture_output=True)
        _, head_r, _ = execution_pipeline._git(child_root, "rev-parse", "HEAD")
        single = execution_pipeline._change_context_range(child_root, None, head_r.strip())
        assert "src/rB.py" in single
        assert "src/rA.py" not in single


@pytest.mark.unit
class TestEvidenceRefSameBasename:
    """EvidenceRef: same-basename другой путь -> 'которого нет среди реально прочитанных'."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def _dom_ev(self, ev):
        return {"schema_version": 1, "kind": "reviewer-result", "gate": "security", "status": "pass",
                "reviewed_revision": "abc123", "checks": [{"id": "c", "status": "pass"}],
                "domain_results": [{"domain": "injection", "status": "pass",
                                    "checks": [{"id": "injection_ok", "status": "pass"}], "evidence": ev}]}

    def test_same_basename_different_path_invalid(self):
        errs = execution_pipeline._security_verdict_errors(
            self._dom_ev([{"type": "code-read", "path": "src/prod/config.py"}]),
            "abc123", ["injection"], self._make_vrr(), reviewer_reads=["tests/config.py"])
        assert any("которого нет среди реально прочитанных" in e for e in errs)


@pytest.mark.unit
class TestApprovalsRecordValid:
    """approvals._record_valid: рыхлая destructive-запись невалидна в обоих режимах."""

    def test_loose_destructive_invalid_both_modes(self):
        import approvals as a4
        loose = {"approval": "destructive", "approved_by": "u@x", "scope": ".", "reason": "ok"}
        assert a4._record_valid(loose, now=a4._now_iso(), plan_hash="x") is False
        assert a4._record_valid(loose, now=a4._now_iso(), plan_hash="x", strict=True) is False

    def test_bound_destructive_passes_nonstrict_not_strict(self):
        import approvals as a4
        bound = {"approval": "destructive", "approved_by": "u@x", "scope": ".",
                 "reason": "ok", "binds_to": "x"}
        assert a4._record_valid(bound, now=a4._now_iso(), plan_hash="x") is True
        assert a4._record_valid(bound, now=a4._now_iso(), plan_hash="x", strict=True) is False


@pytest.mark.unit
class TestHumanApprovalDomains:
    """_human_approval_domains_uncovered: Dockerfile/.github -> deployment_config; src -> []."""

    def test_dockerfile_requires_deployment_config(self, child_root):
        _init_git(child_root)
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["Dockerfile", "src/x.py"])

    def test_github_workflows_requires_deployment_config(self, child_root):
        _init_git(child_root)
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", [".github/workflows/deploy.yml"])

    def test_regular_src_no_human_approval(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["src/app.py", "tests/t.py"]) == []

    def test_legacy_loose_approval_does_not_close(self, child_root):
        _init_git(child_root)
        import yaml as yaml_mod
        ad = child_root / "features" / "no-wi" / "approvals"
        ad.mkdir(parents=True, exist_ok=True)
        (ad / "deployment_config.yaml").write_text(yaml_mod.safe_dump(
            {"schema_version": 1, "kind": "ApprovalRecord", "approval": "deployment_config",
             "approved_by": "u@x", "scope": ".", "reason": "ok"}, allow_unicode=True), encoding="utf-8")
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["Dockerfile"])


@pytest.mark.unit
class TestBaseBinding:
    """BASE BINDING: рабочая ветка форкается от --base, а не от текущего HEAD."""

    def test_worktree_forked_from_base(self, child_root):
        _init_python_repo(child_root)
        orig = _head_branch(child_root)
        execution_pipeline._git(child_root, "checkout", "-q", "-B", "feat-base")
        (child_root / "src").mkdir(exist_ok=True)
        (child_root / "src" / "on_feat.py").write_text("FEAT = 1\n", encoding="utf-8")
        execution_pipeline._git(child_root, "add", "-A")
        execution_pipeline._git(child_root, "commit", "-q", "-m", "commit on feat-base")
        execution_pipeline._git(child_root, "checkout", "-q", orig)  # checkout НЕ на feat-base
        it = iter([{"op": "write", "path": "src/bb.py", "content": "b=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "base binding", _QUICK_SIG, child_root, lambda c: next(it),
            budget={"max_model_calls": 8}, feature="bb-fn",
            commit=True, isolate=True, install_deps=False, base="feat-base")
        wt_bb = child_root / ".ai" / "worktrees" / "bb-fn"
        forked_ok = (wt_bb / "src" / "on_feat.py").exists() if wt_bb.is_dir() else False
        assert rep.get("status") != "error"
        assert forked_ok
        assert (rep.get("base_binding") or {}).get("base_ref") == "feat-base"


@pytest.mark.unit
class TestResolveBaseAuto:
    """_resolve_base auto -> реальная ветка (не 'main'-хардкод); _verify_remote_base reason truthy."""

    def test_auto_resolves_to_current_branch(self, child_root):
        _init_git(child_root)
        orig = _head_branch(child_root)
        ab = execution_pipeline._resolve_base(child_root, None)
        assert ab.get("resolved") is True
        assert ab.get("mode") == "auto"
        assert ab.get("base_ref") == orig
        assert ab.get("base_sha")

    def test_verify_remote_base_reason_truthy(self, child_root):
        _init_git(child_root)
        orig = _head_branch(child_root)
        base_sha = execution_pipeline._resolve_base(child_root, orig).get("base_sha")
        rvb = execution_pipeline._verify_remote_base(child_root, orig, base_sha)
        assert rvb.get("verdict") == "unverifiable"
        assert rvb.get("reason")


@pytest.mark.unit
class TestBasePreflightNoModel:
    """base-preflight: явная несуществующая base -> блок ДО модели (0 вызовов, нет worktree)."""

    def test_nonexistent_base_zero_model_calls_no_worktree(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/nb.py", "content": "n=1\n"}, {"done": True}])
        model_calls = {"n": 0}

        def counting_prop(c):
            model_calls["n"] += 1
            return next(it)
        rep = execution_pipeline.run_pipeline(
            "несуществующая база", _QUICK_SIG, child_root, counting_prop,
            budget={"max_model_calls": 8}, feature="nb-fn",
            commit=True, isolate=True, open_pr=True, install_deps=False,
            base="no-such-branch-xyz")
        assert rep.get("status") == "error"
        assert rep.get("ready_for_pr") is False
        assert (rep.get("base_binding") or {}).get("resolved") is False
        assert "base-preflight" in (rep.get("error") or "")
        assert model_calls["n"] == 0
        assert not (child_root / ".ai" / "worktrees" / "nb-fn").exists()


@pytest.mark.unit
class TestAuthoringEngineering:
    """Product Authoring: ENGINEERING-план и артефакт-гейты requirements/plan_readiness."""

    def _sig_eng(self):
        return {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}

    def _author_provider(self, prompt):
        if "requirements-artifact" in prompt:
            return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                    "  - id: R1\n    statement: фильтр по статусу сужает список\n"
                    "    acceptance:\n      - when статус=paid then только оплаченные\n")
        if "spec-change" in prompt:
            return ("schema_version: 1\nkind: spec-change\ncapability: catalog\nwhy: нужен фильтр\n"
                    "what_changes:\n  - добавить фильтр по статусу\ntasks:\n  - реализовать\n"
                    "requirements:\n  - name: Filter\n    text: The system SHALL filter by status.\n"
                    "    scenarios:\n      - {name: T, when: статус=paid, then: показаны оплаченные}\n")
        return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                "  - id: WP1\n    summary: добавить фильтр\n    depends_on: []\n"
                "write_scope:\n  - src/\n")

    def test_engineering_plan_has_artifact_gates_evaluated(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/na.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор без артефактов", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-na",
            commit=True, isolate=True, install_deps=False)
        assert "requirements" in rep["gates"]["evaluated"]
        assert "plan_readiness" in rep["gates"]["evaluated"]

    def test_without_author_artifact_gates_unmet(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/na.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор без артефактов", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-na2",
            commit=True, isolate=True, install_deps=False)
        assert "requirements" in rep["gates"]["unmet"]
        assert "plan_readiness" in rep["gates"]["unmet"]
        assert rep["authored"] is None

    def test_valid_artifact_closes_gates_and_runs_impl(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/au.py", "content": "a=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с артефактами", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-au",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=self._author_provider)
        assert "requirements" not in rep["gates"]["unmet"]
        assert "plan_readiness" not in rep["gates"]["unmet"]
        assert rep["authored"] and all(a["valid"] for a in rep["authored"])
        assert (child_root / ".ai" / "worktrees" / "eng-au" / ".ai" / "runplan" / "eng-au" / "requirements.yaml").exists()
        # валидная спека -> реализация запущена
        assert (child_root / ".ai" / "worktrees" / "eng-au" / "src" / "au.py").exists()
        assert rep["spec_first"]["prestage"]["implementation_skipped"] is False

    def test_invalid_artifact_keeps_requirements_blocking_no_code(self, child_root):
        _init_python_repo(child_root)
        bad_author = lambda prompt: "это не yaml артефакта, просто текст"  # noqa: E731
        it = iter([{"op": "write", "path": "src/ba.py", "content": "b=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с битым артефактом", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-ba",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=bad_author)
        assert "requirements" in rep["gates"]["unmet"]
        assert any(not a["valid"] for a in (rep["authored"] or []))
        # невалидная спека -> tool loop НЕ запущен, код НЕ записан
        assert rep["loop"]["stopped"] == "spec-prestage-failed"
        assert rep["spec_first"]["prestage"]["implementation_skipped"] is True
        assert rep["ready_for_pr"] is False
        assert not (child_root / ".ai" / "worktrees" / "eng-ba" / "src" / "ba.py").exists()

    def test_flaky_author_retry_restores_valid_form(self, child_root):
        _init_python_repo(child_root)

        def flaky_author(prompt):
            if "[повтор" not in prompt:
                return "(пустой ответ модели)"
            return self._author_provider(prompt)
        it = iter([{"op": "write", "path": "src/fk.py", "content": "f=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с флаки-автором", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="eng-fk",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=flaky_author)
        assert "requirements" not in rep["gates"]["unmet"]
        assert rep["authored"] and all(a["valid"] for a in rep["authored"])

    def test_always_flaky_author_keeps_gate_blocking(self, child_root):
        _init_python_repo(child_root)
        always_bad = lambda prompt: "(пустой ответ модели)"  # noqa: E731
        it = iter([{"op": "write", "path": "src/ab.py", "content": "b=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с вечно-битым автором", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="eng-ab",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=always_bad)
        assert "requirements" in rep["gates"]["unmet"]
        assert any(not a["valid"] for a in (rep["authored"] or []))


@pytest.mark.unit
class TestRunAuthoringSpecEdges:
    """_run_authoring: битый spec не закрывается; task с двоеточием нормализуется."""

    def _spec_author(self, prompt):
        return (
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита цены\n"
            "what_changes:\n  - добавить formatPrice\ntasks:\n  - реализовать\n  - тест\n"
            "requirements:\n  - name: Formatting\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: formatPrice(1000), then: returns 1 000}\n")

    def test_cli_ok_closes_specification(self, child_root):
        _init_git(child_root)
        gev, _auth, _ = execution_pipeline._run_authoring(
            self._spec_author, child_root, ["specification"], {}, "spec-ok",
            "форматирование цены", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" in gev
        assert gev["specification"]["provided"] == ["openspec_valid", "requirements_covered"]
        assert (child_root / "openspec" / "changes" / "spec-ok" / "proposal.md").exists()

    def test_broken_spec_not_closed(self, child_root):
        _init_git(child_root)
        gev, auth, _ = execution_pipeline._run_authoring(
            lambda p: "не yaml", child_root, ["specification"], {}, "spec-bad",
            "x", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" not in gev
        assert any(a["gate"] == "specification" and not a["valid"] for a in auth)

    def test_task_with_colon_normalized_valid(self, child_root):
        _init_git(child_root)
        colon_author = lambda prompt: (  # noqa: E731
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита\n"
            "what_changes:\n  - добавить formatPrice\n"
            "tasks:\n  - Написать unit-тесты: все ветвления, граничные значения, ошибочный ввод\n  - реализовать\n"
            "requirements:\n  - name: Fmt\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: x, then: y}\n")
        _gev, auth, _ = execution_pipeline._run_authoring(
            colon_author, child_root, ["specification"], {}, "spec-colon",
            "цена", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert any(a["gate"] == "specification" and a["valid"] for a in auth)
