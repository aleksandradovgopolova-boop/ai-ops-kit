"""Селфтест validate_container_assets, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_container_assets import (  # noqa: F401 — имена, которые использует тело
    check_assets,
    check_dockerfile,
    check_wrapper,
)


@pytest.mark.slow
def test_validate_container_assets_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good_df = "FROM node:22-slim\nRUN pyyaml openspec\nCOPY . /opt/ai-ops-kit\nUSER runner\nENTRYPOINT [\"x\"]\n"
    expect("dockerfile: полный набор маркеров -> без ошибок", check_dockerfile(good_df) == [])
    expect("dockerfile: без USER runner -> ошибка (root запрещён)",
           any("USER runner" in e for e in check_dockerfile(good_df.replace("USER runner", "USER root"))))
    good_wr = ('git clone --no-hardlinks --local "$CHILD_ABS" "$CLONE"\n'
               "docker run --read-only --tmpfs /tmp --memory 2g --cpus 2 --pids-limit 512 "
               '--cap-drop ALL --security-opt no-new-privileges --mount type=bind,src=${CLONE},dst=/work img\n'
               '"$SCRIPT_DIR/deliver-run-branches.sh" "$CLONE" "$CHILD_ABS" "$SNAP_BEFORE"\n')
    expect("wrapper: полный набор jail-флагов + worktree-only -> без ошибок", check_wrapper(good_wr) == [])
    expect("wrapper: убрали --cap-drop -> ошибка",
           any("--cap-drop" in e for e in check_wrapper(good_wr.replace("--cap-drop ALL", ""))))
    expect("wrapper: убрали --read-only -> ошибка",
           any("--read-only" in e for e in check_wrapper(good_wr.replace("--read-only", ""))))
    # v2.93: регресс worktree-only — прямой монтаж основного child в /work запрещён
    bad_wr = good_wr.replace("src=${CLONE},dst=/work", "src=${CHILD_ABS},dst=/work")
    expect("wrapper: прямой монтаж основного child в /work -> ошибка (нарушает worktree-only)",
           any("worktree-only" in e for e in check_wrapper(bad_wr)))
    # поставляемые ассеты валидны
    expect("поставляемые containers/* содержат все гарантии jail'а", check_assets() == [])

    assert ok, "перенесённый селфтест validate_container_assets: см. строки FAIL в выводе"
