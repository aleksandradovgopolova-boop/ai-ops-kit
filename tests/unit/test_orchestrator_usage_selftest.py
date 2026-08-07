"""Селфтест orchestrator_usage, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

import orchestrator_usage

from orchestrator_usage import (  # noqa: F401 — имена, которые использует тело
    _record_call,
    clear_call_context,
    drain_call_stats,
    set_call_context,
)


@pytest.mark.slow
def test_orchestrator_usage_selftest():
    ok = True
    # _record_call + drain_call_stats: записали -> дренировали -> очистилось
    orchestrator_usage._CALL_STATS.clear()
    orchestrator_usage._CALL_CONTEXT.clear()
    _record_call("test-model", 100, 50, 1.234, provider="test")
    if len(orchestrator_usage._CALL_STATS) == 1 and orchestrator_usage._CALL_STATS[0]["model"] == "test-model":
        print("PASS usage: _record_call записывает в orchestrator_usage._CALL_STATS")
    else:
        ok = False; print("FAIL usage: _record_call не записал")
    stats = drain_call_stats()
    if len(stats) == 1 and len(orchestrator_usage._CALL_STATS) == 0:
        print("PASS usage: drain_call_stats забирает и очищает")
    else:
        ok = False; print("FAIL usage: drain не сработал")
    # set_call_context / clear_call_context
    set_call_context(role="writer", trigger="initial")
    _record_call("m", 10, 20, 0.5)
    rec = orchestrator_usage._CALL_STATS[-1]
    if rec.get("role") == "writer" and rec.get("trigger") == "initial":
        print("PASS usage: set_call_context вмерживается в запись")
    else:
        ok = False; print("FAIL usage: контекст не вмержился")
    clear_call_context()
    _record_call("m2", 1, 2, 0.1)
    if "role" not in orchestrator_usage._CALL_STATS[-1]:
        print("PASS usage: clear_call_context очищает контекст")
    else:
        ok = False; print("FAIL usage: контекст не очистился")
    orchestrator_usage._CALL_STATS.clear()
    orchestrator_usage._CALL_CONTEXT.clear()

    assert ok, "перенесённый селфтест orchestrator_usage: см. строки FAIL в выводе"
