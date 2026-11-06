"""Узкое pre-spawn восстановление: реальные локальные процессы, без моделей."""
import errno
import subprocess
import sys

import pytest

from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session import project as _project_fixture


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


def command():
    return [sys.executable, "-c", "from pathlib import Path; "
            "p=Path('marker'); p.write_text(p.read_text()+'run\\n' if p.exists() else 'run\\n'); "
            "print('finished')"]


@pytest.mark.parametrize("number", [errno.EAGAIN, errno.ETXTBSY])
def test_transient_before_spawn_recovers_with_one_real_execution(tmp_path, monkeypatch, number):
    actual, attempts, messages = subprocess.Popen, [], []

    def spawn(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError(number, "injected before spawn")
        return actual(*args, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    result = sessions.run_process(command(), tmp_path, tmp_path, timeout=5, progress=messages.append)
    assert result.returncode == 0 and result.stdout.strip() == "finished"
    assert (tmp_path / "marker").read_text() == "run\n"
    assert len(attempts) == 2
    assert "одна повторная попытка" in messages[0] and "pid=" in messages[1]
    assert "одна повторная попытка" in (tmp_path / "process.stderr.log").read_text()


@pytest.mark.parametrize("number,expected", [(errno.EAGAIN, 2), (errno.EACCES, 1), (errno.ENOENT, 1)])
def test_repeated_or_permanent_spawn_failure_never_executes(tmp_path, monkeypatch, number, expected):
    attempts = []

    def spawn(*args, **kwargs):
        attempts.append(1)
        raise OSError(number, "injected before spawn")

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(OSError) as error:
        sessions.run_process(command(), tmp_path, tmp_path, timeout=5)
    assert error.value.errno == number and len(attempts) == expected
    assert not (tmp_path / "marker").exists()


def test_retry_uses_original_deadline_instead_of_new_timeout(tmp_path, monkeypatch):
    attempts, pauses = [], []
    clock = iter([0.0, 0.0, 0.02, 0.04])
    monkeypatch.setattr(sessions.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sessions.time, "sleep", pauses.append)

    def spawn(*args, **kwargs):
        attempts.append(1)
        raise OSError(errno.EAGAIN, "injected before spawn")

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        sessions.run_process(command(), tmp_path, tmp_path, timeout=0.03)
    assert len(attempts) == 1 and pauses == pytest.approx([0.01])
    assert not (tmp_path / "marker").exists()


def test_cancel_during_pre_spawn_recovery_does_not_retry(tmp_path, monkeypatch):
    attempts = []

    def spawn(*args, **kwargs):
        attempts.append(1)
        raise OSError(errno.EAGAIN, "injected before spawn")

    def cancel(message):
        raise KeyboardInterrupt

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(KeyboardInterrupt):
        sessions.run_process(command(), tmp_path, tmp_path, timeout=5, progress=cancel)
    assert len(attempts) == 1 and not (tmp_path / "marker").exists()


def test_real_nonzero_exit_with_side_effect_is_never_repeated(tmp_path, monkeypatch):
    actual, attempts = subprocess.Popen, []

    def spawn(*args, **kwargs):
        attempts.append(1)
        return actual(*args, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    failing = command()
    failing[-1] += "; raise SystemExit(75)"
    result = sessions.run_process(failing, tmp_path, tmp_path, timeout=5)
    assert result.returncode == 75
    assert (tmp_path / "marker").read_text() == "run\n" and len(attempts) == 1


def test_eagain_after_started_process_is_not_a_spawn_retry(tmp_path, monkeypatch):
    actual, attempts = subprocess.Popen, []

    def spawn(*args, **kwargs):
        attempts.append(1)
        process = actual(*args, **kwargs)
        actual_wait, injected = process.wait, []

        def wait(*args, **kwargs):
            code = actual_wait(*args, **kwargs)
            if not injected:
                injected.append(1)
                raise OSError(errno.EAGAIN, "injected AFTER executable finished")
            return code

        process.wait = wait
        return process

    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(OSError) as error:
        sessions.run_process(command(), tmp_path, tmp_path, timeout=5)
    assert error.value.errno == errno.EAGAIN
    assert (tmp_path / "marker").read_text() == "run\n" and len(attempts) == 1


@pytest.mark.parametrize("timeout", [None, True, False, "1", 0, -1, float('nan'),
                                    float('inf'), 10 ** 1000],
                         ids=["none", "true", "false", "string", "zero", "negative", "nan", "inf", "huge"])
def test_invalid_timeout_preserves_logs_and_never_spawns(tmp_path, monkeypatch, timeout):
    log = tmp_path / "process.stdout.log"
    log.write_text("previous evidence")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid timeout must fail before Popen")

    monkeypatch.setattr(sessions.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="timeout"):
        sessions.run_process(command(), tmp_path, tmp_path, timeout=timeout)
    assert log.read_text() == "previous evidence"
    assert not (tmp_path / "process.stderr.log").exists() and not (tmp_path / "marker").exists()


def test_execute_invalid_timeout_precedes_native_readiness_and_claim(project, monkeypatch):
    from ai_ops_kit.providers import codex_native
    task = sessions.begin(project, "codex", "bad-timeout", "Проверь документ")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid timeout must fail before readiness or execution claim")

    monkeypatch.setattr(codex_native, "readiness", forbidden)
    monkeypatch.setattr(sessions, "claim_execution", forbidden)
    with pytest.raises(ValueError, match="timeout"):
        sessions.execute(project, "codex", "bad-timeout", {}, timeout=True)
    assert sessions.load(project, "codex", "bad-timeout") == task
    directory = sessions.session_dir(project, "codex", "bad-timeout")
    assert not list(directory.glob("*.execution-claim"))
    assert not list(directory.glob("process.*.log"))
