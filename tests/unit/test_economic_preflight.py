"""Гранулярные тесты economic_preflight (мигрировано из test_economic_preflight_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from economic_preflight import (
    ESTIMATE_STATUS,
    Path,
    VERDICTS,
    _fmt,
    _rec,
    assess,
    check_economics,
    estimate,
    policy_from_config,
    summary_line,
)


def _rules(v, key="violations"):
    return {x["rule"] for x in v[key]}


@pytest.fixture
def measured_estimate():
    return estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", 0.5), _rec("WI-2", 3.0),
                             _rec("WI-3", 2.0)])


@pytest.mark.unit
class TestEstimateHonesty:
    def test_no_history_unavailable(self):
        e = estimate(records=[])
        assert e["status"] == "unavailable" and e["cost_median"] is None and e["cost_max"] is None

    def test_no_history_does_not_block(self):
        e = estimate(records=[])
        v = check_economics(e)
        assert v["allowed"] and v["verdict"] == "proceed_unknown"

    def test_require_estimate_blocks_no_history(self):
        e = estimate(records=[])
        assert check_economics(e, policy={"require_estimate": True})["verdict"] == "block"

    def test_measured_history_status(self, measured_estimate):
        assert measured_estimate["status"] == "measured_history"

    def test_median_max_by_tasks(self, measured_estimate):
        assert measured_estimate["sample_tasks"] == 3
        assert measured_estimate["cost_median"] == 2.0
        assert measured_estimate["cost_max"] == 3.0

    def test_calls_aggregated_by_tasks(self, measured_estimate):
        assert measured_estimate["calls_max"] == 2
        assert measured_estimate["calls_median"] == 1

    def test_sample_3_medium_confidence(self, measured_estimate):
        assert measured_estimate["confidence"] == "medium"

    def test_small_sample_low_confidence(self):
        assert estimate(records=[_rec("WI-1", 1.0)])["confidence"] == "low"


@pytest.mark.unit
class TestEstimatePartial:
    def test_unknown_cost_not_zero(self):
        e = estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", None, "unavailable")])
        assert e["status"] == "estimated_lower_bound"

    def test_lower_bound_labelled(self):
        e = estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", None, "unavailable")])
        assert "НИЖНЯЯ ГРАНИЦА" in e["note"] and "может НЕ сработать" in e["note"]

    def test_lower_bound_advisory(self):
        e = estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", None, "unavailable")])
        v = check_economics(e, {"max_cost": 100})
        assert "lower_bound_only" in _rules(v, "advisories")

    def test_completed_takes_priority(self):
        e = estimate(records=[_rec("WI-1", 1.0), _rec("WI-2", None, "unavailable")])
        assert e["status"] == "measured_history"


@pytest.mark.unit
class TestVerdictAgainstLimits:
    def test_within_limits_proceed(self, measured_estimate):
        v = check_economics(measured_estimate, {"max_cost": 10, "max_model_calls": 50})
        assert v["verdict"] == "proceed" and v["allowed"]

    def test_worst_exceeds_cost_block(self, measured_estimate):
        v = check_economics(measured_estimate, {"max_cost": 2.5})
        assert v["verdict"] == "block" and not v["allowed"]
        assert "cost_limit_exceeded" in _rules(v)

    def test_block_explains_interruption(self, measured_estimate):
        v = check_economics(measured_estimate, {"max_cost": 2.5})
        assert any("прервана посередине" in x["detail"] for x in v["violations"])

    def test_decision_by_worst_not_median(self, measured_estimate):
        assert measured_estimate["cost_median"] < 2.5 < measured_estimate["cost_max"]

    def test_calls_limit_exceeded(self, measured_estimate):
        v = check_economics(measured_estimate, {"max_model_calls": 1})
        assert "calls_limit_exceeded" in _rules(v) and v["verdict"] == "block"

    def test_confirm_required_not_block(self, measured_estimate):
        v = check_economics(measured_estimate, {"max_cost": 10}, {"confirm_over_cost_usd": 1})
        assert v["verdict"] == "confirm_required" and v["allowed"]
        assert "confirm_recommended" in _rules(v, "advisories")

    def test_enforce_block_escalates_confirm(self, measured_estimate):
        assert not check_economics(measured_estimate, {"max_cost": 10},
                                   {"confirm_over_cost_usd": 1, "enforce": "block"})["allowed"]

    def test_none_confirm_threshold_no_confirm(self, measured_estimate):
        assert check_economics(measured_estimate, {"max_cost": 10},
                               {"confirm_over_cost_usd": None})["verdict"] == "proceed"

    def test_no_limits_no_block(self, measured_estimate):
        v = check_economics(measured_estimate)
        assert v["verdict"] in ("proceed", "confirm_required")
        assert v["limits"] == {"max_cost": None, "max_model_calls": None, "max_duration": None}

    def test_low_confidence_advisory(self):
        e = estimate(records=[_rec("WI-1", 1.0)])
        v = check_economics(e, {"max_cost": 10})
        assert "low_confidence" in _rules(v, "advisories")


@pytest.mark.unit
class TestConfigAndSurface:
    def test_no_config_defaults(self, tmp_path):
        assert policy_from_config(tmp_path) == {}

    def test_config_read(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  economics:\n    enforce: block\n"
            "    confirm_over_cost_usd: 1\n    require_estimate: true\n", encoding="utf-8")
        p = policy_from_config(tmp_path)
        assert p.get("enforce") == "block" and p.get("require_estimate") is True

    def test_malformed_config_does_not_crash(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        assert policy_from_config(tmp_path) == {}

    def test_assess_no_ledger_unavailable(self, tmp_path):
        est, v = assess(tmp_path)
        assert est["status"] == "unavailable" and v["allowed"]

    def test_summary_unavailable_not_zero(self, tmp_path):
        assert "unavailable" in summary_line(tmp_path) and "не ноль" in summary_line(tmp_path)

    def test_fmt_prints_verdict(self, tmp_path):
        est, v = assess(tmp_path)
        assert "экономика ДО прогона" in _fmt(est, v)

    def test_statuses_and_verdicts_declared(self):
        assert ESTIMATE_STATUS == ("measured_history", "estimated_lower_bound", "unavailable")
        assert VERDICTS == ("proceed", "proceed_unknown", "confirm_required", "block")
