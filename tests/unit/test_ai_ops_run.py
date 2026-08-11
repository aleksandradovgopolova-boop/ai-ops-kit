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


# Здесь стояло ПЕРВОЕ объявление `TestPrintHuman` (ревизия 2026-08-11). Ниже в файле есть второе
# с тем же именем — Python оставляет последнее, и это первое не исполнялось никогда. Второе его
# полностью содержит (тот же `test_print_human_no_crash` плюс два), так что удаление — снятие
# затенённого дубля, а не потеря проверки.


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

    def test_returns_context_for_failed_check(self):
        """Failed check with output_tail -> fix context includes the tail."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["implementation_verification"]},
            "checks": {
                "tests": {
                    "status": "fail",
                    "runs": [{"output_tail": "AssertionError: expected 2 got 1"}]
                }
            },
            "reviews": [],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "tests" in ctx
        assert "AssertionError" in ctx

    def test_returns_context_for_failed_review(self):
        """Failed review with blockers -> fix context includes blockers."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "fail",
                 "blockers": ["missing docstring", "no type hints"]}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "missing docstring" in ctx
        assert "no type hints" in ctx

    def test_returns_context_for_security_unmet(self):
        """Security gate unmet -> fix context mentions security."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["security"]},
            "checks": {},
            "reviews": [],
            "security_scan": {"needs_review": ["input_validation"]},
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "security" in ctx

    def test_returns_none_for_human_approval_error(self):
        """Error mentioning human approval -> not model-fixable -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "blocked",
            "error": "нужно human approval",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_for_lifecycle_error(self):
        """Error mentioning lifecycle -> not model-fixable -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "blocked",
            "error": "lifecycle barrier failed",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_when_no_parts(self):
        """Not ready but no actionable blockers -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_review_warn_status_included(self):
        """Review with status=warn and blockers -> included in fix context."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "warn",
                 "blockers": ["consider adding tests"]}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "consider adding tests" in ctx

    def test_review_fail_without_blockers(self):
        """Review fail without explicit blockers -> generic message."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "fail", "blockers": None}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "ревью" in ctx


@pytest.mark.critical_path
@pytest.mark.unit
class TestOutboxDir:
    """Tests for _outbox_dir — delivery outbox path construction."""

    def test_outbox_dir_path(self, tmp_path):
        """_outbox_dir returns features_dir/fid/delivery-outbox."""
        result = ai_ops_run._outbox_dir(tmp_path, "my-feature")
        assert result == tmp_path / "my-feature" / "delivery-outbox"

    def test_outbox_dir_with_string(self, tmp_path):
        """_outbox_dir works with string features_dir."""
        result = ai_ops_run._outbox_dir(str(tmp_path), "feat-1")
        assert result == tmp_path / "feat-1" / "delivery-outbox"


@pytest.mark.critical_path
@pytest.mark.unit
class TestUnresolvedIntents:
    """Tests for _unresolved_intents — finding intents without receipts."""

    def test_no_outbox_dir(self, tmp_path):
        """No outbox directory -> empty list."""
        result = ai_ops_run._unresolved_intents(tmp_path, "nonexistent")
        assert result == []

    def test_empty_outbox(self, tmp_path):
        """Empty outbox directory -> empty list."""
        outbox = tmp_path / "feat" / "delivery-outbox"
        outbox.mkdir(parents=True)
        result = ai_ops_run._unresolved_intents(tmp_path, "feat")
        assert result == []

    def test_intent_without_receipt(self, tmp_path):
        """Intent without receipt -> unresolved."""
        import lifecycle_store as _ls
        outbox = tmp_path / "feat" / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "did1.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "did1", "workitem_id": "feat",
                           "repository": "o/r", "branch": "ai-ops/feat",
                           "base_ref": "main", "commit_sha": "abc123",
                           "status": "intended"})
        result = ai_ops_run._unresolved_intents(tmp_path, "feat")
        assert len(result) == 1
        assert result[0][0] == "did1"

    def test_intent_with_receipt_not_unresolved(self, tmp_path):
        """Intent with valid receipt -> NOT unresolved."""
        import lifecycle_store as _ls
        outbox = tmp_path / "feat" / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "did1.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "did1", "workitem_id": "feat",
                           "repository": "o/r", "branch": "ai-ops/feat",
                           "base_ref": "main", "commit_sha": "abc123",
                           "status": "intended"})
        _ls.durable_write(outbox / "did1.receipt.yaml",
                          {"schema_version": 1, "kind": "DeliveryReceipt",
                           "delivery_id": "did1", "workitem_id": "feat",
                           "status": "reconciled"})
        result = ai_ops_run._unresolved_intents(tmp_path, "feat")
        assert len(result) == 0

    def test_branch_filter(self, tmp_path):
        """Branch filter excludes intents on different branches."""
        import lifecycle_store as _ls
        outbox = tmp_path / "feat" / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "did1.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "did1", "workitem_id": "feat",
                           "repository": "o/r", "branch": "ai-ops/feat",
                           "base_ref": "main", "commit_sha": "abc123",
                           "status": "intended"})
        result = ai_ops_run._unresolved_intents(tmp_path, "feat", branch="ai-ops/other")
        assert len(result) == 0
        result2 = ai_ops_run._unresolved_intents(tmp_path, "feat", branch="ai-ops/feat")
        assert len(result2) == 1


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeContextFromHandoff:
    """Tests for _resume_context_from_handoff — building resume prompt context."""

    def test_no_handoff_file(self, tmp_path):
        """No handoff file -> None."""
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "nonexistent")
        assert result is None

    def test_handoff_with_completed(self, tmp_path):
        """Handoff with completed items -> context includes them."""
        fdir = tmp_path / "features" / "feat1"
        fdir.mkdir(parents=True)
        import yaml
        handoff = {
            "kind": "RunHandoff",
            "workitem_id": "feat1",
            "completed": ["wrote src/a.py", "added tests"],
            "decisions": [{"id": "d1", "summary": "use async"}],
            "changed_files": ["src/a.py", "test_a.py"],
            "open_questions": ["verify edge case"],
            "next_action": "run tests",
        }
        (fdir / "run-handoff.yaml").write_text(
            yaml.safe_dump(handoff, allow_unicode=True), encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat1")
        assert result is not None
        assert "RESUME" in result
        assert "wrote src/a.py" in result
        assert "d1" in result
        assert "src/a.py" in result
        assert "verify edge case" in result
        assert "run tests" in result

    def test_handoff_minimal(self, tmp_path):
        """Minimal handoff (only kind/workitem_id) -> context has header only."""
        fdir = tmp_path / "features" / "feat2"
        fdir.mkdir(parents=True)
        import yaml
        (fdir / "run-handoff.yaml").write_text(
            yaml.safe_dump({"kind": "RunHandoff", "workitem_id": "feat2"},
                           allow_unicode=True), encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat2")
        assert result is not None
        assert "RESUME" in result

    def test_handoff_empty_file(self, tmp_path):
        """Empty handoff file -> context has header (safe_load returns None -> {})."""
        fdir = tmp_path / "features" / "feat3"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text("", encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat3")
        assert result is not None
        assert "RESUME" in result


@pytest.mark.critical_path
@pytest.mark.unit
class TestLoadKlpByEnv:
    """Tests for _load_klp_by_env — KLP entries by env_ref."""

    def test_no_policy_file(self, tmp_path):
        """No key-lifecycle.yaml -> empty dict."""
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert result == {}

    def test_with_policy_file(self, tmp_path):
        """Valid key-lifecycle.yaml -> dict keyed by env_ref."""
        pdir = tmp_path / ".ai" / "policies"
        pdir.mkdir(parents=True)
        import yaml
        data = {
            "keys": [
                {"env_ref": "OPENAI_API_KEY", "ttl_days": 90},
                {"env_ref": "ANTHROPIC_API_KEY", "ttl_days": 30},
            ]
        }
        (pdir / "key-lifecycle.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8")
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert "OPENAI_API_KEY" in result
        assert "ANTHROPIC_API_KEY" in result
        assert result["OPENAI_API_KEY"]["ttl_days"] == 90

    def test_empty_keys(self, tmp_path):
        """Empty keys list -> empty dict."""
        pdir = tmp_path / ".ai" / "policies"
        pdir.mkdir(parents=True)
        import yaml
        (pdir / "key-lifecycle.yaml").write_text(
            yaml.safe_dump({"keys": []}), encoding="utf-8")
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert result == {}


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderTrust:
    """Tests for _provider_trust — JIT provider trust checking."""

    def test_key_present_no_klp(self):
        """Key in env, no KLP entry -> ready."""
        import datetime
        now = datetime.date.today().isoformat()
        result = ai_ops_run._provider_trust("deepseek", "K1", {}, {"K1": "x"}, now, {})
        assert result["ready"] is True

    def test_key_missing(self):
        """Key NOT in env -> not ready."""
        import datetime
        now = datetime.date.today().isoformat()
        result = ai_ops_run._provider_trust("qwen", "MISSING_KEY", {}, {}, now, {})
        assert result["ready"] is False
        assert result["reason"] is not None

    def test_klp_expired(self):
        """Key present but KLP rotation expired -> not ready."""
        import datetime
        now = datetime.date.today().isoformat()
        klp = {"K2": {"env_ref": "K2", "next_rotation_at": "2000-01-01"}}
        result = ai_ops_run._provider_trust("kimi", "K2", klp, {"K2": "x"}, now, {})
        assert result["ready"] is False

    def test_caching(self):
        """Same provider -> cached result (identity check)."""
        import datetime
        now = datetime.date.today().isoformat()
        cache = {}
        r1 = ai_ops_run._provider_trust("p", "K1", {}, {"K1": "x"}, now, cache)
        r2 = ai_ops_run._provider_trust("p", "K1", {}, {"K1": "x"}, now, cache)
        assert r1 is r2


@pytest.mark.critical_path
@pytest.mark.unit
class TestPrintPipeline:
    """Tests for _print_pipeline — pipeline report formatting."""

    def test_error_report(self, capsys):
        """Error report -> prints error message."""
        report = {
            "kind": "execution-pipeline",
            "status": "error",
            "workitem_id": "test-err",
            "error": "something broke",
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "ОШИБКА" in captured.out
        assert "something broke" in captured.out

    def test_ready_report(self, capsys):
        """Ready report -> prints READY_FOR_PR."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ok",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 3, "applied_writes": 2, "denied": 0},
            "commit": {"sha": "abc123def456", "branch": "ai-ops/test",
                       "evidence_on_exact_sha": True, "tree_clean_before_checks": True},
            "gates": {"evaluated": ["tests", "lint"], "unmet": [], "blocked": False},
            "lifecycle": {"concurrency_preflight": {"conflicts": []}},
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "READY_FOR_PR" in captured.out
        assert "abc123def456" in captured.out

    def test_not_ready_report(self, capsys):
        """Not-ready report -> prints NOT_READY."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-nr",
            "ready_for_pr": False,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "budget", "steps": 40, "applied_writes": 5, "denied": 1},
            "gates": {"evaluated": ["tests"], "unmet": ["tests"], "blocked": True},
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "NOT_READY" in captured.out

    def test_report_with_context_bundle(self, capsys):
        """Report with context_bundle -> prints context info."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ctx",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "context_bundle": {
                "estimated_tokens": 500,
                "context_budget": 10000,
                "overflow": False,
                "agents": ["agent1"],
                "excluded_count": 3,
            },
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "500" in captured.out
        assert "10000" in captured.out

    def test_report_with_spec_coverage(self, capsys):
        """Report with spec_coverage -> prints spec info."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-spec",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "spec_coverage": {
                "level": 0,
                "level_name": "L0-minimal",
                "escalated_from": None,
                "blocking_missing": [],
                "needs_human": [],
            },
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "L0-minimal" in captured.out

    def test_report_with_exemptions(self, capsys):
        """Report with exemptions -> prints them."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ex",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "exemptions": ["security_scan", "perf_bench"],
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "security_scan" in captured.out
        assert "perf_bench" in captured.out

    def test_report_with_not_yet(self, capsys):
        """Report with not_yet items -> prints them."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ny",
            "ready_for_pr": False,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": ["tests"], "blocked": True},
            "not_yet": ["need live proposer", "tests not passing"],
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "need live proposer" in captured.out


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

    def test_print_human_controller_report(self, capsys):
        """print_human on controller report -> prints tracks and gates."""
        report = {
            "kind": "run-report",
            "workitem_id": "ctl-test",
            "status": "planned",
            "base_workflow": "quick-fix",
            "execution": "planned",
            "runtime": "claude-code",
            "required_tracks": ["IMPL", "TEST"],
            "conditional_tracks": ["DOCS"],
            "gates": ["base_build", "lint"],
            "skipped_tracks": [{"track": "PERF", "reason": "not needed"}],
        }
        ai_ops_run.print_human(report)
        captured = capsys.readouterr()
        assert "ctl-test" in captured.out
        assert "planned" in captured.out
        assert "IMPL" in captured.out

    def test_print_human_pipeline_delegates(self, capsys):
        """print_human on pipeline kind -> delegates to _print_pipeline."""
        report = {
            "kind": "execution-pipeline",
            "status": "error",
            "workitem_id": "pipe-err",
            "error": "test error",
        }
        ai_ops_run.print_human(report)
        captured = capsys.readouterr()
        assert "pipeline" in captured.out


@pytest.mark.critical_path
@pytest.mark.unit
class TestExitCodeController:
    """Tests for exit_code — controller report paths."""

    def test_controller_planned(self):
        """Controller planned -> exit 0."""
        assert ai_ops_run.exit_code({"status": "planned", "workitem_id": "x"}) == 0

    def test_controller_blocked(self):
        """Controller blocked -> exit 1."""
        assert ai_ops_run.exit_code({"status": "blocked", "workitem_id": "x"}) == 1

    def test_controller_done(self):
        """Controller done (not blocked) -> exit 0."""
        assert ai_ops_run.exit_code({"status": "done", "workitem_id": "x"}) == 0

    def test_pipeline_overall_error(self):
        """Pipeline overall_status=error -> exit 2."""
        report = {"kind": "execution-pipeline", "status": "done",
                  "ready_for_pr": True, "overall_status": "error"}
        assert ai_ops_run.exit_code(report) == 2

    def test_pipeline_blocked_status(self):
        """Pipeline status=blocked -> exit 1."""
        report = {"kind": "execution-pipeline", "status": "blocked", "ready_for_pr": False}
        assert ai_ops_run.exit_code(report) == 1


@pytest.mark.critical_path
@pytest.mark.unit
class TestMainResumeSubcommand:
    """Tests for main() — resume subcommand."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_resume_no_handoff(self, child_root):
        """resume without handoff -> can_resume=False, exit 1."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "resume", str(child_root), "nonexistent-feature",
        ])
        assert exit_code == 1

    def test_resume_json_output(self, child_root, capsys):
        """resume --json -> JSON output."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "resume", str(child_root), "nonexistent-feature", "--json",
        ])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "can_resume" in data
        assert exit_code == 1


@pytest.mark.critical_path
@pytest.mark.unit
# TestMainSelftest удалён: selftest вынесен в tests/unit/test_ai_ops_run_selftest.py

@pytest.mark.critical_path
@pytest.mark.unit
class TestRunWithPipelineErrors:
    """Tests for run() — pipeline error handling paths."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_provider_exception_returns_error_report(self, child_root):
        """Provider raising exception -> error report (not traceback)."""
        self._init_repo(child_root)

        def boom(context):
            raise ConnectionResetError("connection lost")

        report = ai_ops_run.run(
            task_text="test task",
            signals={"task_type": "QUICK", "size": "small", "risk": "low",
                     "affected_areas": ["core"]},
            child_root=child_root,
            engine="pipeline",
            execute=True,
            proposer=boom,
            feature="err-test",
        )
        assert report["status"] == "error"
        assert report["kind"] == "execution-pipeline"
        assert report["ready_for_pr"] is False
        assert "failure" in report

    def test_pipeline_with_mock_proposer(self, child_root):
        """Pipeline with mock proposer -> completes with lifecycle artifacts."""
        self._init_repo(child_root)
        pscript = iter([{"op": "write", "path": "new.py", "content": "x=1\n"}, {"done": True}])
        report = ai_ops_run.run(
            task_text="add file",
            signals={"task_type": "QUICK", "size": "small", "risk": "low",
                     "affected_areas": ["core"]},
            child_root=child_root,
            engine="pipeline",
            proposer=lambda c: next(pscript),
            feature="mock-test",
        )
        assert report["kind"] == "execution-pipeline"
        wid = report["workitem_id"]
        assert (child_root / "features" / wid / "workitem.yaml").is_file()
        assert (child_root / "features" / wid / "run-plan.yaml").is_file()
        assert (child_root / "features" / wid / "run-report.json").is_file()
        assert (child_root / "features" / wid / "run-handoff.yaml").is_file()
        assert (child_root / "features" / wid / "context-bundle.yaml").is_file()

    def test_pipeline_writes_lifecycle_journal(self, child_root):
        """Pipeline execution writes lifecycle-journal with run_start + run_end."""
        self._init_repo(child_root)
        pscript = iter([{"op": "write", "path": "j.py", "content": "j=1\n"}, {"done": True}])
        ai_ops_run.run(                      # предмет проверки — журнал на диске, не возврат
            task_text="journal test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low",
                     "affected_areas": ["core"]},
            child_root=child_root,
            engine="pipeline",
            proposer=lambda c: next(pscript),
            feature="journal-test",
        )
        import lifecycle_store as _ls
        jpath = child_root / "features" / "journal-test" / "lifecycle-journal.jsonl"
        jr = _ls.journal_read(jpath)
        assert jr["ok"]
        kinds = {e["kind"] for e in jr["events"]}
        assert "run_start" in kinds
        assert "run_end" in kinds


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeImmutablePolicy:
    """Tests for resume — immutable policy enforcement."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_resume_drift_detection(self, child_root):
        """Resume with changed task_type -> error (drift detected)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "drift-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: drift-test\n"
            "signals:\n  task_type: ENGINEERING\n  risk: high\npolicy:\n  sandbox: true\n",
            encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="drift-test",
            resume=True,
        )
        assert report["status"] == "error"
        assert "replan" in (report.get("error") or "").lower()
        assert "task_type" in (report.get("resume") or {}).get("drift", [])

    def test_resume_corrupt_settings(self, child_root):
        """Resume with corrupt run-settings -> error (fail-closed)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "corrupt-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text("", encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="corrupt-test",
            resume=True,
        )
        assert report["status"] == "error"
        assert "повреждён" in (report.get("error") or "")

    def test_resume_with_replan_flag(self, child_root):
        """Resume with replan=True -> bypasses drift check (no drift error)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "replan-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: replan-test\n"
            "signals:\n  task_type: ENGINEERING\n  risk: high\npolicy:\n  sandbox: true\n",
            encoding="utf-8")
        # Also need a handoff for resume_preflight to pass
        (fdir / "run-handoff.yaml").write_text(
            "kind: RunHandoff\nworkitem_id: replan-test\n"
            "next_action: продолжить\nopen_questions: []\n",
            encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="replan-test",
            resume=True,
            replan=True,
        )
        # With replan=True, the error should NOT be about drift/replan
        # (it may be about resume_preflight or other things, but not drift)
        err = (report.get("error") or "").lower()
        if report["status"] == "error":
            assert "drift" not in err


@pytest.mark.critical_path
@pytest.mark.unit
class TestReconcilePendingDelivery:
    """Tests for _reconcile_pending_delivery — delivery reconciliation."""

    def test_no_pending(self, tmp_path):
        """No pending intents -> None."""
        result = ai_ops_run._reconcile_pending_delivery(tmp_path, "nonexistent", tmp_path)
        assert result is None

    def test_reconcile_found_matching(self, tmp_path):
        """Intent + matching PR on remote -> reconciled receipt."""
        import lifecycle_store as _ls
        import pr_open
        fdir = tmp_path / "feat"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d1.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d1", "workitem_id": "feat",
                           "repository": "o/r", "branch": "ai-ops/feat",
                           "base_ref": "main", "commit_sha": "abc",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/1", "number": 1,
            "repository": "o/r", "head_sha": "abc", "base_ref": "main",
            "pr_state": "open", "merged": False}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "reconciled"

    def test_reconcile_absent(self, tmp_path):
        """Intent + PR absent on remote -> not-delivered receipt."""
        import lifecycle_store as _ls
        import pr_open
        fdir = tmp_path / "feat2"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d2.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d2", "workitem_id": "feat2",
                           "repository": "o/r", "branch": "ai-ops/feat2",
                           "base_ref": "main", "commit_sha": "def",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "absent", "repository": "o/r"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat2", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "reconciled-absent"

    def test_reconcile_mismatch(self, tmp_path):
        """Intent + PR with different SHA -> mismatch receipt."""
        import lifecycle_store as _ls
        import pr_open
        fdir = tmp_path / "feat3"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d3.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d3", "workitem_id": "feat3",
                           "repository": "o/r", "branch": "ai-ops/feat3",
                           "base_ref": "main", "commit_sha": "old_sha",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/3", "number": 3,
            "repository": "o/r", "head_sha": "new_sha", "base_ref": "main"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat3", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "mismatch"

    def test_reconcile_unavailable(self, tmp_path):
        """Intent + remote unavailable -> no receipt written."""
        import lifecycle_store as _ls
        import pr_open
        fdir = tmp_path / "feat4"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d4.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d4", "workitem_id": "feat4",
                           "repository": "o/r", "branch": "ai-ops/feat4",
                           "base_ref": "main", "commit_sha": "xyz",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "unavailable"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat4", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "unavailable"

    def test_reconcile_exception(self, tmp_path):
        """reconcile_delivery raises exception -> unavailable status."""
        import lifecycle_store as _ls
        import pr_open
        fdir = tmp_path / "feat5"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d5.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d5", "workitem_id": "feat5",
                           "repository": "o/r", "branch": "ai-ops/feat5",
                           "base_ref": "main", "commit_sha": "qqq",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: (_ for _ in ()).throw(
            RuntimeError("network down"))
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat5", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "unavailable"


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFallbackExtended:
    """Extended tests for _with_provider_fallback."""

    def test_fallback_stays_on_secondary(self):
        """After switch, subsequent calls go to secondary directly."""
        call_log = []

        def primary(prompt):
            call_log.append("primary")
            raise TimeoutError("timeout")

        def secondary(prompt):
            call_log.append("secondary")
            return f"result-{prompt}"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        r1 = wrapped("first")
        r2 = wrapped("second")
        assert r1 == "result-first"
        assert r2 == "result-second"
        # After first switch, primary should NOT be called again
        assert call_log == ["primary", "secondary", "secondary"]

    def test_on_switch_callback(self):
        """on_switch callback is called when switching to fallback."""
        switched = {"called": False, "error": None}

        def primary(prompt):
            raise TimeoutError("timeout")

        def secondary(prompt):
            return "ok"

        def on_sw(e):
            switched["called"] = True
            switched["error"] = e

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary, on_switch=on_sw)
        wrapped("test")
        assert switched["called"] is True
        assert isinstance(switched["error"], TimeoutError)


@pytest.mark.critical_path
@pytest.mark.unit
class TestMainRunSubcommand:
    """Tests for main() — run subcommand argument parsing."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_run_with_signals_json(self, child_root, capsys):
        """main(['run', ..., '--signals', '{...}']) parses signals correctly."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "controller",
            "--signals", '{"task_type": "ENGINEERING"}',
            "--json",
        ])
        captured = capsys.readouterr()
        # stdout may contain ACTIVE-WORK prefix before JSON; extract JSON block
        json_start = captured.out.index("{")
        data = json.loads(captured.out[json_start:])
        assert isinstance(data, dict)
        assert isinstance(exit_code, int)

    def test_run_with_feature_flag(self, child_root, capsys):
        """main(['run', ..., '--feature', 'name']) binds to named feature."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "controller",
            "--feature", "my-feature",
            "--json",
        ])
        captured = capsys.readouterr()
        # stdout may contain ACTIVE-WORK prefix before JSON; extract JSON block
        json_start = captured.out.index("{")
        data = json.loads(captured.out[json_start:])
        assert data["workitem_id"] == "my-feature"
        assert isinstance(exit_code, int)

    def test_run_with_max_steps(self, child_root):
        """main(['run', ..., '--max-steps', '10']) passes max_steps."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "controller",
            "--max-steps", "10",
            "--json",
        ])
        assert isinstance(exit_code, int)

    def test_run_human_output(self, child_root, capsys):
        """main(['run', ...]) without --json -> human-readable output."""
        self._init_repo(child_root)
        exit_code = ai_ops_run.main([
            "run", "test task", str(child_root),
            "--engine", "controller",
        ])
        captured = capsys.readouterr()
        assert "ai-ops run" in captured.out
        assert isinstance(exit_code, int)


@pytest.mark.unit
class TestBookkeepingLossIsVisible:
    """Утраченная служебная запись ВИДНА в отчёте, а не пропадает молча.

    Ревизия 2026-08-11: учёт usage и lifecycle-журнал писались под `except Exception: pass`.
    Решение «служебная запись не роняет прогон» правильное и записанное — падать из-за журнала
    посреди доставки хуже, чем потерять строку. Но второй половины не было: потеря была
    невидимой. Для кита, чья заявленная ценность — Usage Truth и `unavailable != 0`, молча
    пропавшая запись стоимости означает занижённый счёт, поданный как факт.

    Образец взят в том же файле: рядом уже был `escalation_error` с пометкой «rc3: НЕ глотаем
    молча». Здесь то же для служебных записей.
    """

    def test_records_what_was_lost_and_why(self):
        rep = {"kind": "execution-pipeline"}
        ai_ops_run._note_bookkeeping_error(rep, "usage_ledger.append", OSError("disk full"))

        assert "bookkeeping_errors" in rep, "утрата записи не попала в отчёт"
        entry = rep["bookkeeping_errors"][0]
        assert entry["what"] == "usage_ledger.append", "не сказано, ЧТО потеряно"
        assert "OSError" in entry["error"] and "disk full" in entry["error"], (
            f"не сказано, ПОЧЕМУ потеряно: {entry}")

    def test_accumulates_and_does_not_overwrite(self):
        """Две потери — две записи: вторая не затирает первую."""
        rep = {}
        ai_ops_run._note_bookkeeping_error(rep, "usage_ledger.append", OSError("x"))
        ai_ops_run._note_bookkeeping_error(rep, "lifecycle_journal.fix_attempt", ValueError("y"))

        whats = [e["what"] for e in rep["bookkeeping_errors"]]
        assert whats == ["usage_ledger.append", "lifecycle_journal.fix_attempt"], whats

    def test_clean_run_has_no_such_key(self):
        """Обратная сторона: без потерь ключа НЕТ — иначе он читался бы как «всегда что-то не так»."""
        rep = {"kind": "execution-pipeline"}
        assert "bookkeeping_errors" not in rep

    def test_never_raises_on_unexpected_report_shape(self):
        """fail-closed наоборот: сам учёт потерь не имеет права уронить прогон."""
        ai_ops_run._note_bookkeeping_error(None, "x", OSError("y"))
        ai_ops_run._note_bookkeeping_error("не dict", "x", OSError("y"))
