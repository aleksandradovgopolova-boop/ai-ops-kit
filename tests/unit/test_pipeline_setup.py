"""Юнит-тесты execution_pipeline: подготовка прогона — база, профиль, контекст, окружение."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _QUICK_SIG, _head_branch, _init_git, _init_python_repo


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
class TestInstallDependencies:
    """Tests for _install_dependencies — stack dependency installation."""

    def test_install_with_valid_command(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [{"language": "python", "install_command": "true"}]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 1
        assert results[0]["ok"] is True

    def test_install_skips_none_command(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [{"language": "go", "install_command": None}]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 0

    def test_install_deduplicates_commands(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": [
            {"language": "node", "install_command": "true"},
            {"language": "python", "install_command": "true"},
        ]}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert len(results) == 1

    def test_install_empty_stacks(self, child_root):
        _init_git(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", child_root=str(child_root))
        profile = {"stacks": []}
        results = execution_pipeline._install_dependencies(profile, child_root, pol)
        assert results == []


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
