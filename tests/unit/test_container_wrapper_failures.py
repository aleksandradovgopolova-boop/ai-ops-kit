"""Реальные Git/subprocess отказы wrappers; только свой fake Docker, без daemon/сети."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "containers/run-sandboxed.sh"
DELIVER = REPO / "containers/deliver-run-branches.sh"
pytestmark = [pytest.mark.unit, pytest.mark.skipif(os.name != "posix", reason="Bash/POSIX signals")]

# Reviewed fixture code. Never executes the task text, child code, or arbitrary Docker argv.
FAKE_DOCKER = r'''
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

args = sys.argv[1:]
mount = args[args.index("--mount") + 1]
clone = Path(mount.removeprefix("type=bind,src=").removesuffix(",dst=/work"))
assert (clone / ".git").is_dir()
(clone / "fake-docker-started").write_text("own fixture ran")
mode = os.environ["FAKE_MODE"]

def git(*argv):
    return subprocess.run(["git", "-C", str(clone), *argv], check=True,
                          capture_output=True, text=True).stdout.strip()

if mode == "branches":
    git("add", "fake-docker-started")
    git("commit", "-qm", "fixture: own run")
    git("update-ref", "refs/heads/ai-ops/result", "HEAD")
    git("branch", "feature/not-deliverable", "HEAD")

record = Path(os.environ["FAKE_RECORD"])
def stopped(number, _frame):
    record.with_suffix(".stopped").write_text(str(number))
    sys.exit(128 + number)

signal.signal(signal.SIGINT, stopped)
signal.signal(signal.SIGTERM, stopped)
record.with_suffix(".tmp").write_text(json.dumps({
    "argv": args, "pid": os.getpid(), "clone": str(clone),
    "head": git("rev-parse", "HEAD"), "started": True,
}))
record.with_suffix(".tmp").replace(record)
if mode == "block":
    while True:
        time.sleep(0.02)
print("fake Docker: controlled diagnostic", file=sys.stderr)
sys.exit(int(os.environ["FAKE_RC"]))
'''


@dataclass
class WrapperHarness:
    root: Path
    child: Path
    workbase: Path
    bindir: Path
    env: dict[str, str]
    processes: list[subprocess.Popen] = field(default_factory=list)

    def git(self, *args, repo=None):
        return subprocess.run(
            [str(self.bindir / "git"), "-C", str(repo or self.child), *args],
            env=self.env, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()

    def child_state(self):
        return (
            self.git("rev-parse", "HEAD"),
            self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
            self.git("status", "--porcelain"),
            (self.child / "tracked.txt").read_bytes(),
            (self.child / "untracked.txt").read_bytes(),
        )

    def start(self, args=None, *, mode="done", rc=0, script=WRAPPER):
        env = dict(self.env, FAKE_MODE=mode, FAKE_RC=str(rc))
        proc = subprocess.Popen(
            [str(self.bindir / "bash"), str(script),
             *([str(self.child), "задача с пробелами"] if args is None else args)],
            env=env, cwd=self.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.processes.append(proc)
        return proc

    def run(self, *args, **kwargs):
        proc = self.start(*args, **kwargs)
        stdout, stderr = proc.communicate(timeout=8)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

    @property
    def record(self):
        return Path(self.env["FAKE_RECORD"])

    def started(self, proc):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.record.exists():
                data = json.loads(self.record.read_text())
                assert data["started"]
                assert (Path(data["clone"]) / "fake-docker-started").read_text() == "own fixture ran"
                assert proc.poll() is None
                assert process_exists(data["pid"])
                return data
            if proc.poll() is not None:
                pytest.fail(f"wrapper exited before fake Docker started: {proc.communicate()}")
            time.sleep(0.01)
        pytest.fail("own fake Docker did not start")


def process_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def assert_stopped(pid):
    deadline = time.monotonic() + 2
    while process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not process_exists(pid), f"own fixture PID {pid} survived wrapper completion"


@pytest.fixture
def harness(tmp_path):
    bindir = tmp_path / "controlled bin"
    bindir.mkdir()
    # An allowlist PATH guarantees the host's real Docker is never a fallback, even in
    # the command-not-found test. Absolute links still allow Git's trusted helpers.
    for name in ("bash", "git", "dirname", "mktemp", "rm", "awk"):
        executable = shutil.which(name)
        if executable is None:
            pytest.skip(f"required executable unavailable: {name}")
        (bindir / name).symlink_to(executable)
    docker = bindir / "docker"
    docker.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    docker.chmod(0o755)
    child = tmp_path / "child with spaces"
    child.mkdir()
    workbase = tmp_path / "disposable base with spaces"
    workbase.mkdir()
    home = tmp_path / "empty home"
    home.mkdir()
    env = {
        "PATH": str(bindir), "HOME": str(home), "LC_ALL": "C", "TMPDIR": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_TERMINAL_PROMPT": "0", "AI_OPS_WORKDIR": str(workbase),
        "FAKE_RECORD": str(tmp_path / "docker.json"),
    }
    h = WrapperHarness(tmp_path, child, workbase, bindir, env)
    h.git("init", "-q", "--initial-branch=main")
    h.git("config", "maintenance.auto", "false")
    h.git("config", "gc.auto", "0")
    (child / "tracked.txt").write_text("committed\n")
    h.git("add", "tracked.txt")
    h.git("commit", "-qm", "fixture: initial")
    (child / "tracked.txt").write_text("user dirty work\n")
    (child / "untracked.txt").write_text("user untracked work\n")
    try:
        yield h
    finally:
        # Emergency teardown must not make a failing cleanup assertion pass. This session
        # was created by this fixture; no process discovery or signals to foreign PIDs.
        for proc in h.processes:
            own_docker_alive = False
            if h.record.exists():
                pid = json.loads(h.record.read_text())["pid"]
                try:
                    own_docker_alive = os.getpgid(pid) == proc.pid
                except ProcessLookupError:
                    pass
            if proc.poll() is not None and not own_docker_alive:
                continue
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate(timeout=5)


@pytest.mark.parametrize("args", [[], ["{child}"], ["", "task"], ["{child}", ""]])
def test_wrapper_rejects_missing_arguments_before_clone(harness, args):
    before = harness.child_state()
    args = [arg.replace("{child}", str(harness.child)) for arg in args]
    result = harness.run(args)
    assert result.returncode != 0
    assert "укажи" in result.stderr
    assert not harness.record.exists()
    assert list(harness.workbase.iterdir()) == []
    assert harness.child_state() == before


@pytest.mark.parametrize("target", ["absent", "not a repository"])
def test_wrapper_rejects_invalid_child_before_docker(harness, target):
    before = harness.child_state()
    path = harness.root / target
    if target != "absent":
        path.mkdir()
    result = harness.run([str(path), "task"])
    assert result.returncode != 0
    assert result.stderr
    assert not harness.record.exists()
    assert list(harness.workbase.iterdir()) == []
    assert harness.child_state() == before


@pytest.mark.parametrize("count", [0, 1, 2])
def test_delivery_requires_all_arguments(harness, count):
    before = harness.child_state()
    result = harness.run([str(harness.child)] * count, script=DELIVER)
    assert result.returncode != 0
    assert "нужен" in result.stderr
    assert harness.child_state() == before


def test_clone_failure_cleans_created_disposable_and_preserves_input(harness):
    before = harness.child_state()
    broken = harness.root / "broken child"
    (broken / ".git").mkdir(parents=True)
    (broken / "keep.txt").write_text("own input")
    result = harness.run([str(broken), "task"])
    assert result.returncode != 0
    assert "одноразовый checkout" in result.stderr  # mktemp succeeded before Git refused.
    assert "repository" in result.stderr
    assert not harness.record.exists()
    assert list(harness.workbase.iterdir()) == []
    assert (broken / "keep.txt").read_text() == "own input"
    assert harness.child_state() == before


@pytest.mark.parametrize("provider_configured", [False, True])
def test_spaces_reach_docker_as_single_arguments_and_only_clone_is_writable(harness, provider_configured):
    before = harness.child_state()
    if provider_configured:
        harness.env["OPENAI_COMPATIBLE_BASE_URL"] = "https://fixture.invalid/provider path"
    task = "задача 'с кавычками' и пробелами; $(do-not-execute)"
    result = harness.run([str(harness.child), task, "--model", "model with spaces"])
    data = json.loads(harness.record.read_text())
    clone = Path(data["clone"])
    args = data["argv"]
    assert data["started"]
    assert result.returncode == 0, result.stderr
    assert args[-5:] == ["run", task, "/work", "--model", "model with spaces"]
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
    assert mounts == [f"type=bind,src={clone},dst=/work"]
    assert clone.parent.parent == harness.workbase
    assert clone != harness.child
    assert "--read-only" in args
    assert "GIT_TERMINAL_PROMPT=0" in args
    assert ("OPENAI_COMPATIBLE_BASE_URL" in args) == provider_configured
    assert "https://fixture.invalid/provider path" not in args
    assert not clone.parent.exists()
    assert harness.child_state() == before
    assert_stopped(data["pid"])


@pytest.mark.parametrize("rc", [37, 125])
def test_docker_failure_is_observable_and_clone_is_cleaned(harness, rc):
    before = harness.child_state()
    result = harness.run(rc=rc)
    data = json.loads(harness.record.read_text())
    assert data["started"]
    assert result.returncode == rc
    assert "fake Docker: controlled diagnostic" in result.stderr
    assert not Path(data["clone"]).parent.exists()
    assert harness.child_state() == before
    assert_stopped(data["pid"])


def test_missing_docker_fails_after_clone_and_cleans_only_disposable(harness):
    before = harness.child_state()
    (harness.bindir / "docker").unlink()
    unrelated = harness.workbase / "keep other run"
    unrelated.mkdir()
    result = harness.run()
    assert result.returncode == 127
    assert "docker: command not found" in result.stderr
    assert "одноразовый checkout" in result.stderr
    assert not harness.record.exists()
    assert list(harness.workbase.iterdir()) == [unrelated]
    assert harness.child_state() == before


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_signal_to_wrapper_stops_started_docker_and_cleans_clone(harness, sig):
    before = harness.child_state()
    unrelated = harness.workbase / "another run"
    unrelated.mkdir()
    proc = harness.start(mode="block")
    data = harness.started(proc)
    proc.send_signal(sig)  # Only wrapper receives the signal: it must forward and reap.
    proc.communicate(timeout=3)
    assert proc.returncode != 0
    assert_stopped(data["pid"])
    assert harness.record.with_suffix(".stopped").read_text() == str(sig)
    assert list(harness.workbase.iterdir()) == [unrelated]
    assert harness.child_state() == before


def test_harness_timeout_terminates_started_run_without_leaking_processes(harness):
    before = harness.child_state()
    proc = harness.start(mode="block")
    data = harness.started(proc)
    with pytest.raises(subprocess.TimeoutExpired):
        proc.communicate(timeout=0.1)
    proc.terminate()  # A bounded harness deadline, not a new public wrapper option.
    proc.communicate(timeout=3)
    assert proc.returncode != 0
    assert_stopped(data["pid"])
    assert list(harness.workbase.iterdir()) == []
    assert harness.child_state() == before


def test_wrapper_delivers_only_run_ai_ops_branch_and_preserves_child_files(harness):
    before = harness.child_state()
    result = harness.run(mode="branches")
    data = json.loads(harness.record.read_text())
    assert data["head"] != before[0]  # The fake actually committed work before delivery.
    assert result.returncode == 0, result.stderr
    assert harness.git("rev-parse", "ai-ops/result") == data["head"]
    assert "feature/not-deliverable" not in harness.git("branch", "--list")
    after = harness.child_state()
    assert after[0] == before[0]
    assert after[2:] == before[2:]
    assert not Path(data["clone"]).parent.exists()
    assert_stopped(data["pid"])


def test_failed_delivery_retains_real_run_branch_and_reports_recovery_path(harness):
    harness.git("checkout", "-qb", "ai-ops/result")
    before = harness.child_state()
    result = harness.run(mode="branches", rc=37)
    data = json.loads(harness.record.read_text())
    clone = Path(data["clone"])
    assert data["head"] != before[0]
    assert harness.git("rev-parse", "ai-ops/result", repo=clone) == data["head"]
    assert result.returncode == 37
    assert "refusing to fetch into branch" in result.stderr
    assert f"работа сохранена в {clone} (не удаляю)" in result.stderr
    assert clone.is_dir()
    assert harness.child_state() == before
    assert_stopped(data["pid"])


@pytest.mark.parametrize("target", ["absent", "not a repository"])
def test_delivery_rejects_invalid_clone_without_success_message(harness, target):
    before = harness.child_state()
    clone = harness.root / target
    if target != "absent":
        clone.mkdir()
    snap = harness.root / "snapshot before"
    snap.write_text("")
    result = harness.run([str(clone), str(harness.child), str(snap)], script=DELIVER)
    assert result.returncode != 0
    assert result.stderr
    assert "DELIVER:" not in result.stdout
    assert harness.child_state() == before


def test_delivery_does_not_swallow_ref_enumeration_failure(harness):
    before = harness.child_state()
    clone = harness.root / "clone with spaces"
    harness.git("clone", "--quiet", "--no-hardlinks", "--local", str(harness.child), str(clone))
    assert (clone / ".git").is_dir()
    (clone / ".git/packed-refs").write_text("invalid packed refs\n")
    with pytest.raises(subprocess.CalledProcessError):
        harness.git("for-each-ref", repo=clone)  # Prove Git itself fails before testing helper.
    snap = harness.root / "snapshot before"
    snap.write_text("")
    result = harness.run([str(clone), str(harness.child), str(snap)], script=DELIVER)
    assert result.returncode != 0
    assert "packed-refs" in result.stderr
    assert "DELIVER:" not in result.stdout
    assert clone.is_dir()
    assert harness.child_state() == before


def test_delivery_with_valid_unchanged_clone_reports_nothing(harness):
    before = harness.child_state()
    clone = harness.root / "unchanged clone"
    harness.git("clone", "--quiet", "--no-hardlinks", "--local", str(harness.child), str(clone))
    assert harness.git("rev-parse", "HEAD", repo=clone) == before[0]
    snap = harness.root / "snapshot before"
    snap.write_text("")
    result = harness.run([str(clone), str(harness.child), str(snap)], script=DELIVER)
    assert result.returncode == 0, result.stderr
    assert "DELIVER: nothing" in result.stdout
    assert clone.is_dir()
    assert harness.child_state() == before


@pytest.mark.parametrize("target", ["absent child", "nonrepo child"])
def test_delivery_fetch_failure_preserves_created_run_ref(harness, target):
    before = harness.child_state()
    clone = harness.root / "run clone"
    harness.git("clone", "--quiet", "--no-hardlinks", "--local", str(harness.child), str(clone))
    harness.git("branch", "ai-ops/result", repo=clone)
    assert harness.git("rev-parse", "ai-ops/result", repo=clone) == before[0]
    child = harness.root / target
    if target == "nonrepo child":
        child.mkdir()
    snap = harness.root / "snapshot before"
    snap.write_text("")
    result = harness.run([str(clone), str(child), str(snap)], script=DELIVER)
    assert result.returncode != 0
    assert result.stderr
    assert "DELIVER:" not in result.stdout
    assert harness.git("rev-parse", "ai-ops/result", repo=clone) == before[0]
    assert harness.child_state() == before
