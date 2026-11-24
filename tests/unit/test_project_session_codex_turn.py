"""Process-shaped Codex events from the rejected-turn incident, without a model."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_resume as resume
from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session_completion import project as _project_fixture, start


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def rollout(tmp_path, project, monkeypatch):
    home = tmp_path.resolve() / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    path = home / "sessions/2026/11/24/rollout-2026-11-24T14-26-42-complete.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        ("session_meta", {"id": "complete", "cwd": str(project.resolve())}),
        ("event_msg", {"type": "task_started", "turn_id": "first"}),
        ("response_item", {"type": "message", "role": "user"}),
        ("event_msg", {"type": "user_message"}),
        ("event_msg", {"type": "task_complete", "turn_id": "first", "last_agent_message": None,
                       "error": {"message": json.dumps({"status": 400, "error": {"code": "model_not_found"}})}}),
        ("event_msg", {"type": "task_started", "turn_id": "next"}),
    ]
    def write():
        path.write_text("".join(json.dumps({"type": k, "payload": v}) + "\n" for k, v in rows))
    write()
    return {"hook_event_name": "UserPromptSubmit", "session_id": "complete", "cwd": str(project),
            "prompt": "Исследуй", "turn_id": "next", "transcript_path": str(path)}, rows, write


def test_retry_keeps_request_and_records_new_turn_once(project, rollout):
    (project / ".gitignore").write_text(".ai/runtime/\n")
    sessions.git(project, "add", ".gitignore")
    sessions.git(project, "commit", "-qm", "runtime ignored")
    payload, _, _ = rollout
    task = sessions.begin(project, "codex", "complete", payload["prompt"], "first")
    a = cli.hook("codex", payload)
    saved = sessions.load(project, "codex", "complete")
    assert saved["request_id"] == task["request_id"] and saved["turn_id"] == "first"
    assert len(saved["input_events"]) == 1 and "execution" not in saved
    path = project / saved["input_events"][0]
    assert json.loads(path.read_bytes())["turn_id"] == "next"
    before = path.stat().st_mtime_ns
    assert cli.hook("codex", payload) == a and path.stat().st_mtime_ns == before
    assert not list(path.parent.parent.glob("*.execution-claim"))
    different = dict(payload, turn_id="later", prompt="Другая задача")
    cli.hook("codex", different)
    assert sessions.load(project, "codex", "complete")["request_id"] != task["request_id"]


def test_long_session_reads_recent_complete_turn_and_rejects_late_delivery(project, rollout):
    payload, rows, write = rollout
    rows.insert(1, ("response_item", {"type": "reasoning", "pad": "x" * (3 * 1024 * 1024)}))
    write()
    assert resume.rejected_turn(project, payload) == "first"
    rows.append(("event_msg", {"type": "task_started", "turn_id": "newer"}))
    write()
    assert resume.rejected_turn(project, payload) is None


@pytest.mark.parametrize("damage", ["claim", "stale-report", "orphan-plan", "orphan-openspec", "binding"])
def test_even_confirmed_model_rejection_needs_pristine_kit_state(project, rollout, damage):
    payload, _, _ = rollout
    if damage == "orphan-openspec":
        (project / ".gitignore").write_text("openspec/\n.ai/runtime/\n")
        sessions.git(project, "add", ".gitignore")
        sessions.git(project, "commit", "-qm", "ignored artifacts")
    task = sessions.begin(project, "codex", "complete", payload["prompt"], "first")
    directory = sessions.session_dir(project, "codex", "complete")
    if damage == "claim":
        (directory / (task["request_id"] + ".execution-claim")).touch()
    elif damage == "orphan-openspec":
        proposal = project / "openspec/changes" / ("session-" + task["request_id"]) / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("Earlier preparation")
        assert sessions.git(project, "check-ignore", "--", str(proposal.relative_to(project)))
    elif damage == "orphan-plan":
        (project / ".ai/runplan" / ("session-" + task["request_id"])).mkdir(parents=True)
    elif damage == "stale-report":
        report = project / ("features/session-" + task["request_id"]) / "run-report.json"
        report.parent.mkdir(parents=True)
        report.write_text("{}")
    else:
        (project / ".ai/managed/VERSION").write_text("other version")
    with pytest.raises(ValueError):
        cli.hook("codex", payload)
    assert sessions.load(project, "codex", "complete") == task
    assert not list(directory.glob("*.inputs"))


@pytest.mark.parametrize("damage", ["tool", "other-session", "other-root", "other-error", "assistant",
                                     "intervening", "missing-start", "late-failure", "outside", "symlink", "fifo", "partial", "oversize"])
def test_unproven_provider_failure_never_associates_turns(project, rollout, tmp_path, damage):
    payload, rows, write = rollout
    path = Path(payload["transcript_path"])
    if damage == "tool":
        rows.insert(3, ("response_item", {"type": "function_call"}))
    elif damage == "other-session":
        rows[0][1]["id"] = "different"
    elif damage == "other-root":
        rows[0][1]["cwd"] = str(tmp_path)
    elif damage == "other-error":
        rows[-2][1]["error"] = {"message": json.dumps({"status": 429})}
    elif damage == "assistant":
        rows[-2][1]["last_agent_message"] = "an answer"
    elif damage == "missing-start":
        rows.pop()
    elif damage == "late-failure":
        rows[-2], rows[-1] = rows[-1], rows[-2]
    elif damage == "intervening":
        rows.insert(-1, ("event_msg", {"type": "task_started", "turn_id": "other"}))
    write()
    if damage in ("outside", "symlink"):
        moved = path.rename(tmp_path / "outside")
        if damage == "symlink":
            path.symlink_to(moved)
        else:
            payload["transcript_path"] = str(moved)
    if damage == "fifo":
        path.unlink()
        os.mkfifo(path)
    if damage == "partial":
        path.write_bytes(path.read_bytes()[:-1])
    if damage == "oversize":
        path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    assert resume.rejected_turn(project, payload) is None


def test_stop_persists_missing_finalize_then_normal_verification_can_finish(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    path = sessions.session_dir(project, "codex", "complete") / (task["request_id"] + ".execution-claim")
    before = path.read_bytes(), path.stat().st_mtime_ns
    from ai_ops_kit.cli.project_session_completion import response
    transition = response(project, task)["host_actions"]["after_plan"]
    assert transition["required_before_final_answer"] and transition["argv"][4:] == ["finalize", *args]
    dirty = project / "pending-result.txt"
    dirty.write_text("unfinished local result")
    stop = {"hook_event_name": "Stop", "session_id": "complete", "cwd": str(project), "turn_id": "turn-one"}
    assert cli.hook("codex", dict(stop, turn_id="previous"))["continue"] is False
    assert sessions.load(project, "codex", "complete") == task
    r = cli.hook("codex", stop)
    stopped = sessions.load(project, "codex", "complete")
    assert stopped["status"] == "blocked" and "чистый" in stopped["blocker"]
    assert r["continue"] is False and "verification" not in stopped
    assert not (project / ".ai/runtime/check-ran").exists()
    assert cli.hook("codex", stop) == r
    assert cli.main(["run", *args]) == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    dirty.unlink()
    # Launch the advertised command as a new process from the child. A local
    # namesake must not shadow the exact installation which issued the handoff.
    shadow = project / "ai_ops_kit.py"
    shadow.write_text("raise RuntimeError('shadow package')\n")
    sessions.git(project, "add", "ai_ops_kit.py")
    sessions.git(project, "commit", "-qm", "child module with kit name")
    proc = subprocess.run(transition["argv"], cwd=project, env=dict(os.environ, PYTHONPATH=transition["pythonpath"]),
                          text=True, capture_output=True, timeout=35)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert sessions.verify(project, "codex", "complete")["accepted"]
    assert cli.hook("codex", stop) == {}
