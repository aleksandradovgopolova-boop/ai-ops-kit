"""Селфтест session_telemetry_provider, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from session_telemetry_provider import (  # noqa: F401 — имена, которые использует тело
    check,
    read_session_metadata,
)


@pytest.mark.slow
def test_session_telemetry_provider_selftest():
    """Selftest: контракт + честность (None если нет данных)."""
    ok = True

    # 1. read_session_metadata без данных -> None (честно)
    result = read_session_metadata(session_id="nonexistent-session-12345")
    if result is None:
        print("PASS session_telemetry_provider: nonexistent session -> None (честно)")
    else:
        ok = False
        print("FAIL session_telemetry_provider: nonexistent session должен вернуть None")

    # 2. check(None) -> [] (валидация проходит)
    errors = check(None)
    if not errors:
        print("PASS session_telemetry_provider: check(None) -> [] (unavailable валиден)")
    else:
        ok = False
        print(f"FAIL session_telemetry_provider: check(None) должен вернуть [], got {errors}")

    # 3. check с валидными данными -> []
    valid_data = {
        "session_id": "test-session",
        "started_at": "2026-08-05T10:00:00Z",
        "message_count": 10,
        "input_tokens": 5000,
        "output_tokens": 2000,
    }
    errors = check(valid_data)
    if not errors:
        print("PASS session_telemetry_provider: check(valid) -> []")
    else:
        ok = False
        print(f"FAIL session_telemetry_provider: check(valid) должен вернуть [], got {errors}")

    # 4. check с невалидными данными -> errors
    invalid_data = {"message_count": -1}
    errors = check(invalid_data)
    if errors:
        print("PASS session_telemetry_provider: check(invalid) -> errors")
    else:
        ok = False
        print("FAIL session_telemetry_provider: check(invalid) должен вернуть errors")

    assert ok, "перенесённый селфтест session_telemetry_provider: см. строки FAIL в выводе"
