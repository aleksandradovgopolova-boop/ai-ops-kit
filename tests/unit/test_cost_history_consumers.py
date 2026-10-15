"""Реальные исторические JSONL не обходят защиту финансовых потребителей (#1276)."""
import json

import pytest

from ai_ops_kit.engops.session_launcher import suggest_ceiling
from ai_ops_kit.gates.economic_preflight import estimate
from ai_ops_kit.intelligence.outcome_analytics import collect_analytics, format_report
from ai_ops_kit.shared import usage_ledger


def _record(cost, wid="w"):
    return {"workitem_id": wid, "cost": cost, "cost_status": "measured",
            "input_tokens": 1, "output_tokens": 1, "usage_status": "measured",
            "provider": "test", "model": "test"}


def _history(root, records):
    path = root / ".ai/usage/product-ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Воспроизведение уже существовавшего нестрогого формата, не новый writer.
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.1", 10**400])
def test_history_is_unknown_for_budget_and_partial_for_estimate_and_analytics(tmp_path, bad):
    _history(tmp_path, [_record(bad)] * 20)
    records = usage_ledger.load_product(tmp_path)
    assert len(records) == 20
    assert all(r["cost"] is None and r["cost_status"] == "unavailable" for r in records)
    json.dumps(records, allow_nan=False)
    ceiling = suggest_ceiling(tmp_path)
    assert ceiling["amount"] is None
    assert ceiling["basis"] == "no_measurement"
    est = estimate(records=[_record(1), _record(bad)])
    assert est["status"] == "estimated_lower_bound"
    assert est["cost_median"] == 1
    analytics = collect_analytics(tmp_path)
    assert analytics["summary"]["cost_complete"] is False
    assert analytics["cost_breakdown"]["measured_costs"] == 0
    assert "нижняя граница" in format_report(analytics)
    json.dumps(analytics, allow_nan=False)


def test_finite_history_cannot_overflow_budget_suggestion_or_estimate(tmp_path):
    _history(tmp_path, [_record(1e308, str(i)) for i in range(20)])
    assert suggest_ceiling(tmp_path)["amount"] is None
    est = estimate(tmp_path)
    assert est["status"] == "measured_history"
    assert est["cost_median"] == 1e308
    partial = estimate(records=[_record(1e308), _record(1e308)])
    assert partial["status"] == "estimated_lower_bound"
    assert partial["cost_median"] == 1e308
    json.dumps(partial, allow_nan=False)
    analytics = collect_analytics(tmp_path)
    assert analytics["summary"]["cost_complete"] is False
    assert analytics["cost_breakdown"]["cost_overflow"] is True
    json.dumps(analytics, allow_nan=False)


def test_analytics_retains_known_expense_and_unknown_attempt(tmp_path):
    _history(tmp_path, [_record(1), _record(float("nan"))])
    analytics = collect_analytics(tmp_path)
    assert analytics["summary"]["total_runs"] == 2
    assert analytics["summary"]["total_cost_usd"] == 1
    assert analytics["summary"]["cost_complete"] is False
    assert analytics["cost_breakdown"]["cost_unavailable"] == 1
    assert analytics["top_tasks_by_cost"][0]["cost_usd"] == 1
    assert analytics["top_tasks_by_cost"][0]["cost_complete"] is False
    json.dumps(analytics, allow_nan=False)


def test_analytics_standalone_cli_needs_no_pythonpath(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    _history(tmp_path, [_record(1), _record(float("nan"))])
    script = Path(__file__).resolve().parents[2] / "ai_ops_kit/intelligence/outcome_analytics.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run([sys.executable, str(script), str(tmp_path), "--json"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["cost_complete"] is False
    assert report["summary"]["total_cost_usd"] == 1
    json.dumps(report, allow_nan=False)
