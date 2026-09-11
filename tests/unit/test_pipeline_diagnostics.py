"""Юнит-тесты execution_pipeline: диагностика — failure-id, diff-проверки, git-хелперы, baseline."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _init_git


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
