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
