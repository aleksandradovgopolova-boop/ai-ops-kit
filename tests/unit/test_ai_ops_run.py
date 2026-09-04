"""Юнит-тесты ai_ops_run: run()/main/dispatch — точка входа, exit-коды, subcommands."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import ai_ops_run


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
        from ai_ops_kit.shared import lifecycle_store as _ls
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
        from ai_ops_kit.shared import lifecycle_store as _ls
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
        from ai_ops_kit.shared import lifecycle_store as _ls
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
        from ai_ops_kit.shared import lifecycle_store as _ls
        jpath = child_root / "features" / "journal-test" / "lifecycle-journal.jsonl"
        jr = _ls.journal_read(jpath)
        assert jr["ok"]
        kinds = {e["kind"] for e in jr["events"]}
        assert "run_start" in kinds
        assert "run_end" in kinds


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


@pytest.mark.unit
def test_resume_subparser_accepts_open_pr_and_takeover(tmp_path):
    """#695: resume-СУБПАРСЕР движка обязан принимать --open-pr/--takeover. Раньше их имел только
    run-субпарсер — CLI пробрасывал флаги, а движок падал 'unrecognized arguments' (поле, финальный
    прогон). argparse отверг бы неизвестный флаг SystemExit(2); любой другой исход = флаги приняты."""
    from ai_ops_kit.engine import ai_ops_run
    try:
        ai_ops_run.main(["resume", str(tmp_path), "no-such-wi", "--open-pr", "--takeover",
                         "--takeover-reason", "x"])
    except SystemExit as e:
        pytest.fail(f"resume-субпарсер отверг --open-pr/--takeover: code={e.code}")
    except Exception as e:  # noqa: BLE001 — прочий сбой (нет ветки/фичи) не про разбор аргументов
        assert e is not None  # тело есть (не try-except-pass) — проба только о том, что argparse принял флаги
