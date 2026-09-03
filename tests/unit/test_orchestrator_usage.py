"""Гранулярные тесты orchestrator_usage (мигрировано из test_orchestrator_usage_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.providers import orchestrator_usage

from ai_ops_kit.providers.orchestrator_usage import (
    _record_call,
    clear_call_context,
    drain_call_stats,
    set_call_context,
)


@pytest.fixture(autouse=True)
def clean_state():
    orchestrator_usage._CALL_STATS.clear()
    orchestrator_usage._CALL_CONTEXT.clear()
    yield
    orchestrator_usage._CALL_STATS.clear()
    orchestrator_usage._CALL_CONTEXT.clear()


@pytest.mark.unit
class TestRecordCall:
    def test_record_call_writes_to_stats(self):
        _record_call("test-model", 100, 50, 1.234, provider="test")
        assert len(orchestrator_usage._CALL_STATS) == 1
        assert orchestrator_usage._CALL_STATS[0]["model"] == "test-model"


@pytest.mark.unit
class TestDrainCallStats:
    def test_drain_takes_and_clears(self):
        _record_call("test-model", 100, 50, 1.234, provider="test")
        stats = drain_call_stats()
        assert len(stats) == 1
        assert len(orchestrator_usage._CALL_STATS) == 0


@pytest.mark.unit
class TestCallContext:
    def test_set_context_merged_into_record(self):
        set_call_context(role="writer", trigger="initial")
        _record_call("m", 10, 20, 0.5)
        rec = orchestrator_usage._CALL_STATS[-1]
        assert rec.get("role") == "writer"
        assert rec.get("trigger") == "initial"

    def test_clear_context_removes_it(self):
        set_call_context(role="writer", trigger="initial")
        clear_call_context()
        _record_call("m2", 1, 2, 0.1)
        assert "role" not in orchestrator_usage._CALL_STATS[-1]
