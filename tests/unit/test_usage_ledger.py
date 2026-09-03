"""Гранулярные тесты usage_ledger (мигрировано из test_usage_ledger_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.shared.usage_ledger import (
    aggregate,
    append,
    check,
    load_product,
    load_task,
)


@pytest.fixture
def good_record():
    return {
        "run_id": "r1", "workitem_id": "w1", "role": "implementation", "provider": "claude-cli",
        "model": "claude-code-local", "input_tokens": 100, "output_tokens": 50,
        "usage_status": "measured", "cost": 0.07, "cost_status": "measured", "trigger": "initial",
    }


@pytest.mark.unit
class TestCheck:
    def test_valid_measured_no_errors(self, good_record):
        assert check(good_record) == []

    def test_unavailable_with_tokens_error(self, good_record):
        errors = check({**good_record, "usage_status": "unavailable"})
        assert any("unavailable" in x for x in errors)

    def test_unavailable_with_none_tokens_ok(self, good_record):
        result = check({**good_record, "usage_status": "unavailable", "input_tokens": None,
                        "output_tokens": None, "cost": None, "cost_status": "unavailable"})
        assert result == []

    def test_measured_without_tokens_error(self, good_record):
        errors = check({**good_record, "input_tokens": None, "output_tokens": None})
        assert any("нечего измерять" in x for x in errors)

    def test_zero_input_tokens_valid(self, good_record):
        assert check({**good_record, "input_tokens": 0, "output_tokens": 1}) == []

    def test_unknown_trigger_error(self, good_record):
        errors = check({**good_record, "trigger": "bogus"})
        assert any("trigger" in x for x in errors)


@pytest.mark.unit
class TestAggregate:
    @pytest.fixture
    def mixed_records(self, good_record):
        return [
            good_record,
            {**good_record, "role": "code_review", "provider": "deepseek", "trigger": "review",
             "cost": 0.001, "cost_status": "estimated"},
            {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None, "cost": None,
             "cost_status": "unavailable", "role": "implementation", "provider": "kimi", "trigger": "escalation"},
        ]

    def test_calls_count(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["calls"] == 3
        assert a["usage_measured"] == 2
        assert a["usage_unavailable"] == 1

    def test_tokens_only_measured(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["input_tokens"] == 200
        assert a["output_tokens"] == 100

    def test_cost_incomplete(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["cost_complete"] is False

    def test_by_role_and_trigger(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["by_role"]["implementation"] == 2
        assert a["by_trigger"]["review"] == 1


@pytest.mark.unit
class TestRoundTrip:
    @pytest.fixture
    def ledger_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield td

    @pytest.fixture
    def records(self, good_record):
        return [
            good_record,
            {**good_record, "role": "code_review", "provider": "deepseek", "trigger": "review",
             "cost": 0.001, "cost_status": "estimated"},
            {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None, "cost": None,
             "cost_status": "unavailable", "role": "implementation", "provider": "kimi", "trigger": "escalation"},
        ]

    def test_append_writes_three(self, ledger_dir, records):
        n = append(ledger_dir, "w1", records, run_id="r1")
        assert n == 3

    def test_load_task_reads_three(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert len(load_task(ledger_dir, "w1")) == 3

    def test_load_product_reads_three(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert len(load_product(ledger_dir)) == 3

    def test_normalization_includes_run_id(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert load_task(ledger_dir, "w1")[0].get("run_id") == "r1"
