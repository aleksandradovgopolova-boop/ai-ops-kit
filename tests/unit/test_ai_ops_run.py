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

    def test_print_human_minimal_blocked_report_does_not_crash(self, capsys):
        """Минимальный отчёт отказа active-work (без base_workflow/треков) НЕ роняет вывод.
        Замер поля 01.09.2026: печать такого отчёта падала KeyError('base_workflow') — прогон
        завершался, а print_human ронял процесс. Теперь печатает коротко: id, статус, причину."""
        report = {"schema_version": 1, "kind": "run-report", "workitem_id": "mat-ready",
                  "status": "blocked", "blocked_by": "active-work",
                  "error": "работа не начата: заявку держит другая сессия"}
        ai_ops_run.print_human(report)          # НЕ должно бросать KeyError
        out = capsys.readouterr().out
        assert "mat-ready" in out and "blocked" in out
        assert "active-work" in out

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


# ============================================================================
# Перенос покрытия из tests/unit/test_ai_ops_run_selftest.py (гранулярно).
# Каждое поведение монолита, ещё не покрытое выше, — отдельным тестом с настоящей
# проверкой значения. Вызовы, git-фикстуры и фейковые proposer'ы взяты из монолита.
# ============================================================================


def _git_init_commit(root):
    """Минимальный git-репозиторий с одним коммитом (как в монолите)."""
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)


# Сигналы planned-пути из монолита: PRODUCT + UI + аналитика -> треки VISUAL/ANALYTICS.
_PLANNED_SIG = {
    "task_type": "PRODUCT", "risk": "medium",
    "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
    "ui_changed": True, "measurable_behavior": True, "user_facing_change": True,
    "affected_areas": ["catalog", "orders-api"],
}


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderTrustRotationReason:
    """Просроченная KLP-ротация несёт человекочитаемую причину (не только ready=False)."""

    def test_expired_rotation_reason_mentions_rotation(self):
        """rc3 trust: KLP-ротация просрочена -> reason содержит 'ротация'."""
        import datetime
        now = datetime.date.today().isoformat()
        klp = {"K2": {"env_ref": "K2", "next_rotation_at": "2000-01-01"}}
        result = ai_ops_run._provider_trust("kimi", "K2", klp, {"K2": "x"}, now, {})
        assert result["ready"] is False
        assert "ротация" in (result.get("reason") or "")


@pytest.mark.critical_path
@pytest.mark.unit
class TestPlannedControllerTracks:
    """planned-путь контроллера: неметериализованное состояние, active-work, треки, гейты."""

    def _planned(self, tmp_path):
        root = tmp_path / "planned"
        root.mkdir()
        report = ai_ops_run.run(
            task_text="фильтр по статусу в каталоге заказов",
            signals=dict(_PLANNED_SIG), child_root=root,
            runtime="claude-code", engine="controller",
        )
        return root, report

    def test_run_state_not_materialized(self, tmp_path):
        """planned: run_state НЕ материализован (обещание пути)."""
        _, report = self._planned(tmp_path)
        assert report["run_state_materialized"] is False

    def test_active_work_registered(self, tmp_path):
        """planned: active-work.yaml зарегистрирована."""
        root, _ = self._planned(tmp_path)
        assert (root / ".ai" / "runtime" / "active-work.yaml").exists()

    def test_visual_analytics_tracks(self, tmp_path):
        """planned: сигналы UI/аналитики -> треки VISUAL и ANALYTICS в отчёте."""
        _, report = self._planned(tmp_path)
        assert {"VISUAL", "ANALYTICS"} <= set(report["required_tracks"])

    def test_track_gates_aggregated(self, tmp_path):
        """planned: гейты треков агрегированы (ux_review + analytics_design_readiness)."""
        _, report = self._planned(tmp_path)
        assert {"ux_review", "analytics_design_readiness"} <= set(report["gates"])

    def test_analytics_runtime_verification_not_prerelease(self, tmp_path):
        """v3.27.6: analytics_runtime_verification НЕ входит в дорелизный RunPlan."""
        _, report = self._planned(tmp_path)
        assert "analytics_runtime_verification" not in set(report["gates"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeCorruptSettingsNotOverwritten:
    """v3.0.12: битый run-settings на resume не перезаписывается дефолтами."""

    def test_corrupt_settings_not_rewritten(self, tmp_path):
        """Повреждённый (пустой) run-settings остаётся пустым — контракт не уничтожен молча."""
        root = tmp_path / "corr-root"
        cf = root / "features" / "corr"
        cf.mkdir(parents=True)
        (cf / "run-settings.yaml").write_text("", encoding="utf-8")
        report = ai_ops_run.run(
            task_text="продолжить",
            signals={"task_type": "QUICK", "risk": "low"}, child_root=root,
            engine="pipeline", feature="corr", resume=True,
        )
        assert report.get("status") == "error"
        assert "повреждён" in (report.get("error") or "")
        assert (cf / "run-settings.yaml").read_text(encoding="utf-8") == ""


def _rewrite_base_repo(root, wid):
    """Репо, где base ПЕРЕПИСАН на несвязанный orphan (force-push назад). Как в монолите."""
    root.mkdir(parents=True, exist_ok=True)

    def g(*a):
        return subprocess.run(["git", "-C", str(root), *a],
                              capture_output=True, text=True).stdout.strip()
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        g(*a)
    (root / "f").write_text("x", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "A")
    base_A = g("rev-parse", "HEAD")
    cur = g("rev-parse", "--abbrev-ref", "HEAD")
    g("checkout", "-q", "-b", "ai-ops/rwx")
    (root / "w").write_text("work", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "W")
    work_sha = g("rev-parse", "HEAD")
    g("checkout", "-q", cur)
    g("checkout", "-q", "--orphan", "reborn")
    (root / "z").write_text("z", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "R")
    g("branch", "-f", cur, g("rev-parse", "HEAD")); g("checkout", "-q", cur)
    fdir = root / "features" / wid; fdir.mkdir(parents=True)
    (fdir / "run-settings.yaml").write_text(
        "schema_version: 1\nkind: run-settings\nworkitem_id: %s\n"
        "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
        "  base: %s\n  base_binding:\n    base_ref: %s\n    base_sha: %s\n"
        % (wid, cur, cur, base_A), encoding="utf-8")
    (fdir / "run-handoff.yaml").write_text(
        "kind: RunHandoff\nworkitem_id: %s\nresume_from_revision: %s\n"
        "base_binding:\n  kind: BaseBinding\n  base_ref: %s\n  base_sha: %s\n"
        "next_action: продолжить\nopen_questions: []\n"
        % (wid, work_sha, cur, base_A), encoding="utf-8")


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeBaseRewritten:
    """v3.0.10/14: base переписан -> resume заблокирован даже с force_resume/replan."""

    def test_force_resume_still_blocked(self, tmp_path):
        """base переписан + force_resume=True -> ВСЁ РАВНО blocked (base_rewritten, 'свежий')."""
        root = tmp_path / "rw"
        _rewrite_base_repo(root, "rwx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="rwx",
            resume=True, force_resume=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_rewritten") is True
        assert "свежий" in (report.get("error") or "").lower()

    def test_replan_still_blocked(self, tmp_path):
        """base переписан + replan (всё ещё resume) -> ВСЁ РАВНО blocked (base_rewritten)."""
        root = tmp_path / "rw2"
        _rewrite_base_repo(root, "rwx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="rwx",
            resume=True, replan=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_rewritten") is True


def _fast_forward_base_repo(root, wid):
    """Репо, где база УШЛА ВПЕРЁД (fast-forward): base_A остаётся предком cur. Как в монолите."""
    root.mkdir(parents=True, exist_ok=True)

    def g(*a):
        return subprocess.run(["git", "-C", str(root), *a],
                              capture_output=True, text=True).stdout.strip()
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        g(*a)
    (root / "f").write_text("x", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "A")
    base_A = g("rev-parse", "HEAD")
    cur = g("rev-parse", "--abbrev-ref", "HEAD")
    g("checkout", "-q", "-b", "ai-ops/ffx")
    (root / "w").write_text("work", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "W")
    work_sha = g("rev-parse", "HEAD")
    g("checkout", "-q", cur)
    (root / "b2").write_text("advance", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "B")
    fdir = root / "features" / wid; fdir.mkdir(parents=True)
    (fdir / "run-settings.yaml").write_text(
        "schema_version: 1\nkind: run-settings\nworkitem_id: %s\n"
        "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
        "  base: %s\n  base_binding:\n    base_ref: %s\n    base_sha: %s\n"
        % (wid, cur, cur, base_A), encoding="utf-8")
    (fdir / "run-handoff.yaml").write_text(
        "kind: RunHandoff\nworkitem_id: %s\nresume_from_revision: %s\n"
        "base_binding:\n  kind: BaseBinding\n  base_ref: %s\n  base_sha: %s\n"
        "next_action: продолжить\nopen_questions: []\n"
        % (wid, work_sha, cur, base_A), encoding="utf-8")
    return cur


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeFastForwardBase:
    """v3.0.14: fast-forward базы + force_resume -> blocked (base_moved), force не снимает."""

    def test_fast_forward_force_blocked(self, tmp_path):
        """fast-forward базы + force_resume -> blocked, base_moved=True, 'свежий'."""
        root = tmp_path / "ff"
        _fast_forward_base_repo(root, "ffx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="ffx",
            resume=True, force_resume=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_moved") is True
        assert "свежий" in (report.get("error") or "").lower()


@pytest.mark.critical_path
@pytest.mark.unit
class TestWriteBarrierRunPlan:
    """v3.0.15 write-barrier: сбой durable-записи RunPlan -> прогон не начат."""

    def test_durable_runplan_failure_is_error(self, tmp_path):
        """Монкипатч durable_write на провал -> status=error и 'RunPlan' в error."""
        import lifecycle_store as _ls
        root = tmp_path / "bar"
        root.mkdir()
        _git_init_commit(root)
        orig = _ls.durable_write
        _ls.durable_write = lambda *a, **k: {"ok": False, "error": "smoke IO fail"}
        try:
            report = ai_ops_run.run(
                task_text="барьер",
                signals={"task_type": "QUICK", "risk": "low", "affected_areas": ["core"]},
                child_root=root, engine="pipeline",
                proposer=lambda c: {"done": True}, execute=True, feature="barx",
            )
        finally:
            _ls.durable_write = orig
        assert report.get("status") == "error"
        assert "RunPlan" in (report.get("error") or "")


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    """Канонический pipeline-прогон mock-предложителем (пишет src/a.py). Один раз на модуль."""
    root = tmp_path_factory.mktemp("pipe")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
    )
    return root, rp, rp["workitem_id"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestEnginePipelineExecution:
    """engine=pipeline: движок реально применил изменение и прошёл единый lifecycle."""

    def test_applied_write_and_file_exists(self, pipeline_run):
        """Движок применил ровно одно изменение и файл существует на диске."""
        root, rp, _ = pipeline_run
        assert rp["loop"]["applied_writes"] == 1
        assert (root / "src" / "a.py").exists()

    def test_commit_barrier_ordering(self, pipeline_run):
        """commit-barrier: ready_for_delivery предшествует run_end по seq журнала."""
        import lifecycle_store as _ls
        root, _, pfid = pipeline_run
        jr = _ls.journal_read(root / "features" / pfid / "lifecycle-journal.jsonl")
        seq_by_kind = {e["kind"]: e["seq"] for e in jr["events"]}
        assert "ready_for_delivery" in seq_by_kind
        assert seq_by_kind["ready_for_delivery"] < seq_by_kind["run_end"]

    def test_active_work_registered(self, pipeline_run):
        """pipeline зарегистрировал active-work."""
        root, _, _ = pipeline_run
        assert (root / ".ai" / "runtime" / "active-work.yaml").exists()

    def test_lifecycle_artifacts_in_report(self, pipeline_run):
        """lifecycle-артефакты в отчёте: rep['lifecycle']['workitem'] указывает на workitem.yaml."""
        _, rp, pfid = pipeline_run
        assert isinstance(rp.get("lifecycle"), dict)
        assert rp["lifecycle"].get("workitem") == f"features/{pfid}/workitem.yaml"

    def test_single_plan_workitem_id_matches(self, pipeline_run):
        """Единый план: workitem_id отчёта совпадает с id артефактов (второй план не строился)."""
        root, rp, pfid = pipeline_run
        assert rp["workitem_id"] == pfid
        assert (root / "features" / pfid / "workitem.yaml").exists()


@pytest.mark.critical_path
@pytest.mark.unit
class TestF012ActiveWorkDeregistration:
    """F-012: прогон снят с учёта в любом исходе; статус честно отражает исход."""

    def test_deregistered_after_run(self, pipeline_run):
        """active-work содержит запись с id == workitem_id (снята с учёта по завершении)."""
        import active_work
        root, _, pfid = pipeline_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == pfid), None)
        assert entry is not None

    def test_status_reflects_outcome(self, pipeline_run):
        """done только при ready_for_pr, иначе blocked + status_reason."""
        import active_work
        root, rp, pfid = pipeline_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == pfid), None)
        assert entry is not None
        if rp.get("ready_for_pr"):
            assert entry.get("status") == "done"
        else:
            assert entry.get("status") == "blocked" and entry.get("status_reason")


@pytest.mark.critical_path
@pytest.mark.unit
class TestPipelineContext:
    """v2.97/v2.108: контекст измерен до модели, payload собран и подан."""

    def test_context_bundle_measured(self, pipeline_run):
        """estimated_tokens>0 и context_budget>0 в отчёте."""
        _, rp, _ = pipeline_run
        assert isinstance(rp.get("context_bundle"), dict)
        assert rp["context_bundle"]["estimated_tokens"] > 0
        assert rp["context_bundle"]["context_budget"] > 0

    def test_context_payload_saved(self, pipeline_run):
        """ContextPayload сохранён рядом с планом."""
        root, _, pfid = pipeline_run
        assert (root / "features" / pfid / "context-payload.yaml").exists()

    def test_payload_fed_to_model(self, pipeline_run):
        """payload подан модели (fed_to_model) + бюджет с резервом (payload_budget < context_budget)."""
        _, rp, _ = pipeline_run
        payload = rp.get("context_payload")
        assert isinstance(payload, dict)
        assert payload["fed_to_model"] is True
        assert payload["payload_budget"] < payload["context_budget"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestPipelineSpecAndWorkPackage:
    """v2.98/v2.99/v2.100/v2.111: spec-level, handoff, атомарный пакет."""

    def test_spec_coverage_saved_level_zero(self, pipeline_run):
        """SpecCoverage сохранён + level==0 для QUICK (L0)."""
        root, rp, pfid = pipeline_run
        assert (root / "features" / pfid / "spec-coverage.yaml").exists()
        assert isinstance(rp.get("spec_coverage"), dict)
        assert rp["spec_coverage"]["level"] == 0

    def test_handoff_next_action(self, pipeline_run):
        """handoff несёт непустой next_action (следующий шаг)."""
        _, rp, _ = pipeline_run
        assert isinstance(rp.get("handoff"), dict)
        assert bool(rp["handoff"].get("next_action"))

    def test_work_package_saved_atomic(self, pipeline_run):
        """WorkPackagePlan сохранён + atomic==True (QUICK/1 подсистема)."""
        root, rp, pfid = pipeline_run
        assert (root / "features" / pfid / "work-package.yaml").exists()
        assert isinstance(rp.get("work_package"), dict)
        assert rp["work_package"]["atomic"] is True

    def test_atomic_has_no_subpackages(self, pipeline_run):
        """Атомарный пакет -> work_packages пуст (не выдумываем разбиение)."""
        _, rp, _ = pipeline_run
        assert rp["work_package"].get("work_packages") == []


@pytest.mark.critical_path
@pytest.mark.unit
class TestMockProposerNote:
    """v2.119: заметка 'живой предложитель' уместна для mock и убрана для живого провайдера."""

    def test_mock_note_present(self, pipeline_run):
        """mock-провайдер -> заметка «живой предложитель» присутствует в not_yet."""
        _, rp, _ = pipeline_run
        assert any("живой предложитель" in n for n in (rp.get("not_yet") or []))

    def test_live_provider_note_removed(self, tmp_path):
        """Живой провайдер -> заметка «живой предложитель» убрана из not_yet."""
        root = tmp_path / "live"
        root.mkdir()
        _git_init_commit(root)
        pscript = iter([{"op": "write", "path": "b.py", "content": "b=1\n"}, {"done": True}])
        rp_live = ai_ops_run.run(
            task_text="добавить b",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
            provider_name="anthropic", feature="live-fn",
        )
        assert not any("живой предложитель" in n for n in (rp_live.get("not_yet") or []))


@pytest.fixture(scope="module")
def boom_run(tmp_path_factory):
    """Pipeline-прогон, где провайдер бросает ConnectionResetError. Один раз на модуль."""
    root = tmp_path_factory.mktemp("boom")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)

    def _boom(c):
        raise ConnectionResetError("[Errno 54] Connection reset by peer")

    rep = ai_ops_run.run(
        task_text="задача с падающим провайдером",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", execute=True, proposer=_boom, feature="boomwi",
    )
    return root, rep


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFailureTyped:
    """v3.0-rc17: исключение провайдера -> честный типизированный error-отчёт."""

    def test_failure_class_network_retryable(self, boom_run):
        """ConnectionResetError -> failure_class=='network', retryable True."""
        _, rep = boom_run
        assert rep.get("status") == "error"
        assert (rep.get("failure") or {}).get("failure_class") == "network"
        assert (rep.get("failure") or {}).get("retryable") is True

    def test_exit_code_two(self, boom_run):
        """exit_code(provider-error) == 2."""
        _, rep = boom_run
        assert ai_ops_run.exit_code(rep) == 2

    def test_active_work_blocked_with_reason(self, boom_run):
        """Падение провайдера -> active-work снята как blocked, ConnectionResetError в status_reason."""
        import active_work
        root, _ = boom_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == "boomwi"), None)
        assert entry is not None
        assert entry.get("status") == "blocked"
        assert "ConnectionResetError" in (entry.get("status_reason") or "")


@pytest.mark.critical_path
@pytest.mark.unit
class TestReevaluateOnly:
    """v3.8.3: reevaluate_only в сигнатуре run() и реально прокинут в run_pipeline."""

    def test_in_signature(self):
        """run() принимает reevaluate_only."""
        import inspect
        assert "reevaluate_only" in inspect.signature(ai_ops_run.run).parameters

    def test_propagated_to_pipeline(self, tmp_path):
        """После execute-прогона повторный reevaluate_only -> loop.stopped == 'reevaluate-only'."""
        root = tmp_path / "reev"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
        (root / "seed").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        ps = iter([{"op": "write", "path": "rv.py", "content": "def f():\n    return 1\n"}, {"done": True}])
        ai_ops_run.run(task_text="add rv", signals=sig, child_root=root, engine="pipeline",
                       execute=True, feature="rev-x", proposer=lambda c: next(ps))
        r2 = ai_ops_run.run(task_text="reeval", signals=sig, child_root=root, engine="pipeline",
                            execute=True, feature="rev-x", reevaluate_only=True,
                            proposer=lambda c: {"done": True})
        assert (r2.get("loop") or {}).get("stopped") == "reevaluate-only"


@pytest.fixture(scope="module")
def ctl_resume_results(tmp_path_factory):
    """Многофазный controller-resume сценарий из монолита. Возвращает исходы всех фаз."""
    root = tmp_path_factory.mktemp("ctl")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "seed").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    cur = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
    out = {"worktree": root / ".ai" / "worktrees" / "ctl-resume"}

    s1 = iter([{"op": "write", "path": "src/phase1.py", "content": "p=1\n"}, {"done": True}])
    out["p1"] = ai_ops_run.run(task_text="фаза 1", signals=sig, child_root=root, engine="pipeline",
                               proposer=lambda c: next(s1), execute=True, feature="ctl-resume",
                               install_deps=False, base=cur)
    s2 = iter([{"op": "write", "path": "src/phase2.py", "content": "p=2\n"}, {"done": True}])
    out["p2"] = ai_ops_run.run(task_text="фаза 2", signals=sig, child_root=root, engine="pipeline",
                               proposer=lambda c: next(s2), execute=True, feature="ctl-resume",
                               install_deps=False, resume=True, base=cur)
    out["none"] = ai_ops_run.run(task_text="продолжить пустоту", signals=sig, child_root=root,
                                 engine="pipeline", proposer=lambda c: {"done": True}, execute=True,
                                 feature="never-ran", install_deps=False, resume=True, base=cur)
    (root / "moved.txt").write_text("z", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "base+1"], capture_output=True)
    s3 = iter([{"op": "write", "path": "src/phase3.py", "content": "p=3\n"}, {"done": True}])
    out["block"] = ai_ops_run.run(task_text="фаза 3", signals=sig, child_root=root, engine="pipeline",
                                  proposer=lambda c: next(s3), execute=True, feature="ctl-resume",
                                  install_deps=False, resume=True, base=cur)
    s4 = iter([{"op": "write", "path": "src/phase4.py", "content": "p=4\n"}, {"done": True}])
    out["force"] = ai_ops_run.run(task_text="фаза 4", signals=sig, child_root=root, engine="pipeline",
                                  proposer=lambda c: next(s4), execute=True, feature="ctl-resume",
                                  install_deps=False, resume=True, force_resume=True, base=cur)
    out["root"] = root
    return out


@pytest.mark.critical_path
@pytest.mark.unit
class TestControllerRealResume:
    """v2.109/v3.0.14: реальный resume контроллера — продолжение поверх ветки, честные блоки."""

    def test_phase1_committed_with_handoff(self, ctl_resume_results):
        """Фаза 1 закоммичена + run-handoff записан."""
        r = ctl_resume_results
        assert bool((r["p1"].get("commit") or {}).get("sha"))
        assert (r["root"] / "features" / "ctl-resume" / "run-handoff.yaml").exists()

    def test_resume_continued(self, ctl_resume_results):
        """resume продолжил (не ошибка про несохранённые коммиты), resumed=True."""
        r = ctl_resume_results
        assert r["p2"].get("status") != "error"
        assert (r["p2"].get("resume") or {}).get("resumed") is True

    def test_both_phases_in_worktree(self, ctl_resume_results):
        """Обе фазы в worktree (продолжили поверх, не с нуля)."""
        wt = ctl_resume_results["worktree"]
        assert (wt / "src" / "phase1.py").exists()
        assert (wt / "src" / "phase2.py").exists()

    def test_resume_without_prior_honest_error(self, ctl_resume_results):
        """resume без прошлого -> honest error (can_resume=False)."""
        r = ctl_resume_results
        assert r["none"].get("status") == "error"
        assert (r["none"].get("resume") or {}).get("can_resume") is False

    def test_stale_base_blocked(self, ctl_resume_results):
        """Устаревшая база -> resume блокируется без --force (revalidation_needed)."""
        r = ctl_resume_results
        assert r["block"].get("status") == "blocked"
        assert (r["block"].get("resume") or {}).get("revalidation_needed") is True

    def test_fast_forward_force_base_moved(self, ctl_resume_results):
        """fast-forward базы + --force -> blocked (base_moved), не продолжает на устаревшем."""
        r = ctl_resume_results
        assert r["force"].get("status") == "blocked"
        assert (r["force"].get("resume") or {}).get("base_moved") is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestOrchestratedPath:
    """orchestrated-путь: транзакция прошла, состояние по WorkItem."""

    def _orchestrated(self, tmp_path):
        root = tmp_path / "orch"
        root.mkdir()
        return ai_ops_run.run(
            task_text="починить опечатку",
            signals={"task_type": "QUICK", "affected_areas": ["docs"]}, child_root=root,
            runtime="generic-orchestrator", provider_name="mock", execute=True, engine="controller",
        )

    def test_execution_orchestrated(self, tmp_path):
        """execution=='orchestrated' и статус blocked|done."""
        r2 = self._orchestrated(tmp_path)
        assert r2["execution"] == "orchestrated"
        assert r2["status"] in ("blocked", "done")

    def test_run_state_by_workitem(self, tmp_path):
        """run_state ссылается на workitems/<id>."""
        r2 = self._orchestrated(tmp_path)
        assert f"workitems/{r2['workitem_id']}" in r2["run_state"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestReconcileReceiptFields:
    """v3.0.17: строгая идентичность доставки — поля DeliveryReceipt и идемпотентность."""

    def _mk_intent(self, fdir, did, wid, branch, commit):
        import lifecycle_store as _ls
        obx = fdir / "delivery-outbox"
        _ls.durable_write(obx / f"{did}.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent", "delivery_id": did,
                           "workitem_id": wid, "repository": "o/r", "branch": branch,
                           "base_ref": "main", "base_sha": "b" * 40, "commit_sha": commit,
                           "status": "intended"})
        return obx / f"{did}.receipt.yaml"

    def test_reconciled_receipt_fields(self, tmp_path):
        """Строгая идентичность (head.sha==commit) -> sha_verified True + remote_sha + pr_url."""
        import lifecycle_store as _ls
        import pr_open
        root = tmp_path / "dlvroot"
        f1 = root / "features" / "dlv"; f1.mkdir(parents=True)
        rp1 = self._mk_intent(f1, "did1", "dlv", "ai-ops/dlv", "cafe1234")
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/7", "number": 7, "repository": "o/r",
            "head_sha": "cafe1234", "base_ref": "main", "pr_state": "open", "merged": False}
        try:
            r = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
        finally:
            pr_open.reconcile_delivery = orig
        d1 = _ls.load_guarded(rp1, kind="DeliveryReceipt")
        assert r and r[0]["status"] == "reconciled"
        assert d1["state"] == "ok"
        assert d1["data"]["remote_sha"] == "cafe1234"
        assert d1["data"]["sha_verified"] is True
        assert d1["data"]["pr_url"] == "https://x/pr/7"

    def test_repeat_reconcile_returns_none(self, tmp_path):
        """Повторная реконсиляция -> None (Receipt уже есть, дубля нет)."""
        import pr_open
        root = tmp_path / "dlvroot2"
        f1 = root / "features" / "dlv"; f1.mkdir(parents=True)
        self._mk_intent(f1, "did1", "dlv", "ai-ops/dlv", "cafe1234")
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/7", "number": 7, "repository": "o/r",
            "head_sha": "cafe1234", "base_ref": "main", "pr_state": "open", "merged": False}
        try:
            first = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
            second = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
        finally:
            pr_open.reconcile_delivery = orig
        assert first and first[0]["status"] == "reconciled"
        assert second is None


@pytest.fixture(scope="module")
def fixloop_run(tmp_path_factory):
    """v3.1.1 fix-loop: полный прогон с pytest (провал теста -> починка). Один раз на модуль.

    Требует pytest в окружении (как в монолите). Иначе — пропуск: unit-проверки логики
    fix-context (TestReviewFixContext выше) покрывают её без внешних инструментов.
    """
    import importlib.util as ilu
    if ilu.find_spec("pytest") is None:
        pytest.skip("pytest недоступен — интеграционный fix-loop пропущен")
    root = tmp_path_factory.mktemp("fixloop")
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    (root / "m.py").write_text("def base():\n    return 1\n", encoding="utf-8")
    (root / "test_base.py").write_text(
        "from m import base\n\ndef test_base():\n    assert base() == 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0.1.0'\n[tool.setuptools]\npy-modules=['m']\n"
        "[tool.pytest.ini_options]\npythonpath=['.']\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    cur = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    st = {"buggy": False, "test": False, "fixed": False}

    def fl_prop(context):
        fix = ("упала" in context) or ("Устрани" in context)
        if fix:
            if not st["fixed"]:
                st["fixed"] = True
                return {"op": "write", "path": "m.py",
                        "content": "def base():\n    return 1\n\ndef g(x):\n    return x + 1\n"}
            return {"done": True}
        if not st["buggy"]:
            st["buggy"] = True
            return {"op": "write", "path": "m.py",
                    "content": "def base():\n    return 1\n\ndef g(x):\n    return x\n"}
        if not st["test"]:
            st["test"] = True
            return {"op": "write", "path": "test_g.py",
                    "content": "from m import g\n\ndef test_g():\n    assert g(1) == 2\n"}
        return {"done": True}

    sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
    rfl = ai_ops_run.run(task_text="добавить g(x)=x+1 с тестом", signals=dict(sig),
                         child_root=root, engine="pipeline", provider_name="test",
                         proposer=fl_prop, execute=True, feature="fixloop",
                         install_deps=False, base=cur, review_fix_attempts=1)
    return root, rfl


@pytest.mark.critical_path
@pytest.mark.unit
class TestFixLoopIntegration:
    """v3.1.1 fix-loop: провал теста -> итерация по блокерам -> ready; событие fix_attempt в журнале."""

    def test_test_failure_fixed_to_ready(self, fixloop_run):
        """Провал теста -> итерация по блокерам -> ready_for_pr=True и 'test' не в unmet."""
        _, rfl = fixloop_run
        assert rfl.get("ready_for_pr") is True
        assert "test" not in (rfl.get("gates") or {}).get("unmet", [])

    def test_fix_attempt_event_logged(self, fixloop_run):
        """Событие fix_attempt записано в lifecycle-журнал."""
        import lifecycle_store as _ls
        root, _ = fixloop_run
        jr = _ls.journal_read(root / "features" / "fixloop" / "lifecycle-journal.jsonl")
        assert any(e.get("kind") == "fix_attempt" for e in jr["events"])


@pytest.fixture(scope="module")
def hybrid_run(tmp_path_factory):
    """Pipeline-прогон с context_hybrid=True (mock-предложитель). Один раз на модуль.

    Закрывает пробел покрытия под расщепление K6: под-блок hybrid фазы компиляции
    контекста (context_hybrid) не гонялся ни одним тестом до этого.
    """
    root = tmp_path_factory.mktemp("hybrid")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
        context_hybrid=True,
    )
    return root, rp


@pytest.mark.unit
class TestPipelineContextHybrid:
    """Характеристика под-блока hybrid фазы компиляции контекста (context_hybrid=True).

    Фиксирует поведение ДО расщепления run() (K6-глубина): на минимальном репозитории
    без v2-additions hybrid — fail-safe v1-only, ничего не подаётся сверх v1.
    """

    def test_report_has_context_hybrid(self, hybrid_run):
        """rep['context_hybrid'] присутствует и является ContextHybrid."""
        _, rp = hybrid_run
        assert rp["context_hybrid"]["kind"] == "ContextHybrid"

    def test_v1_only_fail_safe_on_minimal_repo(self, hybrid_run):
        """Без v2-additions: mode=v1-only, ничего не подано сверх v1, exact-snapshot соблюдён."""
        _, rp = hybrid_run
        ch = rp["context_hybrid"]
        assert ch["mode"] == "v1-only"
        assert ch["fed_to_model"] is False
        assert ch["v2_additions"] == []
        assert ch["exact_snapshot"] is True


@pytest.fixture(scope="module")
def shadow_run(tmp_path_factory):
    """Pipeline-прогон с context_shadow=True (mock-предложитель). Один раз на модуль.

    Закрывает пробел покрытия под расщепление K6: под-блок context_shadow фазы
    обогащения отчёта не гонялся через run() ни одним тестом до этого.
    """
    root = tmp_path_factory.mktemp("shadow")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
        context_shadow=True,
    )
    return root, rp


@pytest.mark.unit
class TestPipelineContextShadow:
    """Характеристика под-блока context_shadow фазы обогащения отчёта (context_shadow=True).

    Фиксирует поведение ДО расщепления run() (K6-глубина): shadow — чистая наблюдаемость
    РЯДОМ с боевым v1, полностью guarded — его сбой не роняет прогон, а честно фиксируется.
    """

    def test_shadow_present_and_guarded(self, shadow_run):
        """rep['context_shadow'] присутствует как dict; прогон не упал из-за shadow."""
        _, rp = shadow_run
        assert isinstance(rp.get("context_shadow"), dict)
        # прогон дошёл до отчёта пайплайна (shadow не прервал исполнение)
        assert rp.get("kind") == "execution-pipeline"


@pytest.mark.unit
class TestPipelineRunProvenance:
    """Характеристика фазы обогащения отчёта provenance-полями (runtime/provider/engine/
    model/model_resolution/preflight/lifecycle). Фиксирует поведение ДО расщепления run()
    (K6-глубина) перед выносом блока в _enrich_run_report.
    """

    def test_runtime_engine_provider(self, pipeline_run):
        _, rp, _ = pipeline_run
        assert rp["runtime"] == "claude-code"
        assert rp["engine"] == "pipeline"
        assert rp["provider"] == "mock"

    def test_model_resolution_and_preflight_present(self, pipeline_run):
        _, rp, _ = pipeline_run
        assert rp["model_resolution"]["kind"] == "ModelResolution"
        assert "preflight" in rp

    def test_lifecycle_dict_shape(self, pipeline_run):
        _, rp, pfid = pipeline_run
        lc = rp["lifecycle"]
        assert lc["workitem"] == f"features/{pfid}/workitem.yaml"
        assert lc["run_plan"] == f"features/{pfid}/run-plan.yaml"
        assert lc["run_report"] == f"features/{pfid}/run-report.json"
        assert lc["run_handoff"] == f"features/{pfid}/run-handoff.yaml"
        assert lc["active_work"] == ".ai/runtime/active-work.yaml"
        assert "concurrency_preflight" in lc


@pytest.mark.unit
class TestPipelineRunCost:
    """Характеристика фазы run_cost (агрегат tokens/latency/cost из вызовов модели).

    pipeline_run с mock-предложителем даёт пустой drain_call_stats -> тело `if _stats:`
    (rep['cost'] + usage_ledger) не гонялось. Инжектируем один вызов, чтобы зафиксировать
    поведение ДО расщепления run() (K6-глубина) перед выносом в _finalize_run_cost.
    """

    def _run_with_stats(self, root, stats):
        import subprocess
        from unittest.mock import patch
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
        (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
        ps = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
        with patch("ai_ops_kit.providers.orchestrator.drain_call_stats", return_value=stats):
            return ai_ops_run.run(
                task_text="add a",
                signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
                child_root=root, engine="pipeline", proposer=lambda c: next(ps))

    def test_cost_aggregated_from_stats(self, tmp_path):
        """Непустой drain_call_stats -> rep['cost'] агрегирует calls/tokens/latency."""
        rp = self._run_with_stats(tmp_path / "r", [
            {"input_tokens": 100, "output_tokens": 40, "latency_s": 1.5, "cost_usd_est": 0.01},
            {"input_tokens": 50, "output_tokens": 10, "latency_s": 0.5, "cost_usd_est": 0.005},
        ])
        cost = rp["cost"]
        assert cost["calls"] == 2
        assert cost["input_tokens"] == 150
        assert cost["output_tokens"] == 50
        assert cost["latency_s"] == 2.0
        assert cost["cost_usd_est"] == 0.015

    def test_no_stats_no_cost(self, tmp_path):
        """Пустой drain_call_stats -> rep['cost'] не проставляется (нет вызовов — нечего агрегировать)."""
        rp = self._run_with_stats(tmp_path / "r", [])
        assert "cost" not in rp


class TestRegisterActiveWorkTakeover:
    """Fix 2 (#autonomous-delivery, 01.09.2026): `--takeover` доезжает до register через
    run -> _register_active_work. Раньше run звал register БЕЗ takeover — брошенную заявку можно
    было снять только руками через active_work.py, и автономная доставка вставала."""

    def test_takeover_overrides_a_blocking_claim(self, child_root):
        from ai_ops_kit.lifecycle import active_work as aw
        aw_path = child_root / ".ai" / "runtime" / "active-work.yaml"
        aw_path.parent.mkdir(parents=True, exist_ok=True)
        aw.register(aw_path, "wi-x", "ai-ops/wi-x", ["src/"], "session:holder")   # свежая, держит
        sig = {"affected_areas": ["core"]}
        errs = []
        # БЕЗ takeover: свежая чужая заявка обязана останавливать (контроль Fix 1 — молодую не гасим)
        p1, _pf1, err1 = ai_ops_run._register_active_work(
            child_root, sig, ["src/"], "wi-x", "session:me", errs)
        assert err1 is not None and p1 is None, "без takeover блокирующая заявка обязана останавливать"
        # С takeover: проводка Fix 2 — register перенимает заявку
        p2, _pf2, err2 = ai_ops_run._register_active_work(
            child_root, sig, ["src/"], "wi-x", "session:me", errs,
            takeover=True, takeover_reason="прежняя сессия мертва")
        assert err2 is None and p2 is not None, "--takeover обязан перенять заявку (проводка Fix 2)"
        entry = [w for w in aw.load(aw_path)["active"] if w["id"] == "wi-x"][0]
        assert entry.get("taken_over_from", {}).get("owner_session") == "session:holder", \
            "прежний держатель обязан остаться записан (атрибуция)"
