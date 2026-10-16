"""Гранулярные тесты orchestrator_usage (мигрировано из test_orchestrator_usage_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import concurrent.futures
import threading

import pytest

from ai_ops_kit.providers import orchestrator_usage

from ai_ops_kit.providers.orchestrator_usage import (
    _record_call,
    clear_call_context,
    drain_call_stats,
    set_call_context,
)
from ai_ops_kit.shared import usage_ledger


@pytest.mark.parametrize("fail_first", [False, True])
def test_parallel_context_and_drain_persist_only_own_calls(tmp_path, fail_first):
    """Два потока реально пишут свои task/product ledgers после принудительного interleave."""
    a_context, b_recorded, a_drained = (threading.Event() for _ in range(3))
    set_call_context(workitem_id="main", run_id="main-run")
    _record_call("controlled-unpriced", 99, 9, 0.5)

    def worker(wid, tokens):
        set_call_context(workitem_id=wid, run_id=f"{wid}-run", role="writer")
        outcome = "completed"
        try:
            if wid == "a":
                a_context.set()
                assert b_recorded.wait(5)
            else:
                assert a_context.wait(5)
            _record_call("controlled-unpriced", tokens, 1, 0.25)
            if wid == "b":
                b_recorded.set()
                assert a_drained.wait(5)
            if wid == "a" and fail_first:
                raise RuntimeError("controlled failure after measured call")
        except RuntimeError:
            outcome = "failed"
        finally:
            count = usage_ledger.append(tmp_path / wid, wid, drain_call_stats())
            clear_call_context()
            if wid == "a":
                a_drained.set()
        return outcome, count

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a_future = pool.submit(worker, "a", 11)
        assert a_context.wait(5)
        b_future = pool.submit(worker, "b", 22)
        assert a_future.result(timeout=10) == ("failed" if fail_first else "completed", 1)
        assert b_future.result(timeout=10) == ("completed", 1)
    for wid, tokens in (("a", 11), ("b", 22)):
        task_rows = usage_ledger.load_task(tmp_path / wid, wid)
        assert len(task_rows) == 1
        assert task_rows == usage_ledger.load_product(tmp_path / wid)
        assert task_rows[0]["workitem_id"] == wid
        assert task_rows[0]["run_id"] == f"{wid}-run"
        assert task_rows[0]["input_tokens"] == tokens
        assert task_rows[0]["cost"] is None
    assert [row["workitem_id"] for row in drain_call_stats()] == ["main"]


def test_reused_worker_has_no_previous_calls_and_main_facade_stays_live():
    from ai_ops_kit.providers import orchestrator

    def worker(wid):
        set_call_context(workitem_id=wid)
        _record_call("controlled-unpriced", 1, 1, 0)
        rows = drain_call_stats()
        clear_call_context()
        return threading.get_ident(), rows

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        thread_a, a = pool.submit(worker, "a").result(timeout=5)
        thread_b, b = pool.submit(worker, "b").result(timeout=5)
    assert thread_a == thread_b
    assert [r["workitem_id"] for r in a] == ["a"]
    assert [r["workitem_id"] for r in b] == ["b"]
    assert drain_call_stats() == []
    for _ in range(2):
        _record_call("main-sequential", 1, 1, 0)
        assert len(orchestrator._CALL_STATS) == 1
        assert len(orchestrator.drain_call_stats()) == 1
        assert orchestrator._CALL_STATS == []


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
