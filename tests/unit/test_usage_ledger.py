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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.1", 10**400])
def test_invalid_cost_survives_as_unknown_call_not_invalid_json(tmp_path, good_record, bad):
    import json

    assert check({**good_record, "cost": bad})
    raw = {**good_record, "cost": None, "cost_usd_est": bad}
    assert append(tmp_path, "invalid", [raw, good_record]) == 2
    for records in (load_task(tmp_path, "invalid"), load_product(tmp_path)):
        assert len(records) == 2
        assert records[0]["cost"] is None
        assert records[0]["cost_status"] == "unavailable"
        json.dumps(records, allow_nan=False)
        agg = aggregate(records)
        assert agg["calls"] == 2
        assert agg["cost"] == pytest.approx(0.07)
        assert agg["cost_unavailable"] == 1
        assert agg["cost_complete"] is False
        json.dumps(agg, allow_nan=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.1", None])
def test_old_malformed_ledger_does_not_become_complete(good_record, bad):
    import json

    agg = aggregate([{**good_record, "cost": bad}, good_record])
    assert agg["cost"] == pytest.approx(0.07)
    assert agg["cost_complete"] is False
    assert agg["cost_unavailable"] == 1
    json.dumps(agg, allow_nan=False)


def test_overflow_is_finite_lower_bound_not_complete(good_record):
    import json

    agg = aggregate([{**good_record, "cost": 1e308}] * 2)
    assert agg["calls"] == 2
    assert agg["cost"] == 1e308
    assert agg["cost_overflow"] is True
    assert agg["cost_complete"] is False
    json.dumps(agg, allow_nan=False)


def test_measured_missing_cost_is_normalized_unavailable(tmp_path, good_record):
    append(tmp_path, "missing", [{**good_record, "cost": None}])
    record = load_task(tmp_path, "missing")[0]
    assert record["cost"] is None
    assert record["cost_status"] == "unavailable"
    assert aggregate([record])["cost_complete"] is False


@pytest.mark.parametrize("prices", [[1e308, 1], [1, 1e308]])
def test_absorbed_positive_expense_is_incomplete_lower_bound(good_record, prices):
    result = aggregate([{**good_record, "cost": price} for price in prices])
    assert result["calls"] == 2
    assert result["cost"] == 1e308
    assert result["cost_precision_lost"] is True
    assert result["cost_complete"] is False


def test_unrepresentable_integer_cost_is_unknown(good_record):
    from ai_ops_kit.shared.usage_ledger import normalize

    result = normalize({**good_record, "cost": 2**53 + 1})
    assert result["cost"] is None
    assert result["cost_status"] == "unavailable"
