"""Юнит-тесты execution_pipeline: базовый прогон run_pipeline, коммит/изоляция/резюм/loop."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _QUICK_SIG, _head_branch, _init_git, _init_python_repo


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
class TestRunPipelineCommit:
    """Tests for run_pipeline with commit=True — SHA, tree cleanliness, evidence."""

    def test_commit_creates_sha_and_branch(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import tool_broker
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
class TestRunPipelinePlan:
    """Tests for run_pipeline with pre-built plan."""

    def test_external_plan_used(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import run_plan
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
        from ai_ops_kit.engine import tool_broker
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
class TestPipelineLoopReport:
    """Петля/отчёт run_pipeline: точные значения полей (dry QUICK, python-профиль)."""

    def _run_dry(self, child_root):
        from ai_ops_kit.engine import tool_broker
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
        from ai_ops_kit.engine import tool_broker
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
        from ai_ops_kit.engine import tool_broker
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
        from ai_ops_kit.gates import approvals as appr
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
        from ai_ops_kit.engine import tool_broker
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
        from ai_ops_kit.engine import tool_broker
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
