"""Native delegation intake: synthetic Git/FS/process fixtures, no live models."""
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session import project as fixture_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    return fixture_project.__wrapped__(tmp_path, monkeypatch)


def state(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in (root / ".ai/runtime/sessions").rglob("*") if p.is_file()}


def capture(monkeypatch, project, payload, *extra):
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))
    return cli.main(["intake", "--runtime", "codex", "--session", "native", *extra])


def test_native_intake_persists_exact_declared_input_without_execution(project, monkeypatch):
    prompt = "Исследуй отмену; $(touch forbidden); `exit`\nОдна попытка."
    assert capture(monkeypatch, project, json.dumps({"prompt": prompt}).encode()) == 1
    task = sessions.load(project, "codex", "native")
    assert task["prompt"] == prompt and task["status"] == "pending"
    assert task["turn_id"] is None
    assert task["input_origin"] == {
        "kind": "current-agent-intake", "identity_scope": "declared", "hook_event_name": None}
    assert task["binding"] == sessions.binding(project, "session-" + task["request_id"])
    assert "execution" not in task and "verification" not in task
    assert not list(project.rglob("*.execution-claim"))
    assert not list(project.rglob("process.*.log"))
    assert not (project / "features").exists() and not (project / "forbidden").exists()


def test_same_initial_intake_is_read_only_replay(project):
    first = cli.initial_intake(project, "codex", "native", "Одна задача")
    before = state(project)
    assert cli.initial_intake(project, "codex", "native", "Одна задача") == first
    assert state(project) == before
    assert len(list(sessions.session_dir(project, "codex", "native").glob("*.json"))) == 2


def test_intake_then_real_controller_preserves_existing_handoff(project, monkeypatch):
    task = cli.initial_intake(project, "codex", "native", "Проверь документ")
    monkeypatch.chdir(project)
    assert cli.main(["run", "--runtime", "codex", "--session", "native", "--signals",
                     '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    prepared = sessions.load(project, "codex", "native")
    assert prepared["execution"]["mode"] == "current-session"
    assert prepared["execution"]["prepared"] is True
    feature = project / "features" / ("session-" + task["request_id"])
    assert (feature / "workitem.yaml").is_file() and (feature / "run-plan.yaml").is_file()
    assert json.loads((feature / "run-report.json").read_text())["status"] == "planned"
    before = state(project)
    assert cli.initial_intake(project, "codex", "native", task["prompt"]) == prepared
    assert state(project) == before and prepared["status"] != "accepted"


@pytest.mark.parametrize("kind", ["hook", "changed", "accepted", "unknown"])
def test_initial_intake_never_overwrites_other_or_unknown_work(project, kind):
    task = (sessions.begin(project, "codex", "native", "original", "actual-hook-turn")
            if kind == "hook" else cli.initial_intake(project, "codex", "native", "original"))
    directory = sessions.session_dir(project, "codex", "native")
    if kind == "unknown":
        claim = directory / (task["request_id"] + ".execution-claim")
        claim.write_bytes(b"unknown actual execution marker")
        assert claim.read_bytes() == b"unknown actual execution marker"
    if kind == "accepted":
        task["status"] = "accepted"
        sessions.write(directory / (task["request_id"] + ".json"), task)
    before = state(project)
    with pytest.raises(ValueError):
        cli.initial_intake(project, "codex", "native", "different" if kind == "changed" else "original")
    assert state(project) == before
    assert not list(project.rglob("process.*.log"))


def test_binding_change_refuses_same_intake_without_new_request(project):
    cli.initial_intake(project, "codex", "native", "original")
    sessions.git(project, "commit", "--allow-empty", "-qm", "real head changed")
    before = state(project)
    with pytest.raises(ValueError, match="проект изменился"):
        cli.initial_intake(project, "codex", "native", "original")
    assert state(project) == before


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"null", b"not JSON",
    b'{"prompt":""}', b'{"prompt":5}', b'{"prompt":"ok","approved":true}',
    json.dumps({"prompt": "x" * 131073}).encode(), b" " * 262145])
def test_invalid_intake_never_creates_a_request(project, monkeypatch, payload):
    assert capture(monkeypatch, project, payload) == 2
    assert not list((project / ".ai/runtime/sessions").glob("project-*/*.json"))
    assert not (project / "features").exists()


@pytest.mark.parametrize("flags", [["--autonomous"], ["--signals", "{}"], ["--review-digests", "{}"]])
def test_capture_cannot_execute_or_provide_approval(project, monkeypatch, flags):
    assert capture(monkeypatch, project, b'{"prompt":"original"}', *flags) == 2
    assert not list((project / ".ai/runtime/sessions").glob("project-*/*.json"))


def test_session_start_exposes_real_identity_and_fallback_without_capturing(project):
    result = cli.hook("codex", {"cwd": str(project), "session_id": "real-session",
                                "hook_event_name": "SessionStart"})
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "session_id=real-session" in context and "project_session intake" in context
    assert "declared" in context and "не hook evidence" in context
    assert not list((project / ".ai/runtime/sessions").glob("project-*/*.json"))


def test_other_runtime_does_not_gain_unqualified_intake(project):
    with pytest.raises(ValueError, match="только.*Codex"):
        cli.initial_intake(project, "claude-code", "native", "original")
    assert not list((project / ".ai/runtime/sessions").glob("project-*/*.json"))


def test_stock_installed_intake_uses_delivered_code_without_model(installed_copy):
    from installer import team_setup
    config_path = installed_copy / ".ai-ops.yaml"
    config = yaml.safe_load(config_path.read_text())
    config.setdefault("standard", {})["team_session"] = "required"
    config_path.write_text(yaml.safe_dump(config))
    team_setup.ensure_team_session(installed_copy)  # synthetic project only, no native trust
    process = subprocess.run([sys.executable, "-P", "-m", "ai_ops_kit.cli.project_session",
                              "intake", "--runtime", "codex", "--session", "installed"],
        cwd=installed_copy, input='{"prompt":"Исследуй отмену задачи"}', capture_output=True,
        text=True, timeout=15, env=dict(os.environ, PYTHONPATH=str(installed_copy / ".ai/managed")))
    assert process.returncode == 1, process.stderr
    task = json.loads(process.stdout)
    assert task["status"] == "pending" and task["input_origin"]["identity_scope"] == "declared"
    assert task["binding"]["root"] == str(installed_copy.resolve())
    directory = sessions.session_dir(installed_copy, "codex", "installed")
    assert json.loads((directory / (task["request_id"] + ".json")).read_text())["prompt"] == "Исследуй отмену задачи"
    assert not list(directory.glob("*.execution-claim")) and not (installed_copy / "features").exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_real_blocking_stdin_finishes_without_task_or_owned_worker(project, cancel):
    code = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r}); "
            "from ai_ops_kit.cli import project_session as cli; "
            "cli.sessions.HOOK_READ_SECONDS=0.7; "
            "print('ready',flush=True); "
            "raise SystemExit(cli.main(['intake','--runtime','codex','--session','blocked']))")
    process = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=project,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        started = time.monotonic()
        # Открытый stdin без EOF: действительно блокирующее OS-чтение.
        time.sleep(0.15)
        assert process.poll() is None
        if cancel:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=4)
        assert time.monotonic() - started < 3
        assert process.returncode != 0
        assert not list((project / ".ai/runtime/sessions").glob("project-*/*.json"))
        assert not list(project.rglob("*.execution-claim"))
        with sessions.session_lock(sessions.session_dir(project, "codex", "blocked") / "requests"):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("read_kind", ["active", "verification"])
def test_replay_blocked_state_read_is_bounded_and_preserves_task(project, tmp_path, monkeypatch, cancel, read_kind):
    task = cli.initial_intake(project, "codex", "native", "original")
    directory = sessions.session_dir(project, "codex", "native")
    target, method = directory / "active.json", "read_text"
    if read_kind == "verification":
        monkeypatch.chdir(project)
        assert cli.main(["run", "--runtime", "codex", "--session", "native", "--signals",
                         '{"task_type":"quick","size":"small","risk":"low"}']) == 1
        task = sessions.load(project, "codex", "native")
        target, method = directory / "verification.json", "read_bytes"
        sessions.write(target, {})  # synthetic finished report; block before parsing it
        task["verification"] = {"phase": "finished", "report": str(target.relative_to(project))}
        sessions.write(directory / (task["request_id"] + ".json"), task)
    before = state(project)
    fifo, marker = tmp_path / "fifo", tmp_path / "entered"
    os.mkfifo(fifo)
    code = f"""
import os, sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from pathlib import Path
from ai_ops_kit.cli import project_session as cli
actual = Path.{method}
def read(path, *args, **kwargs):
    if path == Path({str(target)!r}):
        Path({str(marker)!r}).write_text('entered')
        fd = os.open({str(fifo)!r}, os.O_RDWR)
        os.read(fd, 1)
    return actual(path, *args, **kwargs)
Path.{method} = read
cli.sessions.HOOK_READ_SECONDS = 0.7
raise SystemExit(cli.main(['intake','--runtime','codex','--session','native']))
"""
    process = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=project,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        process.stdin.write('{"prompt":"original"}')
        process.stdin.close()
        process.stdin = None
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.read_text() == "entered" and process.poll() is None
        started = time.monotonic()
        if cancel:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=3)
        assert time.monotonic() - started < 2
        assert process.returncode != 0 and state(project) == before
        assert sessions.load(project, "codex", "native") == task
        with sessions.session_lock(directory / "requests"):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)
