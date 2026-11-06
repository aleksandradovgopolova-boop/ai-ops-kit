"""Настоящие FIFO/syscall и hooks; без моделей, replay и продуктовой установки."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_completion as completion
from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.shared import gitio
from test_project_session import project as _project_fixture
from test_project_session_resume_bounds import state, assert_unlocked
from test_project_session_completion import start

KIT = str(Path(sessions.__file__).resolve().parents[2])
SESSION = "bounded-resume"


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def prepared(project, monkeypatch):
    (project / ".ai/managed/blocked.data").write_text("regular file\n")
    sessions.begin(project, "codex", SESSION, "Проверь документ", "original")
    monkeypatch.chdir(project)
    assert cli.main(["run", "--runtime", "codex", "--session", SESSION,
                     "--signals", '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    return sessions.load(project, "codex", SESSION)


def payload(root, event, *, session=SESSION):
    return {"cwd": str(root), "session_id": session, "hook_event_name": event,
            "prompt": "Продолжи ту же задачу", "turn_id": "next-turn"}


def launch(root, tmp_path, request, target=None, *, journal=False, seconds=0.4, extra=""):
    fifo, marker = tmp_path / "blocked-fifo", tmp_path / "entered-read"
    os.mkfifo(fifo)
    code = f"""
import os, sys, json
from pathlib import Path
from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.lifecycle import project_session as sessions
sessions.HOOK_READ_SECONDS = {seconds!r}
def blocked():
    Path({str(marker)!r}).write_text(str(os.getpid()))
    fd = os.open({str(fifo)!r}, os.O_RDWR)
    try:
        os.read(fd, 1)
    finally:
        os.close(fd)
target = {str(target) if target is not None else None!r}
if {journal!r}:
    original = sessions.session_migration_store.document
    def document(path, **kwargs):
        if str(path) == target:
            blocked()
        return original(path, **kwargs)
    sessions.session_migration_store.document = document
elif target:
    original = Path.open
    def opening(path, *args, **kwargs):
        if str(path) == target:
            blocked()
        return original(path, *args, **kwargs)
    Path.open = opening
{extra}
raise SystemExit(cli.main(['hook', '--runtime', 'codex']))
"""
    process = subprocess.Popen([sys.executable, "-P", "-c", code], cwd=root,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True, env=dict(os.environ, PYTHONPATH=KIT))
    if request is not None:
        process.stdin.write(json.dumps(request))
        process.stdin.close()
        process.stdin = None
    return process, marker


def stopped(process):
    try:
        process.wait(timeout=4)
        stdout, stderr = process.communicate(timeout=1)
        assert process.returncode == 0, stderr
        answer = json.loads(stdout)
        assert answer["continue"] is False and "hook" in answer["stopReason"]
        return answer
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=2)


def test_real_stdin_pipe_times_out_before_external_hook_limit(project, tmp_path):
    before = state(project)
    process, _ = launch(project, tmp_path, None)
    started = time.monotonic()
    answer = stopped(process)  # stdin остаётся открытым: EOF не подставляется
    assert "бюджет" in answer["stopReason"]
    assert time.monotonic() - started < 4
    assert state(project) == before
    assert sessions.HOOK_READ_SECONDS == 10
    assert sessions.hook_group("codex")["hooks"][0]["timeout"] == 15


@pytest.mark.parametrize("kind", ["binding", "artifact", "journal", "fresh"])
def test_blocked_hook_read_preserves_state_and_claim_and_releases_locks(project, prepared, tmp_path, kind):
    event = "UserPromptSubmit" if kind in ("artifact", "fresh") else "SessionStart"
    target = project / (next(iter(prepared["execution"]["files"])) if kind == "artifact"
                        else ".ai/managed/blocked.data")
    if kind == "journal":
        target = project / sessions.session_migration_store.AREA / "prior" / "journal.json"
        target.parent.mkdir()
        target.write_text('{"phase":"committed"}')
    request = payload(project, event, session="fresh-session" if kind == "fresh" else SESSION)
    before = state(project)
    assert target.is_file()  # regular → реальный блокирующий syscall, не пропущенный is_file FIFO
    process, marker = launch(project, tmp_path, request, target, journal=kind == "journal")
    stopped(process)
    assert marker.is_file(), "не доказан вход в OS read"
    assert state(project) == before
    assert state(project, "fresh-session") == {}
    assert_unlocked(project)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_cancel_during_actual_read_preserves_claim_and_unlocks(project, prepared, tmp_path, sig):
    before = state(project)
    process, marker = launch(project, tmp_path, payload(project, "UserPromptSubmit"),
        project / next(iter(prepared["execution"]["files"])), seconds=10)
    try:
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        process.send_signal(sig)
        stopped(process)
        assert state(project) == before
        assert_unlocked(project)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=2)


def test_read_deadline_is_shared_and_never_restarted_between_phases(monkeypatch):
    monkeypatch.setattr(sessions, "HOOK_READ_SECONDS", 0.08)
    with sessions.hook_read_budget():
        with sessions.reading():
            time.sleep(0.05)
        with pytest.raises(sessions.HookReadInterrupted, match="бюджет"):
            with sessions.reading():
                time.sleep(0.05)
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_read_timer_and_cancel_handler_are_disarmed_before_mutation(project, monkeypatch):
    actual, writes = sessions.write, []
    alarm, term = signal.getsignal(signal.SIGALRM), signal.getsignal(signal.SIGTERM)
    def write(path, data):
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
        assert signal.getsignal(signal.SIGALRM) == alarm
        assert signal.getsignal(signal.SIGTERM) == term
        writes.append(path)
        return actual(path, data)
    monkeypatch.setattr(sessions, "write", write)
    with sessions.hook_read_budget():
        result = cli.hook("codex", payload(project, "UserPromptSubmit"))
    assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert len(writes) == 2 and sessions.load(project, "codex", SESSION)["status"] == "pending"
    assert_unlocked(project)


def test_expired_read_budget_does_not_interrupt_started_write_or_read_after_it(project, monkeypatch):
    actual, committed = sessions.write, []
    monkeypatch.setattr(sessions, "HOOK_READ_SECONDS", 0.5)
    def write(path, data):
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
        result = actual(path, data)
        if not committed:
            time.sleep(0.6)  # истечение бюджета в durable-фазе не является read timeout
        committed.append(path)
        return result
    monkeypatch.setattr(sessions, "write", write)
    with sessions.hook_read_budget():
        result = cli.hook("codex", payload(project, "UserPromptSubmit"))
    assert len(committed) == 2
    assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert sessions.load(project, "codex", SESSION)["status"] == "pending"


def finished(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    actual = sessions.run_process
    def interrupted(*a, **kw):
        actual(*a, **kw)
        raise subprocess.TimeoutExpired(a[0], 300)
    monkeypatch.setattr(sessions, "run_process", interrupted)
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, "codex", "complete")
    assert saved["verification"]["phase"] == "finished" and saved["status"] != "accepted"
    return saved


def test_stop_read_timeout_never_persists_unverified_acceptance(project, monkeypatch, tmp_path):
    task = finished(project, monkeypatch)
    before = state(project, "complete")
    process, marker = launch(project, tmp_path, payload(project, "Stop", session="complete"),
                             project / task["verification"]["report"])
    stopped(process)
    assert marker.exists() and state(project, "complete") == before
    assert_unlocked(project, "complete")


def test_stop_rejects_input_modified_between_reconciliation_and_commit(project, monkeypatch):
    finished(project, monkeypatch)
    before = state(project, "complete")
    actual = completion._reconcile
    def changed(*args, **kwargs):
        candidate = actual(*args, **kwargs)
        assert candidate["status"] == "accepted"
        (project / "result.py").write_text("VALUE = 99\n")
        assert (project / "result.py").read_text() == "VALUE = 99\n"
        return candidate
    monkeypatch.setattr(completion, "_reconcile", changed)
    with sessions.hook_read_budget():
        verdict = cli.hook("codex", payload(project, "Stop", session="complete"))
    assert verdict["continue"] is False
    assert state(project, "complete") == before
    assert_unlocked(project, "complete")


def test_stop_disarms_deadline_before_persisting_verified_candidate(project, monkeypatch):
    task = finished(project, monkeypatch)
    actual, commits = sessions.write, []
    term = signal.getsignal(signal.SIGTERM)
    def write(path, data):
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
        assert signal.getsignal(signal.SIGTERM) == term
        assert data["status"] == "accepted"
        commits.append(path)
        return actual(path, data)
    monkeypatch.setattr(sessions, "write", write)
    with sessions.hook_read_budget():
        assert cli.hook("codex", payload(project, "Stop", session="complete")) == {}
    assert len(commits) == 1
    assert sessions.load(project, "codex", "complete")["request_id"] == task["request_id"]
    assert sessions.verify(project, "codex", "complete")["accepted"]


@pytest.mark.parametrize("sig", [None, signal.SIGINT, signal.SIGTERM])
def test_git_read_timeout_or_cancel_kills_owned_process_group(project, tmp_path, sig):
    pids = tmp_path / "git-pids.json"
    child = "import time; time.sleep(60)"
    helper = ("import os, subprocess, sys, time, json; from pathlib import Path; "
              f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
              f"Path({str(pids)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)")
    extra = f"""
actual = sessions.subprocess.Popen
def spawn(command, **kwargs):
    assert command[0] == 'git'
    return actual([sys.executable, '-c', {helper!r}], **kwargs)
sessions.subprocess.Popen = spawn
"""
    before = state(project)
    process, _ = launch(project, tmp_path, payload(project, "SessionStart"),
                         seconds=0.5 if sig is None else 10, extra=extra)
    try:
        deadline = time.monotonic() + 4
        while not pids.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pids.exists(), "Git и потомок действительно должны запуститься"
        if sig is not None:
            process.send_signal(sig)
        stopped(process)
        parent, child = json.loads(pids.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(parent, 0)  # непосредственный ребёнок учтён, не zombie
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True)
        assert not status.stdout.strip() or status.stdout.strip().startswith("Z")
        assert state(project) == before
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=2)
        if pids.exists():
            try:
                os.killpg(json.loads(pids.read_text())[0], signal.SIGKILL)
            except ProcessLookupError:
                pass  # наша группа уже завершилась штатным cleanup


def test_git_group_helper_preserves_raw_output_and_return_code(project):
    content = "  leading whitespace\ntrailing whitespace  \n\n"
    (project / "raw.txt").write_text(content)
    sessions.git(project, "add", "raw.txt")
    sessions.git(project, "commit", "-qm", "raw bytes fixture")
    result = gitio.raw_group(["-C", str(project), "show", "HEAD:raw.txt"], timeout=2)
    assert result.returncode == 0 and result.stdout == content and result.stderr == ""
    failed = gitio.raw_group(["-C", str(project), "show", "HEAD:missing-file"], timeout=2)
    assert failed.returncode != 0 and failed.stderr


def test_git_group_helper_enforces_its_own_timeout_without_hook_budget(tmp_path, monkeypatch):
    marker = tmp_path / "git-started"
    actual = gitio.subprocess.Popen
    script = ("import os,time; from pathlib import Path; "
              f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)")
    def spawn(command, **kwargs):
        return actual([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(gitio.subprocess, "Popen", spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        gitio.raw_group(["status"], cwd=tmp_path, timeout=0.4)
    assert marker.is_file()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
