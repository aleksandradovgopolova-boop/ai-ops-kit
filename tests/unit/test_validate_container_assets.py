"""Гранулярные тесты validate_container_assets (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest
import json
import os
import subprocess
import sys

from validate_container_assets import (  # noqa: F401
    check_assets,
    check_dockerfile,
    check_wrapper,
    main,
    PKG,
)


GOOD_DOCKERFILE = (
    "FROM node:22-slim\n"
    "RUN pyyaml openspec\n"
    "COPY . /opt/ai-ops-kit\n"
    "ENV PYTHONPATH=/opt/ai-ops-kit\n"
    "USER runner\n"
    "ENV GIT_ASKPASS=/bin/false GIT_TERMINAL_PROMPT=0 "
    'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=""\n'
    'ENTRYPOINT ["python3", "-m", "ai_ops_kit.engine.ai_ops_run"]\n'
)

GOOD_WRAPPER = (
    'git clone --no-hardlinks --local "$CHILD_ABS" "$CLONE"\n'
    "docker run --read-only --tmpfs /tmp --memory 2g --cpus 2 --pids-limit 512 "
    "-e GIT_ASKPASS=/bin/false -e GIT_TERMINAL_PROMPT=0 "
    "-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=credential.helper -e GIT_CONFIG_VALUE_0= "
    '--cap-drop ALL --security-opt no-new-privileges --mount type=bind,src=${CLONE},dst=/work img\n'
    '"$SCRIPT_DIR/deliver-run-branches.sh" "$CLONE" "$CHILD_ABS" "$SNAP_BEFORE"\n'
)


@pytest.mark.unit
def test_dockerfile_full_markers():
    assert check_dockerfile(GOOD_DOCKERFILE) == []


@pytest.mark.unit
def test_dockerfile_without_user_runner():
    errs = check_dockerfile(GOOD_DOCKERFILE.replace("USER runner", "USER root"))
    assert any("USER runner" in e for e in errs)


@pytest.mark.unit
def test_wrapper_full_jail_flags():
    assert check_wrapper(GOOD_WRAPPER) == []


@pytest.mark.unit
def test_wrapper_without_cap_drop():
    errs = check_wrapper(GOOD_WRAPPER.replace("--cap-drop ALL", ""))
    assert any("--cap-drop" in e for e in errs)


@pytest.mark.unit
def test_wrapper_without_read_only():
    errs = check_wrapper(GOOD_WRAPPER.replace("--read-only", ""))
    assert any("--read-only" in e for e in errs)


@pytest.mark.unit
def test_wrapper_direct_child_mount():
    bad_wr = GOOD_WRAPPER.replace("src=${CLONE},dst=/work", "src=${CHILD_ABS},dst=/work")
    errs = check_wrapper(bad_wr)
    assert any("worktree-only" in e for e in errs)


@pytest.mark.unit
def test_wrapper_credentialless_push_markers():
    """Wrapper объявляет credential-less git для push (ПЕРВЫЙ рубеж недоставки — среда)."""
    assert check_wrapper(GOOD_WRAPPER) == []
    for marker in ("GIT_ASKPASS=/bin/false", "GIT_TERMINAL_PROMPT=0",
                   "GIT_CONFIG_KEY_0=credential.helper"):
        assert marker in GOOD_WRAPPER


@pytest.mark.unit
@pytest.mark.parametrize("dropped", [
    "GIT_ASKPASS=/bin/false",
    "GIT_TERMINAL_PROMPT=0",
    "GIT_CONFIG_KEY_0=credential.helper",
])
def test_wrapper_without_credentialless_fails_closed(dropped):
    """Fail-closed: убери гарантию credential-less → валидатор краснеет (для wrapper и Dockerfile)."""
    assert any(dropped in e for e in check_wrapper(GOOD_WRAPPER.replace(dropped, "")))
    assert any(dropped in e for e in check_dockerfile(GOOD_DOCKERFILE.replace(dropped, "")))


@pytest.mark.unit
def test_shipped_container_assets_valid():
    assert check_assets() == []


@pytest.fixture
def container_root(tmp_path):
    """Минимальный реальный build context; target нельзя импортировать валидатором."""
    target = tmp_path / "ai_ops_kit/engine/ai_ops_run.py"
    target.parent.mkdir(parents=True)
    target.write_text("raise RuntimeError('validator must not execute target')\n")
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "Dockerfile").write_text(GOOD_DOCKERFILE)
    (containers / "run-sandboxed.sh").write_text(GOOD_WRAPPER)
    (containers / "deliver-run-branches.sh").write_text("for-each-ref fetch ai-ops/*\n")
    return tmp_path


def test_existing_launch_target_is_checked_without_execution_or_writes(container_root):
    before = {p.relative_to(container_root): p.read_bytes()
              for p in container_root.rglob("*") if p.is_file()}
    assert check_assets(container_root) == []
    after = {p.relative_to(container_root): p.read_bytes()
             for p in container_root.rglob("*") if p.is_file()}
    assert after == before


def test_removed_launch_target_fails_despite_all_markers(container_root):
    target = container_root / "ai_ops_kit/engine/ai_ops_run.py"
    assert check_assets(container_root) == []
    target.unlink()
    assert not target.exists()  # реальная порча до реакции гейта
    errors = check_assets(container_root)
    assert any("ai_ops_kit/engine/ai_ops_run.py" in e for e in errors)


@pytest.mark.parametrize("entrypoint", [
    '["python3", "/opt/ai-ops-kit/tools/ai_ops_run.py"]',
    '["python3", "-m", "ai_ops_kit.engine.missing"]',
    'python3 -m ai_ops_kit.engine.ai_ops_run',
    '["python3", "-m",',
    '["python3", "-m", "ai_ops_kit.engine.ai_ops_run", "--help"]',
])
def test_invalid_launch_command_fails_closed(entrypoint):
    text = GOOD_DOCKERFILE.rsplit("ENTRYPOINT", 1)[0] + f"ENTRYPOINT {entrypoint}\n"
    assert any("ENTRYPOINT" in e for e in check_dockerfile(text))


def test_last_entrypoint_is_validated_not_a_comment_or_old_instruction():
    text = GOOD_DOCKERFILE + '# ENTRYPOINT ["python3", "-m", "ai_ops_kit.engine.ai_ops_run"]\n'
    assert check_dockerfile(text) == []
    text += 'ENTRYPOINT ["missing"]\n'
    assert any("ENTRYPOINT" in e for e in check_dockerfile(text))


@pytest.mark.parametrize("replacement", ["", "# ENV PYTHONPATH=/opt/ai-ops-kit", "ENV PYTHONPATH=/work"])
def test_missing_import_root_fails_closed(replacement):
    text = GOOD_DOCKERFILE.replace("ENV PYTHONPATH=/opt/ai-ops-kit", replacement)
    assert any("PYTHONPATH" in e for e in check_dockerfile(text))


def test_last_pythonpath_assignment_is_validated():
    text = GOOD_DOCKERFILE + 'ENV PYTHONPATH="/work"\n'
    assert any("PYTHONPATH" in e for e in check_dockerfile(text))


def test_multiline_instructions_are_supported():
    text = GOOD_DOCKERFILE.replace("ENV PYTHONPATH=/opt/ai-ops-kit",
                                  'ENV OTHER=value \\\n    PYTHONPATH="/opt/ai-ops-kit"')
    assert check_dockerfile(text) == []


def test_comment_does_not_copy_launch_source():
    text = GOOD_DOCKERFILE.replace("COPY . /opt/ai-ops-kit", "# COPY . /opt/ai-ops-kit")
    assert any("COPY" in e for e in check_dockerfile(text))


def test_new_build_stage_cannot_reuse_previous_launch_contract():
    text = GOOD_DOCKERFILE + 'FROM node:22-slim\nENTRYPOINT ["python3", "-m", "ai_ops_kit.engine.ai_ops_run"]\n'
    assert any("FROM" in e for e in check_dockerfile(text))


def test_commented_entrypoint_is_not_a_launch_command():
    text = GOOD_DOCKERFILE.replace("ENTRYPOINT", "# ENTRYPOINT")
    assert any("ENTRYPOINT" in e for e in check_dockerfile(text))


def test_static_success_does_not_claim_image_start(capsys):
    assert main([]) == 0
    assert "сборка/запуск образа и реальная изоляция НЕ проверены" in capsys.readouterr().out


def test_standalone_validator_returns_failure_for_deleted_target(container_root):
    (container_root / "VERSION").write_text("0.0.0\n")
    validator = container_root / "validate_container_assets.py"
    validator.write_bytes((PKG / "ai_ops_kit/validation/validate_container_assets.py").read_bytes())
    target = container_root / "ai_ops_kit/engine/ai_ops_run.py"
    target.unlink()
    assert not target.exists()
    env = {"PATH": os.defpath, "HOME": str(container_root), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(validator)], cwd=container_root, env=env,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert "ai_ops_kit/engine/ai_ops_run.py" in result.stdout
    assert "CONTAINER-ASSETS-OK" not in result.stdout


def test_launch_target_outside_build_context_fails_closed(container_root, tmp_path):
    target = container_root / "ai_ops_kit/engine/ai_ops_run.py"
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text("raise RuntimeError('outside build context')\n")
    target.unlink()
    target.symlink_to(outside)
    assert target.resolve() == outside
    assert any("ai_ops_kit/engine/ai_ops_run.py" in e for e in check_assets(container_root))


def test_shipped_launch_command_reaches_cli_from_work_directory(tmp_path):
    """Host smoke с тем же import root/argv, без модели; не runnable-image proof."""
    text = (PKG / "containers/Dockerfile").read_text()
    entry = next(line.removeprefix("ENTRYPOINT ") for line in text.splitlines()
                 if line.startswith("ENTRYPOINT "))
    command = json.loads(entry)
    assert command == ["python3", "-m", "ai_ops_kit.engine.ai_ops_run"]
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONPATH": str(PKG),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, *command[1:], "--help"], cwd=tmp_path,
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "run" in result.stdout and "resume" in result.stdout
    assert list(tmp_path.iterdir()) == []
