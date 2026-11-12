"""No-model smoke образа (`validate_container_assets.py --image-smoke`, #1478).

Настоящий Docker в unit-тестах недоступен, поэтому в PATH стоит подставной `docker`: он пишет
журнал вызовов и «собирает образ» из РЕАЛЬНО переданного ему архива контекста — launch target
в «образе» ровно тот, что лежал в tar. Так проверяется путь кода, а не строки: что именно уходит
в сборку, с какими флагами стартует контейнер, что образ убирается, и что без Docker результат —
BLOCKED, а не успех.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import validate_container_assets as vca

FAKE_DOCKER = r'''
import hashlib, io, json, os, sys, tarfile
args = sys.argv[1:]
mode = os.environ.get("FAKE_DOCKER_MODE", "").split(",")
state_path = os.environ["FAKE_DOCKER_STATE"]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
state = json.load(open(state_path)) if os.path.exists(state_path) else {}
def fail(msg):
    sys.stderr.write(msg + "\n"); sys.exit(1)
if args[0] == "info":
    if "daemon_down" in mode:
        fail("Cannot connect to the Docker daemon")
    print("27.0.0")
elif args[0] == "build":
    if "build_fails" in mode:
        fail("boom: build failed")
    names = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()))
    members = {m.name: m for m in names.getmembers()}
    if "containers/Dockerfile" not in members:
        fail("no Dockerfile in context")
    blob = names.extractfile(members["ai_ops_kit/engine/ai_ops_run.py"]).read()
    label = args[args.index("--label") + 1].split("=", 1)[1]
    state = {"tag": args[args.index("-t") + 1], "label": label,
             "sha": hashlib.sha256(blob).hexdigest()}
    json.dump(state, open(state_path, "w"))
elif args[:2] == ["image", "inspect"]:
    print(state.get("label", ""))
elif args[0] == "run" and "--entrypoint" in args:
    sha = "0" * 64 if "tampered" in mode else state["sha"]
    print("/opt/ai-ops-kit/ai_ops_kit/engine/ai_ops_run.py"); print(sha)
elif args[0] == "run":
    if "help_fails" in mode:
        fail("ModuleNotFoundError: No module named 'ai_ops_kit'")
    print("usage: ai_ops_run.py [-h] {run,resume} ...")
elif args[:2] == ["image", "rm"]:
    if "rm_fails" in mode:
        fail("conflict: image in use")
    state.clear(); json.dump(state, open(state_path, "w"))
'''


def _git(root, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "kit"
    (root / "containers").mkdir(parents=True)
    (root / "containers/Dockerfile").write_text("FROM scratch\n")
    target = root / vca.LAUNCH_TARGET
    target.parent.mkdir(parents=True)
    target.write_text("print('committed controller')\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture
def docker(tmp_path, monkeypatch):
    """Подставной docker в PATH; возвращает (задать режим, прочитать журнал, состояние «образа»)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "docker"
    exe.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
    exe.chmod(0o755)
    log, state = tmp_path / "docker.log", tmp_path / "docker.state"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state))

    class Fake:
        @staticmethod
        def mode(*modes):
            monkeypatch.setenv("FAKE_DOCKER_MODE", ",".join(modes))

        @staticmethod
        def calls():
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

        @staticmethod
        def image():
            return json.loads(state.read_text()) if state.exists() else {}
    return Fake


def _verbs(calls):
    return [c[0] if c[0] in {"info", "build", "run"} else " ".join(c[:2]) for c in calls]


def test_smoke_builds_exact_commit_and_starts_cli_without_network(repo, docker):
    code, lines = vca.image_smoke(repo)
    assert code == 0, lines
    rev = _git(repo, "rev-parse", "HEAD")
    assert f"CONTAINER-IMAGE-SMOKE-OK: образ собран из коммита {rev}" in lines[0]
    assert "НЕ проверена (#1407)" in lines[0]
    calls = docker.calls()
    assert _verbs(calls) == ["info", "build", "image inspect", "run", "run", "image rm"]
    build = calls[1]
    assert build[-1] == "-" and f"{vca.REVISION_LABEL}={rev}" in build
    for run in (c for c in calls if c[0] == "run"):
        assert run[1:1 + len(vca.SMOKE_RUN_FLAGS)] == vca.SMOKE_RUN_FLAGS
    assert calls[3][-1] == "--help"


def test_uncommitted_edit_does_not_reach_the_image(repo, docker):
    """Сборка идёт из коммита: правка в рабочем дереве в образ не попадает, проверка видит коммит."""
    committed = vca.hashlib.sha256((repo / vca.LAUNCH_TARGET).read_bytes()).hexdigest()
    dirty = repo / vca.LAUNCH_TARGET
    dirty.write_text("print('dirty, never committed')\n")
    assert vca.hashlib.sha256(dirty.read_bytes()).hexdigest() != committed  # правка реальна
    docker.mode("rm_fails")  # оставить «образ», чтобы увидеть, что в него попало
    assert vca.image_smoke(repo)[0] == 0
    assert docker.image()["sha"] == committed


def test_no_docker_is_blocked_not_success(repo, monkeypatch, tmp_path):
    empty = tmp_path / "nobin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code, lines = vca.image_smoke(repo)
    assert code == 2
    assert "BLOCKED" in lines[0] and "SMOKE-OK" not in lines[0]


def test_daemon_down_is_blocked_and_nothing_is_built(repo, docker):
    docker.mode("daemon_down")
    code, lines = vca.image_smoke(repo)
    assert code == 2 and "BLOCKED" in lines[0]
    assert _verbs(docker.calls()) == ["info"]


def test_launch_target_missing_in_commit_fails_before_build(repo, docker):
    _git(repo, "rm", "-q", vca.LAUNCH_TARGET)
    _git(repo, "commit", "-qm", "drop target")
    assert not (repo / vca.LAUNCH_TARGET).exists()
    code, lines = vca.image_smoke(repo)
    assert code == 1
    assert any(vca.LAUNCH_TARGET in line for line in lines)
    assert "build" not in _verbs(docker.calls())


@pytest.mark.parametrize("mode, needle", [
    ("build_fails", "сборка образа упала"),
    ("help_fails", "--help не ответил"),
    ("tampered", "не совпадает с коммитом"),
])
def test_broken_image_fails_and_is_still_removed(repo, docker, mode, needle):
    docker.mode(mode)
    code, lines = vca.image_smoke(repo)
    assert code == 1
    assert any(needle in line for line in lines), lines
    assert not any("SMOKE-OK" in line for line in lines)
    assert _verbs(docker.calls())[-1] == "image rm"
    assert docker.image() == {}


def test_leftover_image_is_reported_without_masking_result(repo, docker):
    docker.mode("rm_fails")
    code, lines = vca.image_smoke(repo)
    assert code == 0
    assert any("не удалён" in line for line in lines)
    assert docker.image()["sha"] == vca.hashlib.sha256((repo / vca.LAUNCH_TARGET).read_bytes()).hexdigest()


def test_standalone_image_smoke_without_docker_exits_2(tmp_path):
    validator = Path(vca.__file__)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(validator), "--image-smoke"], env=env, text=True,
                            capture_output=True, timeout=30)
    assert result.returncode == 2, result.stderr
    assert "BLOCKED" in result.stdout and "SMOKE-OK" not in result.stdout
