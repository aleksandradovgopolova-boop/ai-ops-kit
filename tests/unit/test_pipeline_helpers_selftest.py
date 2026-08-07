"""Селфтест pipeline_helpers, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from pipeline_helpers import (  # noqa: F401 — имена, которые использует тело
    NO_SELF_REVIEW,
    _intake_evidence,
    _parse_yaml_block,
    _profile_summary,
    _reviewable_gates,
)


@pytest.mark.slow
def test_pipeline_helpers_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("pipeline_helpers: imports work", True)
    expect("pipeline_helpers: _profile_summary is callable", callable(_profile_summary))
    expect("pipeline_helpers: _intake_evidence is callable", callable(_intake_evidence))
    expect("pipeline_helpers: _reviewable_gates is callable", callable(_reviewable_gates))
    expect("pipeline_helpers: _parse_yaml_block is callable", callable(_parse_yaml_block))
    expect("pipeline_helpers: NO_SELF_REVIEW contains security", "security" in NO_SELF_REVIEW)

    assert ok, "перенесённый селфтест pipeline_helpers: см. строки FAIL в выводе"
