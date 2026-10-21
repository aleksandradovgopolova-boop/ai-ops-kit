"""Cross-checkout local/CI contention, fail-closed, owned fixture crash recovery."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ai_ops_kit.shared import host_resources as hr
from ai_ops_kit.devtools import host_resource_cli as cli

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_fixture_lease_environment(monkeypatch):
    # Execnet closes parent fds but preserves env. These tests use only their own
    # tmp_path leases; clearing hints never closes/unlocks the real parent lease.
    monkeypatch.delenv("AI_OPS_HOST_SLOT_FD", raising=False)
    monkeypatch.delenv("AI_OPS_HOST_SLOT_PATH", raising=False)


def test_default_path_is_host_wide_even_with_different_tmpdir(monkeypatch):
    monkeypatch.setenv("TMPDIR", "/other/executor/tmp")
    assert hr.DEFAULT_LOCK == Path("/tmp/ai-ops-kit-heavy.lock")


def test_local_holder_blocks_ci_from_another_checkout(tmp_path):
    path = tmp_path / "shared.lock"
    other = tmp_path / "other-checkout"
    other.mkdir()
    source = str(Path(hr.__file__).parents[2])
    code = ("import sys; sys.path.insert(0,sys.argv[1]); "
            "from ai_ops_kit.shared.host_resources import host_slot; "
            "from pathlib import Path; "
            "with_placeholder")
    code = code.replace("with_placeholder", "\nwith host_slot('ci','self_hosted_ci',path=Path(sys.argv[2])):\n Path('ran').write_text('yes')")
    with hr.host_slot("local", "local", path=path):
        inode = path.stat().st_ino
        result = subprocess.run([sys.executable, "-c", code, source, str(path)], cwd=other,
                                capture_output=True, text=True)
        assert result.returncode != 0 and "host-slot занят" in result.stderr
        assert not (other / "ran").exists() and path.stat().st_ino == inode
    subprocess.run([sys.executable, "-c", code, source, str(path)], cwd=other, check=True)
    assert (other / "ran").read_text() == "yes"  # action truly happened after unlock


def test_owned_holder_crash_releases_without_unlink(tmp_path):
    path = tmp_path / "shared.lock"
    code = ("import sys,time; from pathlib import Path; "
            "from ai_ops_kit.shared.host_resources import host_slot;\n"
            "with host_slot('fixture','local',path=Path(sys.argv[1])):\n print('locked',flush=True); time.sleep(20)")
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        inode = path.stat().st_ino
        with pytest.raises(hr.ResourceBlocked, match="занят"):
            with hr.host_slot("ci", "self_hosted_ci", path=path):
                pytest.fail("must not acquire active foreign slot")
    finally:
        child.terminate()  # Only this test's own fixture process, never a user's process.
        child.wait(timeout=5)
    with hr.host_slot("recovery", "local", path=path):
        assert path.stat().st_ino == inode


def test_env_marker_without_fd_does_not_bypass_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_OPS_HOST_SLOT_FD", "99999999")
    assert hr.inherited_slot(tmp_path / "shared.lock") is None


def test_real_inherited_fd_is_checked_and_child_action_runs(tmp_path):
    path = tmp_path / "shared.lock"
    target = tmp_path / "action"
    command = [sys.executable, "-c",
               "import sys; from pathlib import Path; from ai_ops_kit.shared.host_resources import inherited_slot; "
               "assert inherited_slot(Path(sys.argv[1])) is not None; Path(sys.argv[2]).write_text('ran')",
               str(path), str(target)]
    assert cli.execute(command, "local", "local", path=path, probe=lambda: []) == 0
    assert target.read_text() == "ran"


def test_observed_unwrapped_heavy_process_blocks_action(tmp_path):
    target = tmp_path / "must-not-exist"
    command = [sys.executable, "-c", f"open({str(target)!r},'w').write('ran')"]
    with pytest.raises(hr.ResourceBlocked, match="ps наблюдает"):
        cli.execute(command, "local", "local", path=tmp_path / "shared.lock",
                    probe=lambda: [{"pid": 999, "class": "observed_heavy_command"}])
    assert not target.exists()


def test_symlink_lock_is_blocked_without_changing_target(tmp_path):
    target, path = tmp_path / "foreign", tmp_path / "shared.lock"
    target.write_text("foreign lock data")
    path.symlink_to(target)
    with pytest.raises(hr.ResourceBlocked, match="недоступен"):
        with hr.host_slot("local", "local", path=path):
            pytest.fail("symlink must not be followed")
    assert target.read_text() == "foreign lock data"


def test_native_observer_does_not_treat_waiting_wrapper_as_running_suite(monkeypatch):
    class Result:
        stdout = (f"{os.getpid()} 0 python current-observer\n"
                  "900001 0 python -m ai_ops_kit.devtools.host_resource_cli -- pytest tests/\n"
                  "900002 0 node /runner/node_modules/vitest/vitest.mjs run\n")
    monkeypatch.setattr(hr.subprocess, "run", lambda *a, **kw: Result())
    assert hr.heavy_processes() == [{"pid": 900002, "class": "observed_heavy_command"}]


def test_closed_inherited_fd_returns_blocked_without_waiting_or_unlocking_parent(tmp_path):
    path, target = tmp_path / "parent.lock", tmp_path / "must-not-run"
    with hr.host_slot("parent", "local", path=path) as fd:
        before = path.read_bytes()
        env = {**os.environ, "AI_OPS_HOST_SLOT_FD": str(fd), "AI_OPS_HOST_SLOT_PATH": str(path)}
        command = [sys.executable, "-m", "ai_ops_kit.devtools.host_resource_cli",
                   "--lock-path", str(path), "--wait-seconds", "3600", "--", sys.executable,
                   "-I", "-S", "-c", f"open({str(target)!r},'w').write('ran')"]
        # Default close_fds reproduces the P1; timeout bounds the regression itself.
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
        assert result.returncode == 2 and "fd потерян" in result.stdout
        assert not target.exists() and path.read_bytes() == before
        with pytest.raises(hr.ResourceBlocked, match="занят"):
            with hr.host_slot("foreign", "self_hosted_ci", path=path):
                pytest.fail("must not release parent's lock")


def test_nested_cli_forwards_real_fd_and_keeps_parent_lease(tmp_path):
    path, target = tmp_path / "parent.lock", tmp_path / "ran"
    with hr.host_slot("parent", "local", path=path) as fd:
        before = path.read_bytes()
        env = {**os.environ, "AI_OPS_HOST_SLOT_FD": str(fd), "AI_OPS_HOST_SLOT_PATH": str(path)}
        command = [sys.executable, "-m", "ai_ops_kit.devtools.host_resource_cli",
                   "--lock-path", str(path), "--", sys.executable, "-I", "-S", "-c",
                   f"open({str(target)!r},'w').write('ran')"]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5,
                                **hr.subprocess_kwargs(env))
        assert target.read_text() == "ran", result.stdout + result.stderr
        assert result.returncode == 0 and path.read_bytes() == before
