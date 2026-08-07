"""Селфтест pipeline_git, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from pipeline_git import (  # noqa: F401 — имена, которые использует тело
    _git,
    _has_changes,
    _resolve_base,
    _tree_clean,
)


@pytest.mark.slow
def test_pipeline_git_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("pipeline_git: imports work", True)
    expect("pipeline_git: _git is callable", callable(_git))
    expect("pipeline_git: _has_changes is callable", callable(_has_changes))
    expect("pipeline_git: _tree_clean is callable", callable(_tree_clean))
    expect("pipeline_git: _resolve_base is callable", callable(_resolve_base))

    assert ok, "перенесённый селфтест pipeline_git: см. строки FAIL в выводе"
