"""Селфтест validate_container_delivery, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_container_delivery import (  # noqa: F401 — имена, которые использует тело
    main,
)


@pytest.mark.slow
def test_validate_container_delivery_selftest():
    assert main([]) == 0, "перенесённый селфтест validate_container_delivery: см. строки FAIL в выводе"
