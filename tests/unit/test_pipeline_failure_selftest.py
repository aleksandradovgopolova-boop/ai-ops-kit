"""Селфтест pipeline_failure, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from pipeline_failure import (  # noqa: F401 — имена, которые использует тело
    _diff_checks,
    _env_proven_ok,
    _failure_ids,
    _failure_signal,
    _security_verdict_errors,
)


@pytest.mark.slow
def test_pipeline_failure_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("pipeline_failure: imports work", True)
    expect("pipeline_failure: _diff_checks is callable", callable(_diff_checks))
    expect("pipeline_failure: _failure_signal is callable", callable(_failure_signal))
    expect("pipeline_failure: _failure_ids is callable", callable(_failure_ids))
    expect("pipeline_failure: _env_proven_ok is callable", callable(_env_proven_ok))
    expect("pipeline_failure: _security_verdict_errors is callable", callable(_security_verdict_errors))

    assert ok, "перенесённый селфтест pipeline_failure: см. строки FAIL в выводе"
