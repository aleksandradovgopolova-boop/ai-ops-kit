"""Гранулярные тесты session_telemetry (мигрировано из test_session_telemetry_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from session_telemetry import (
    check,
    snapshot,
    usage_ledger,
)


@pytest.fixture(autouse=True)
def _isolate_runtime(monkeypatch, tmp_path):
    """Изоляция от рантайма разработчика (ENV + HOME)."""
    from ai_ops_kit.engops import session_telemetry_provider as _p
    for key in (*_p.ENV_SESSION_ID_KEYS, *_p.ENV_PROJECT_DIR_KEYS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "no-runtime-home"))


@pytest.fixture
def ledger_dir(tmp_path):
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def sample_records():
    return [
        {"run_id": "r", "workitem_id": "WI-1", "role": "implementation", "provider": "claude-cli",
         "model": "m", "runtime": "claude-cli", "input_tokens": 120000, "output_tokens": 4000,
         "usage_status": "measured", "cost": 1.5, "cost_status": "measured", "trigger": "initial"},
        {"run_id": "r", "workitem_id": "WI-1", "role": "code_review", "provider": "deepseek",
         "model": "d", "runtime": "api", "input_tokens": 260000, "output_tokens": 2000,
         "usage_status": "measured", "cost": 0.02, "cost_status": "estimated", "trigger": "review"},
        {"run_id": "r", "workitem_id": "WI-1", "role": "author", "provider": "x", "model": "y",
         "runtime": "api", "input_tokens": None, "output_tokens": None,
         "usage_status": "unavailable", "cost": None, "cost_status": "unavailable", "trigger": "initial"},
    ]


@pytest.mark.unit
class TestSnapshotEmpty:
    def test_empty_product_returns_unavailable(self, ledger_dir):
        s = snapshot(ledger_dir)
        assert s["turns"] == 0
        assert s["context_status"] == "unavailable"
        assert s["context_current"] is None

    def test_check_valid_on_empty(self, ledger_dir):
        s = snapshot(ledger_dir)
        assert check(s) == []


@pytest.mark.unit
class TestSnapshotWithLedger:
    def test_context_current_estimated(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["context_current"] == 260000
        assert s["context_status"] == "estimated"

    def test_context_peak(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["context_peak"] == 260000

    def test_turns_count(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["turns"] == 3

    def test_unavailable_does_not_sink_token_sums(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["input_tokens"] == 380000

    def test_cost_incomplete_when_unavailable(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["cost_complete"] is False

    def test_usage_status_partial(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["usage_status"] == "partial"

    def test_usage_unavailable_calls(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["usage_unavailable_calls"] == 1

    def test_cache_unavailable_is_none(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s = snapshot(ledger_dir, workitem_id="WI-1")
        assert s["cache_read_tokens"] is None
        assert s["cache_status"] == "unavailable"


@pytest.mark.unit
class TestSnapshotRuntimeContext:
    def test_runtime_context_overrides_estimated(self, ledger_dir, sample_records):
        usage_ledger.append(ledger_dir, "WI-1", sample_records, run_id="r")
        s2 = snapshot(ledger_dir, workitem_id="WI-1", context_current=95000)
        assert s2["context_current"] == 95000
        assert s2["context_status"] == "measured"
