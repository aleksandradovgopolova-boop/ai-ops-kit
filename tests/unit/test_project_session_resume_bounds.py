"""Реальные read-only workers и блокирующий OS read; без toast, моделей и live runtime."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_resume as resume
from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session import project as _project_fixture

PYTHON = sys.executable
KIT = str(Path(sessions.__file__).resolve().parents[2])


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def prepared(project, monkeypatch):
    (project / ".ai/managed/blocked.data").write_text("ordinary regular file\n")
    task = sessions.begin(project, "codex", "bounded-resume", "Проверь документ", "original-turn")
    monkeypatch.chdir(project)
    assert cli.main(["run", "--runtime", "codex", "--session", "bounded-resume",
                     "--signals", '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    task = sessions.load(project, "codex", "bounded-resume")
    assert task["execution"]["prepared"] and task["status"] == "running"
    return task


def state(root, session="bounded-resume"):
    directory = sessions.session_dir(root, "codex", session)
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*") if p.is_file() and p.suffix != ".lock"}


def assert_unlocked(root, session="bounded-resume"):
    directory = sessions.session_dir(root, "codex", session)
    with sessions.session_migration_store.barrier(root, exclusive=True):
        with sessions.session_lock(directory / "preparation"), sessions.session_lock(directory / "requests"):
            pass


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def blocked_reader(tmp_path, monkeypatch, target, *, skip_reads=0):
    """Обычный файл остаётся regular; инъекция блокирует его read_bytes в OS FIFO read."""
    probe = tmp_path / "read-probe"
    probe.mkdir()
    fifo, marker = probe / "fifo", probe / "worker.pid"
    os.mkfifo(fifo)
    shim = probe / "python-read-fixture"
    shim.write_text(f"""#!{PYTHON}
import os, sys, runpy
from pathlib import Path
assert sys.argv[1:4] == ['-P', '-m', 'ai_ops_kit.cli.project_session_resume']
sys.path.insert(0, {KIT!r})
original = Path.read_bytes
seen = 0
def read_bytes(path):
    global seen
    if path.resolve() == Path({str(target.resolve())!r}):
        seen += 1
        if seen > {skip_reads!r}:
            Path({str(marker)!r}).write_text(str(os.getpid()))
            fd = os.open({str(fifo)!r}, os.O_RDWR)
            os.read(fd, 1)
    return original(path)
Path.read_bytes = read_bytes
sys.argv = ['ai_ops_kit.cli.project_session_resume', sys.argv[4]]
runpy.run_module('ai_ops_kit.cli.project_session_resume', run_name='__main__')
""")
    shim.chmod(0o755)
    monkeypatch.setattr(resume.sys, "executable", str(shim))
    return marker, shim


def test_real_worker_resumes_same_prepared_task_and_preserves_claim(project, prepared):
    before = state(project)
    assert resume.TIMEOUT == 30
    result = resume.validate(project, prepared)
    assert result["request_id"] == prepared["request_id"] and result["status"] == prepared["status"]
    assert result["host_actions"]["status"] == "execute_plan"
    assert cli.main(["run", "--runtime", "codex", "--session", "bounded-resume"]) == 1
    assert state(project) == before
    assert not sessions.verify(project, "codex", "bounded-resume")["accepted"]
    assert_unlocked(project)


def test_observer_does_not_change_binding_and_reports_managed_paths(project, prepared):
    paths = []
    feature = "session-" + prepared["request_id"]
    assert sessions.binding(project, feature) == sessions.binding(project, feature, before_read=paths.append)
    assert project / ".ai/managed/blocked.data" in paths
    assert project / ".ai/managed/VERSION" in paths
    assert project / "AGENTS.md" in paths


@pytest.mark.parametrize("kind", ["managed", "artifact"])
def test_blocked_read_is_killed_within_common_deadline_without_state_change(project, prepared, tmp_path, monkeypatch, kind):
    relative = ".ai/managed/blocked.data" if kind == "managed" else next(iter(prepared["execution"]["files"]))
    target = project / relative
    assert target.is_file()  # не FIFO, который binding пропустил бы по is_file()
    marker, _ = blocked_reader(tmp_path, monkeypatch, target)
    before, started = state(project), time.monotonic()
    directory = sessions.session_dir(project, "codex", "bounded-resume")
    with pytest.raises(ValueError, match="превысила 1.5 с") as error:
        with sessions.session_migration_store.barrier(project), sessions.session_lock(directory / "preparation"):
            resume.validate(project, prepared, timeout=1.5)
    assert time.monotonic() - started < 5
    assert marker.is_file()  # worker действительно дошёл до блокирующего syscall
    assert not alive(int(marker.read_text()))
    assert relative in str(error.value)
    assert state(project) == before
    assert_unlocked(project)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_cancelled_cli_reaps_own_blocked_worker_and_releases_locks(project, prepared, tmp_path, monkeypatch, sig):
    marker, shim = blocked_reader(tmp_path, monkeypatch, project / ".ai/managed/blocked.data")
    before = state(project)
    code = ("from ai_ops_kit.cli import project_session_resume as r; "
            f"r.sys.executable={str(shim)!r}; "
            "from ai_ops_kit.cli import project_session as c; "
            "raise SystemExit(c.main(['run','--runtime','codex','--session','bounded-resume']))")
    parent = subprocess.Popen([PYTHON, "-P", "-c", code], cwd=project, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, start_new_session=True,
                              env=dict(os.environ, PYTHONPATH=KIT))
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "не доказан вход worker в блокирующий read"
        pid = int(marker.read_text())
        assert alive(pid)
        parent.send_signal(sig)
        stdout, stderr = parent.communicate(timeout=5)
        assert parent.returncode in (-signal.SIGINT, 130, 2)
        assert ".ai/managed/blocked.data" in stderr
        assert not alive(pid)
        assert state(project) == before
        assert_unlocked(project)
    finally:
        if parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.communicate(timeout=5)
        if marker.exists() and alive(int(marker.read_text())):
            os.killpg(int(marker.read_text()), signal.SIGKILL)


@pytest.mark.parametrize("damage", ["binding", "artifact"])
def test_real_worker_rejects_changed_inputs_without_acceptance_or_state_write(project, prepared, damage):
    if damage == "binding":
        (project / ".ai/managed/blocked.data").write_text("changed managed")
    else:
        (project / next(iter(prepared["execution"]["files"]))).write_text("changed artifact")
    before = state(project)
    with pytest.raises(ValueError, match="контекст|артефакт"):
        resume.validate(project, prepared)
    assert state(project) == before
    assert_unlocked(project)


@pytest.mark.parametrize("receipt", ["", "{}", '{"request_id":"foreign","snapshot_sha256":"foreign"}'])
def test_zero_exit_without_exact_snapshot_receipt_never_confirms_resume(project, prepared, monkeypatch, receipt):
    before = state(project)
    monkeypatch.setattr(sessions, "run_process", lambda command, *a, **kw:
                        subprocess.CompletedProcess(command, 0, receipt, ""))
    with pytest.raises(ValueError):
        resume.validate(project, prepared)
    assert state(project) == before


def test_product_modules_and_inherited_pythonpath_cannot_shadow_real_worker(project, prepared, tmp_path, monkeypatch):
    marker = tmp_path / "shadow-executed"
    malicious = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed product code')\n"
    package = project / "ai_ops_kit"
    package.mkdir()
    (package / "__init__.py").write_text(malicious)
    (project / "yaml.py").write_text(malicious)
    (project / "sitecustomize.py").write_text(malicious)
    assert (package / "__init__.py").read_text() == malicious  # подмена действительно существует
    before = state(project)
    monkeypatch.setenv("PYTHONPATH", str(project))
    result = resume.validate(project, prepared)
    assert result["request_id"] == prepared["request_id"] and result["status"] == prepared["status"]
    assert not marker.exists()
    assert state(project) == before


def test_internal_resume_and_completion_callbacks_do_not_spawn_cli_worker(project, prepared, monkeypatch):
    from ai_ops_kit.cli import project_session_completion as completion
    before = state(project)

    def forbidden(*args, **kwargs):
        pytest.fail("hook/internal callback must not launch the CLI resume worker")

    monkeypatch.setattr(resume, "validate", forbidden)
    monkeypatch.setattr(sessions, "run_process", forbidden)
    assert cli.resume_current(project, "codex", "bounded-resume", prepared) is prepared
    assert completion.prepared(project, "codex", "bounded-resume", prepared) is prepared
    assert cli.continuation(project, "codex", "bounded-resume", prepared) is prepared
    assert state(project) == before


def test_large_host_response_uses_verified_private_ipc_instead_of_stdout_tail(project, prepared):
    task = dict(prepared, synthetic_padding="x" * 8192)
    before = state(project)
    result = resume.validate(project, task)
    assert len(json.dumps(result)) > 4096
    assert result["synthetic_padding"] == task["synthetic_padding"]
    assert result["host_actions"]["status"] == "execute_plan"
    assert state(project) == before


def test_valid_receipt_cannot_change_task_status_in_worker_response(project, prepared, monkeypatch):
    before = state(project)

    def forged(command, root, directory, **kwargs):
        snapshot = Path(command[-1]).read_bytes()
        changed = dict(prepared, status="accepted")
        raw = json.dumps(changed).encode()
        (directory / "response.json").write_bytes(raw)
        receipt = {"request_id": prepared["request_id"], "snapshot_sha256": sessions.digest(snapshot),
                   "response_sha256": sessions.digest(raw)}
        return subprocess.CompletedProcess(command, 0, json.dumps(receipt), "")

    monkeypatch.setattr(sessions, "run_process", forged)
    with pytest.raises(ValueError, match="изменил исходную задачу"):
        resume.validate(project, prepared)
    assert state(project) == before


def test_finished_host_response_second_binding_read_is_inside_same_deadline(project, tmp_path, monkeypatch, capsys):
    from test_project_session_agents import pending_review
    target = project / ".ai/managed/blocked.data"
    target.write_text("regular file for second binding read")
    _, _, output = pending_review(project, monkeypatch, capsys)
    task = sessions.load(project, "codex", "complete")
    assert task["verification"]["phase"] == "finished" and output["host_actions"]["jobs"]
    before = state(project, "complete")
    marker, _ = blocked_reader(tmp_path, monkeypatch, target, skip_reads=1)
    started = time.monotonic()
    with pytest.raises(ValueError, match="превысила 1.5 с") as error:
        resume.validate(project, task, timeout=1.5)
    assert time.monotonic() - started < 5
    assert marker.exists() and not alive(int(marker.read_text()))
    assert ".ai/managed/blocked.data" in str(error.value)
    assert state(project, "complete") == before
    assert_unlocked(project, "complete")
