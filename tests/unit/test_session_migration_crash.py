"""OS process death, not an exception that runs finally blocks."""
import json
import os
import subprocess
import sys

import pytest

from test_session_migration import captured_plan, initialize, project as _project_fixture
from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration as migration
from ai_ops_kit.lifecycle import session_migration_store as store

project = _project_fixture


@pytest.mark.parametrize("phase", ["plan_open", "plan_link", "journal_open", "journal_link", "before_rename", "after_rename", "rollback_before_rename", "rollback_after_rename"])
def test_sigkill_preserves_recoverable_wal_and_all_original_bytes(project, tmp_path, phase):
    initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    before = migration.protected_files(project)
    if phase.startswith("rollback"):
        migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    script = r'''
import os, signal, sys
from pathlib import Path
from ai_ops_kit.lifecycle import session_migration as m, session_migration_store as s
root, snapshot, snapshot_sha, plan, plan_sha, transaction, phase = sys.argv[1:]
original_open, original_link, original_replace = os.open, os.link, os.replace
def die():
    os.kill(os.getpid(), signal.SIGKILL)
def opened(path, *args, **kwargs):
    fd = original_open(path, *args, **kwargs)
    if ((phase == 'plan_open' and str(path).startswith('.creating-plan.json-')) or
            (phase == 'journal_open' and str(path).startswith('.creating-journal.json-'))):
        die()
    return fd
def linked(src, dst, *args, **kwargs):
    result = original_link(src, dst, *args, **kwargs)
    if ((phase == 'plan_link' and dst == 'plan.json') or (phase == 'journal_link' and dst == 'journal.json')):
        die()
    return result
def replaced(src, dst, *args, **kwargs):
    target = str(dst).endswith('.json') and len(str(dst)) == 37
    if target and phase.endswith('before_rename'):
        die()
    result = original_replace(src, dst, *args, **kwargs)
    if target and phase.endswith('after_rename'):
        die()
    return result
os.open, os.link, os.replace = opened, linked, replaced
if phase.startswith('rollback'):
    m.rollback(Path(root), transaction, plan_sha, Path(plan))
else:
    m.apply(Path(root), Path(snapshot), snapshot_sha, Path(plan), plan_sha)
raise SystemExit('kill injection did not execute')
'''
    result = subprocess.run([sys.executable, "-c", script, str(project), str(snapshot), snapshot_sha,
                             str(plan), preview["sha256"], preview["id"], phase], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == -9, result.stdout + result.stderr
    uncertain = migration.protected_files(project)
    with pytest.raises((ValueError, OSError)):
        sessions.begin(project, "codex", "other-owner", "new task", "new-id")
    assert migration.protected_files(project) == uncertain
    migration.rollback(project, preview["id"], preview["sha256"], plan)
    assert migration.protected_files(project) == before
    assert not list((project / ".ai/runtime/sessions").glob("project-*/.migration-*"))


@pytest.mark.parametrize("subdir", [".", ".ai"])
def test_direct_subdirectory_mutator_uses_project_lock(project, tmp_path, subdir):
    initialize(project)
    before = migration.protected_files(project)
    with store.barrier(project, exclusive=True):
        with pytest.raises(ValueError, match="busy"):
            sessions.begin(project / subdir, "codex", "new-owner", "new input", "different-event")
    assert migration.protected_files(project) == before


def test_old_runner_preparation_lock_is_nonblocking(project, tmp_path):
    initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    before = migration.protected_files(project)
    with sessions.session_lock(sessions.session_dir(project, "codex", "owner") / "preparation"):
        with pytest.raises(ValueError, match="другой процесс"):
            migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    assert migration.protected_files(project) == before


def test_cli_requires_window_and_does_not_print_user_data(project, tmp_path):
    initialize(project)
    command = [sys.executable, "-m", "ai_ops_kit.cli.project_session", "migrate", "capture",
               "--project", str(project), "--snapshot", str(tmp_path / "private-snapshot.json")]
    denied = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert denied.returncode == 2
    assert not (tmp_path / "private-snapshot.json").exists()
    result = subprocess.run(command + ["--quiescent-window"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Preserve this request" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["active"] == 1
    assert os.stat(tmp_path / "private-snapshot.json").st_mode & 0o777 == 0o600


def test_each_new_directory_is_fsynced_before_wal_file(tmp_path, monkeypatch):
    events = []
    mkdir, fsync, opened = store.os.mkdir, store.os.fsync, store.os.open

    def directory(*args, **kwargs):
        result = mkdir(*args, **kwargs)
        events.append(("mkdir", kwargs["dir_fd"]))
        return result

    def sync(fd):
        events.append(("fsync", fd))
        return fsync(fd)

    def opening(path, *args, **kwargs):
        if str(path).startswith(".creating-"):
            events.append(("file", None))
        return opened(path, *args, **kwargs)

    monkeypatch.setattr(store.os, "mkdir", directory)
    monkeypatch.setattr(store.os, "fsync", sync)
    monkeypatch.setattr(store.os, "open", opening)
    store.create(tmp_path / "new" / "nested" / "journal.json", {"phase": "applying"})
    for index, (event, fd) in enumerate(events):
        if event == "mkdir":
            assert events[index + 1] == ("fsync", fd)
    assert len([e for e in events if e[0] == "mkdir"]) == 2


@pytest.mark.parametrize("entry", ["claim", "prepare", "current_session"])
def test_state_read_before_migration_is_revalidated_under_lock(project, tmp_path, entry):
    from ai_ops_kit.cli import project_session as cli
    stale = initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    before = migration.protected_files(project)
    with pytest.raises(ValueError, match="binding"):
        if entry == "claim":
            sessions.claim_execution(project, "codex", "owner", stale, {"mode": "current-session"})
        else:
            getattr(cli, entry)(project, "codex", "owner", stale, {"size": "S", "risk": "low"})
    assert migration.protected_files(project) == before
