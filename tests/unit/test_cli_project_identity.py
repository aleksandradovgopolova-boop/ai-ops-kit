"""Фасад передаёт runtime/сессию, а не подменяет Codex дефолтом Claude."""
from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engine import ai_ops_run


def test_run_forwards_explicit_runtime_and_full_session(tmp_path, monkeypatch):
    seen = {}

    def capture(task, signals, root, **kwargs):
        seen.update(kwargs)
        return {"kind": "execution-pipeline", "ready_for_pr": False}

    monkeypatch.setattr(ai_ops_run, "run", capture)
    monkeypatch.setattr(ai_ops_run, "print_human", lambda report: None)
    ai_ops_cli.main(["run", "task", str(tmp_path), "--execute", "--provider", "mock",
                     "--runtime", "codex", "--session", "full-independent-session-123456",
                     "--signals", '{"task_type":"QUICK","size":"small","risk":"low"}'])
    assert seen["runtime"] == "codex"
    assert seen["session"] == "full-independent-session-123456"
