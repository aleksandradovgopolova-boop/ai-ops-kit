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
import os, signal, sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from pathlib import Path
from ai_ops_kit.cli import project_session as cli
actual = Path.{method}
def read(path, *args, **kwargs):
    if path == Path({str(target)!r}):
        # Бюджет отсчитывается от блокировки, а не от старта: предварительные чтения
        # под параллельной нагрузкой не должны съедать его до проверяемой точки (#1579).
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0, "чтение должно идти под бюджетом hook"
        signal.setitimer(signal.ITIMER_REAL, 0.7)
        Path({str(marker)!r}).write_text('entered')
        fd = os.open({str(fifo)!r}, os.O_RDWR)
        os.read(fd, 1)
    return actual(path, *args, **kwargs)
Path.{method} = read
raise SystemExit(cli.main(['intake','--runtime','codex','--session','native']))
"""
    process = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=project,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        process.stdin.write('{"prompt":"original"}')
        process.stdin.close()
        process.stdin = None
        deadline = time.monotonic() + 30  # потолок только от зависания: ждём событие
        # Ждём содержимое, а не появление файла: write_text создаёт его пустым до записи.
        while not (marker.exists() and marker.read_text() == "entered") and time.monotonic() < deadline:
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


@pytest.mark.parametrize("entry", ["intake", "UserPromptSubmit", "SessionStart"])
def test_missing_active_pointer_preserves_saved_task(project, entry):
    task = cli.initial_intake(project, "codex", "native", "original")
    directory = sessions.session_dir(project, "codex", "native")
    pointer = directory / "active.json"
    pointer.unlink()
    before = state(project)
    assert (directory / (task["request_id"] + ".json")).is_file()
    with pytest.raises(ValueError, match="active.json"):
        if entry == "intake":
            cli.initial_intake(project, "codex", "native", "new")
        else:
            cli.hook("codex", {"hook_event_name": entry, "cwd": str(project),
                               "session_id": "native", "prompt": "new", "turn_id": "next"})
    assert state(project) == before


@pytest.mark.parametrize("suffix", [".execution-claim", ".inputs", ".reviews", ".verification-attempt.json"])
def test_orphaned_execution_evidence_prevents_fresh_intake(project, suffix):
    directory = sessions.session_dir(project, "codex", "native")
    directory.mkdir(parents=True)
    (directory / "requests.lock").touch()
    marker = directory / ("a" * 32 + suffix)
    if suffix in (".reviews", ".inputs"):
        marker.mkdir()
    else:
        marker.touch()
    with sessions.session_migration_store.barrier(project):
        before = state(project)
    with pytest.raises(ValueError, match="active.json"):
        cli.initial_intake(project, "codex", "native", "new")
    assert state(project) == before


def test_empty_session_lock_and_unrelated_file_allow_first_intake(project):
    directory = sessions.session_dir(project, "codex", "native")
    directory.mkdir(parents=True)
    (directory / "requests.lock").touch()
    (directory / ".DS_Store").write_bytes(b"metadata")
    task = cli.initial_intake(project, "codex", "native", "first")
    assert sessions.load(project, "codex", "native") == task
    assert task["status"] == "pending"


def test_session_start_refuses_pointer_whose_task_record_is_missing(project):
    task = cli.initial_intake(project, "codex", "native", "original")
    directory = sessions.session_dir(project, "codex", "native")
    (directory / (task["request_id"] + ".json")).unlink()
    before = state(project)
    with pytest.raises(FileNotFoundError):
        cli.hook("codex", {"hook_event_name": "SessionStart", "cwd": str(project),
                           "session_id": "native"})
    assert state(project) == before


def test_initial_intake_preserves_dangling_pointer(project):
    directory = sessions.session_dir(project, "codex", "native")
    directory.mkdir(parents=True)
    pointer = directory / "active.json"
    pointer.symlink_to("absent")
    with pytest.raises(ValueError, match="active.json"):
        cli.initial_intake(project, "codex", "native", "new")
    assert pointer.is_symlink() and not (directory / "absent").exists()
    assert list(directory.glob("*.json")) == [pointer]


@pytest.mark.parametrize("write_report", [False, True], ids=["no-report", "planned-report"])
def test_controller_failure_survives_reconcile(project, monkeypatch, capsys, write_report):
    task = cli.initial_intake(project, "codex", "native", "Проверь документ")
    monkeypatch.chdir(project)
    run_process = sessions.run_process
    calls = []

    def fail_controller(command, root, directory, **kwargs):
        calls.append(command)
        # Реальный контроллер успевает записать валидный отчёт во втором сценарии.
        failing = [sys.executable, "-c",
                   "import subprocess, sys\n"
                   "if sys.argv[1] == 'after': subprocess.run(sys.argv[2:], check=True)\n"
                   "print('local diagnostic marker', file=sys.stderr)\n"
                   "sys.exit(73)", "after" if write_report else "before", *command]
        return run_process(failing, root, directory, **kwargs)

    monkeypatch.setattr(sessions, "run_process", fail_controller)
    args = ["--runtime", "codex", "--session", "native"]
    assert cli.main(["run", *args, "--signals",
                     '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    saved = sessions.load(project, "codex", "native")
    assert saved["status"] == "blocked" and saved["execution"]["controller_exit_code"] == 73
    assert not saved["execution"].get("prepared")
    log = sessions.session_dir(project, "codex", "native") / "process.stderr.log"
    assert "local diagnostic marker" in log.read_text()
    assert str(log.relative_to(project)) in saved["blocker"] and "73" in saved["blocker"]
    assert "local diagnostic marker" not in saved["blocker"]
    report = project / "features" / ("session-" + task["request_id"]) / "run-report.json"
    if write_report:
        assert json.loads(report.read_text())["status"] == "planned"
    else:
        assert not report.exists()
    before = state(project)
    capsys.readouterr()
    assert cli.main(["reconcile", *args]) == 2
    assert saved["blocker"] in capsys.readouterr().err
    assert len(calls) == 1 and state(project) == before


@pytest.mark.parametrize("revise_signals", [False, True])
def test_registry_denial_keeps_same_request_retryable(project, monkeypatch, revise_signals):
    from ai_ops_kit.lifecycle import work_claims

    task = cli.initial_intake(project, "codex", "native", "Проверь документ")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "native"]
    directory = sessions.session_dir(project, "codex", "native")
    with monkeypatch.context() as blocked:
        def deny(root):
            raise PermissionError("synthetic EPERM")

        blocked.setattr(work_claims, "probe_registry_write", deny)
        blocked.setattr(sessions, "run_process", lambda *a, **kw: pytest.fail("controller started"))
        assert cli.main([*args, "--signals", '{"task_type":"quick","size":"small","risk":"low"}']) == 1
        saved = sessions.pending(project, "codex", "native")
        assert saved["request_id"] == task["request_id"] and "synthetic EPERM" in saved["blocker"]
        assert "execution" not in saved and not list(directory.glob("*.execution-claim"))
        cli.waiting_continuation(project, "codex", "native", saved)
        assert not (project / ".git/ai-ops/active-work.yaml").exists()
    resume_args = list(args)
    if revise_signals:
        assert cli.main([*args, "--signals", '{"risk":null}']) == 2
        waiting = sessions.pending(project, "codex", "native")
        assert "risk" in waiting["blocker"] and "реестр" not in waiting["blocker"]
        assert "реестр" not in waiting["next_step"] and "registry_error" not in waiting["intake"]
        resume_args.extend(["--signals", '{"risk":"low"}'])
    assert cli.main(resume_args) == 1
    saved = sessions.load(project, "codex", "native")
    assert saved["request_id"] == task["request_id"] and saved["execution"]["prepared"] is True
    assert len(list(directory.glob("*.execution-claim"))) == 1 and saved["blocker"] is None
    assert (project / ".git/ai-ops/active-work.yaml").is_file()


def test_registry_probe_uses_common_store_and_preserves_existing_files(project, tmp_path):
    from ai_ops_kit.lifecycle import work_claims

    linked = tmp_path / "linked"
    subprocess.run(["git", "-C", str(project), "worktree", "add", "--detach", str(linked)], check=True)
    registry = work_claims.shared_registry_path(project)
    registry.parent.mkdir()
    lock = registry.with_suffix(".yaml.lock")
    registry.write_bytes(b"owner registry")
    lock.write_bytes(b"owner lock")
    work_claims.probe_registry_write(linked)
    assert set(registry.parent.iterdir()) == {registry, lock}
    assert registry.read_bytes() == b"owner registry" and lock.read_bytes() == b"owner lock"
    assert not (linked / ".ai/runtime/active-work.yaml").exists()


def test_writable_registry_directory_does_not_admit_failed_registration(project, monkeypatch):
    from ai_ops_kit.lifecycle import work_claims

    task = cli.initial_intake(project, "codex", "native", "Проверь документ")
    monkeypatch.chdir(project)
    registry = work_claims.shared_registry_path(project)
    lock = registry.with_suffix(".yaml.lock")
    lock.mkdir(parents=True)
    owner = lock / "owner"
    owner.write_bytes(b"untouched")
    args = ["run", "--runtime", "codex", "--session", "native"]
    assert cli.main([*args, "--signals", '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    saved = sessions.load(project, "codex", "native")
    assert saved["request_id"] == task["request_id"]
    assert saved["status"] == "blocked" and saved["execution"]["controller_exit_code"] != 0
    before = state(project)
    assert cli.main(args) == 2 and state(project) == before
    assert owner.read_bytes() == b"untouched" and not registry.exists()
