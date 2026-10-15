"""Гранулярные тесты cost_account (мигрировано из test_cost_account_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.providers.cost_account import (
    PKG,
    compare_configs,
    cost_per_successful_change,
    reconcile,
    yaml,
)


@pytest.fixture
def run_budget():
    return yaml.safe_load((PKG / "examples" / "budget-demo" / "BUD-002.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def loop_budget():
    return yaml.safe_load((PKG / "examples" / "budget-demo" / "BUD-001.yaml").read_text(encoding="utf-8"))


@pytest.mark.unit
class TestReconcile:
    def test_within_budget(self, run_budget):
        r = reconcile(run_budget, {"calls": 20, "cost_usd_est": 0.5})
        assert r["verdict"] == "within_budget"
        assert r["dimensions"]["max_model_calls"]["remaining"] == 20

    def test_spent_equals_limit_exhausted(self, run_budget):
        r = reconcile(run_budget, {"calls": 40, "cost_usd_est": 0.5})
        assert r["verdict"] == "exhausted"
        assert r["dimensions"]["max_model_calls"]["exhausted"] is True

    def test_spent_over_limit(self, run_budget):
        r = reconcile(run_budget, {"calls": 45, "cost_usd_est": 0.5})
        assert r["verdict"] == "over"
        assert r["dimensions"]["max_model_calls"]["over"] is True

    def test_cost_over_limit(self, run_budget):
        r = reconcile(run_budget, {"calls": 20, "cost_usd_est": 1.5})
        assert r["verdict"] == "over"
        assert r["dimensions"]["max_cost_usd"]["over"] is True

    def test_unmeasured_cost_not_over(self, run_budget):
        r = reconcile(run_budget, {"calls": 20, "cost_usd_est": None})
        assert r["dimensions"]["max_cost_usd"]["measured"] is False
        assert r["verdict"] == "within_budget"

    def test_loop_tokens_input_plus_output(self, loop_budget):
        r = reconcile(loop_budget, {"input_tokens": 150000, "output_tokens": 60000}, iterations=1)
        assert r["dimensions"]["max_tokens"]["spent"] == 210000
        assert r["verdict"] == "over"

    def test_iterations_checked(self, loop_budget):
        r = reconcile(loop_budget, {"input_tokens": 100000, "output_tokens": 50000}, iterations=1)
        assert r["dimensions"]["max_iterations"]["spent"] == 1
        assert r["dimensions"]["max_iterations"]["exhausted"] is True

    def test_null_limits_not_in_dimensions(self, run_budget):
        r = reconcile(run_budget, {"calls": 5})
        assert "max_tokens" not in r["dimensions"]
        assert "max_wall_seconds" not in r["dimensions"]


@pytest.mark.unit
class TestCostPerSuccessfulChange:
    def test_sum_of_all_costs(self):
        kimi = cost_per_successful_change({
            "calls_cost": 0.30, "retry_cost": 0.60, "reviewer_cost": 0.20,
            "escalation_cost": 0.90, "manual_interventions": 1, "delivered_verified": True})
        assert kimi["cost_per_change"] == 2.0

    def test_strong_config_cost(self):
        strong = cost_per_successful_change({
            "calls_cost": 1.20, "reviewer_cost": 0.30, "delivered_verified": True})
        assert strong["cost_per_change"] == 1.5

    def test_not_delivered_is_none(self):
        fail = cost_per_successful_change({"calls_cost": 0.30, "delivered_verified": False})
        assert fail["cost_per_change"] is None


@pytest.mark.unit
class TestCompareConfigs:
    def test_strongest_cheaper_on_success(self):
        cmp = compare_configs([
            {"name": "economical-kimi", "attempt": {"calls_cost": 0.30, "retry_cost": 0.60,
             "escalation_cost": 0.90, "reviewer_cost": 0.20, "delivered_verified": True}},
            {"name": "reference-strong", "attempt": {"calls_cost": 1.20, "reviewer_cost": 0.30,
             "delivered_verified": True}},
            {"name": "cheap-but-failed", "attempt": {"calls_cost": 0.10, "delivered_verified": False}}])
        assert cmp["cheapest_qualified"] == "reference-strong"

    def test_failed_excluded(self):
        cmp = compare_configs([
            {"name": "economical-kimi", "attempt": {"calls_cost": 0.30, "retry_cost": 0.60,
             "escalation_cost": 0.90, "reviewer_cost": 0.20, "delivered_verified": True}},
            {"name": "reference-strong", "attempt": {"calls_cost": 1.20, "reviewer_cost": 0.30,
             "delivered_verified": True}},
            {"name": "cheap-but-failed", "attempt": {"calls_cost": 0.10, "delivered_verified": False}}])
        assert "cheap-but-failed" in cmp["excluded_no_verified_change"]


@pytest.mark.unit
@pytest.mark.parametrize("attempt", [{}, {"calls_cost": None}, {"calls_cost": 1, "retry_cost": None}])
def test_unknown_change_price_is_unavailable(attempt):
    result = cost_per_successful_change({**attempt, "delivered_verified": True})
    assert result["total_cost"] is None
    assert result["cost_per_change"] is None


@pytest.mark.unit
def test_unknown_price_cannot_win_configuration_ranking():
    result = compare_configs([
        {"name": "unknown", "attempt": {"calls_cost": None, "delivered_verified": True}},
        {"name": "known", "attempt": {"calls_cost": 1, "delivered_verified": True}}])
    assert result["cheapest_qualified"] == "known"
    assert [row["name"] for row in result["ranking"]] == ["known"]
    assert result["excluded_unknown_cost"] == ["unknown"]


@pytest.mark.unit
class TestEconomicInputsFailClosed:
    @pytest.mark.parametrize("delivered", ["false", "true", "unknown", 1, 0, None, []])
    def test_only_true_boolean_is_verified_delivery(self, delivered):
        from ai_ops_kit.providers.cost_account import cost_per_successful_outcome
        attempt = {"calls_cost": 1.0, "delivered_verified": delivered, "manual_interventions": 0}
        change = cost_per_successful_change(attempt)
        outcome = cost_per_successful_outcome(attempt, human_attention_cost_usd=0)
        assert change["total_cost"] == 1.0
        assert change["delivered_verified"] is False
        assert change["cost_per_change"] is None
        assert outcome["cost_per_outcome"] is None

    def test_true_boolean_and_finite_cost_remain_measured(self):
        from ai_ops_kit.providers.cost_account import estimate_vs_actual
        assert cost_per_successful_change({"calls_cost": 2.0, "delivered_verified": True})["cost_per_change"] == 2.0
        result = estimate_vs_actual({"estimate_status": "estimated", "cost_median": 1.0}, 2.0)
        assert result["status"] == "measured" and result["delta_usd"] == 1.0

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1.0])
    def test_invalid_actual_cost_is_not_measured(self, value):
        from ai_ops_kit.providers.cost_account import estimate_vs_actual
        result = estimate_vs_actual({"estimate_status": "estimated", "cost_median": 1.0}, value)
        assert result["status"] == "unavailable"
        assert result["actual_usd"] is None and result["delta_usd"] is None

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
    def test_invalid_estimate_is_not_measured(self, value):
        from ai_ops_kit.providers.cost_account import estimate_vs_actual
        result = estimate_vs_actual({"estimate_status": "estimated", "cost_median": value}, 1.0)
        assert result["status"] == "unavailable"
        assert result["estimate_usd"] is None

    @pytest.mark.parametrize("rate", [float("nan"), float("inf"), -1.0])
    def test_invalid_human_rate_is_unavailable(self, rate):
        from ai_ops_kit.providers.cost_account import cost_per_successful_outcome
        result = cost_per_successful_outcome({"calls_cost": 1.0, "delivered_verified": True,
                                              "manual_interventions": 0}, human_attention_cost_usd=rate)
        assert result["human_attention_cost"] is None
        assert result["complete"] is False

    def test_report_file_keeps_failed_cost_without_accepted_price(self, tmp_path):
        import json
        from ai_ops_kit.providers.cost_account import estimate_vs_actual, roid_outcome_report
        report = {"outcome": roid_outcome_report(1.0, 2.0, 0, "false", root=tmp_path),
                  "comparison": estimate_vs_actual({"estimate_status": "estimated", "cost_median": 1.0}, float("nan"))}
        target = tmp_path / "economic-report.json"
        target.write_text(json.dumps(report, allow_nan=False))
        written = json.loads(target.read_text())
        assert written["outcome"]["ai_cost"] == 1.0
        assert written["outcome"]["cost_per_successful_outcome"] is None
        assert written["comparison"]["status"] == "unavailable"


@pytest.mark.unit
class TestCostOverflowIsUnknown:
    def test_finite_components_cannot_produce_infinite_total(self):
        result = cost_per_successful_change({"calls_cost": 1e308, "retry_cost": 1e308, "delivered_verified": True})
        assert result["total_cost"] is None
        assert result["cost_per_change"] is None

    def test_finite_rate_overflow_is_not_complete(self):
        from ai_ops_kit.providers.cost_account import cost_per_successful_outcome
        result = cost_per_successful_outcome({"calls_cost": 1.0, "manual_interventions": 10,
            "delivered_verified": True}, human_attention_cost_usd=1e308)
        assert result["human_attention_cost"] is None
        assert result["complete"] is False
        assert result["loaded_cost"] == 1.0

    def test_huge_integer_and_overflow_percentage_remain_serializable(self):
        import json
        from ai_ops_kit.providers.cost_account import estimate_vs_actual
        huge = cost_per_successful_change({"calls_cost": 10**400, "delivered_verified": True})
        result = estimate_vs_actual({"estimate_status": "estimated", "cost_median": 1e-308}, 1e308)
        assert huge["total_cost"] is None
        assert result["delta_pct"] is None
        json.dumps({"change": huge, "comparison": result}, allow_nan=False)
