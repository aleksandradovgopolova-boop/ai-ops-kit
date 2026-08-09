"""Селфтест validate_stack_qualification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_stack_qualification import (  # noqa: F401 — имена, которые использует тело
    main,
)


@pytest.mark.slow
def test_validate_stack_qualification_selftest():
    return main([])

    assert ok, "перенесённый селфтест validate_stack_qualification: см. строки FAIL в выводе"
