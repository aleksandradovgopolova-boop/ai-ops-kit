"""Гранулярные тесты validate_container_assets (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_container_assets import (  # noqa: F401
    check_assets,
    check_dockerfile,
    check_wrapper,
)


GOOD_DOCKERFILE = (
    "FROM node:22-slim\n"
    "RUN pyyaml openspec\n"
    "COPY . /opt/ai-ops-kit\n"
    "USER runner\n"
    "ENV GIT_ASKPASS=/bin/false GIT_TERMINAL_PROMPT=0 "
    'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=""\n'
    'ENTRYPOINT ["x"]\n'
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
