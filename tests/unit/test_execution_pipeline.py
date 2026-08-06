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
        _aws = "AKIA" + "IOSFODNN7EXAMPLE"
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
