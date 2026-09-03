"""Гранулярные тесты evolution_triggers (мигрировано из test_evolution_triggers_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.intelligence.evolution_triggers import (
    reg,
    triggers,
)


def _adr(aid, qas):
    return {"id": aid, "status": "accepted", "quality_attributes": qas}


def _hr(metrics, band="warning"):
    return {"scope": "s", "period": "p", "health_score": {"band": band},
            "metrics": {k: {"normalized": v} for k, v in metrics.items()}}


@pytest.fixture
def adrs():
    return {
        "ADR-A": _adr("ADR-A", [{"attribute": "reliability", "effect": "improves"}]),
        "ADR-B": _adr("ADR-B", [{"attribute": "performance", "effect": "tradeoff"}]),
        "ADR-OLD": {"id": "ADR-OLD", "status": "superseded",
                    "quality_attributes": [{"attribute": "reliability", "effect": "improves"}]},
    }


@pytest.mark.unit
class TestPromiseBroken:
    def test_degradation_of_improves_attribute(self, adrs):
        t = triggers(adrs, _hr({"reliability": 0.5, "performance": 0.9}))
        assert any(x["kind"] == "promise_broken" and x["adrs"] == ["ADR-A"] for x in t)

    def test_no_cost_realized_when_healthy(self, adrs):
        t = triggers(adrs, _hr({"reliability": 0.5, "performance": 0.9}))
        assert not any(x["kind"] == "cost_realized" for x in t)


@pytest.mark.unit
class TestCostRealized:
    def test_tradeoff_degradation(self, adrs):
        t = triggers(adrs, _hr({"performance": 0.4}))
        assert any(x["kind"] == "cost_realized" and x["adrs"] == ["ADR-B"] for x in t)


@pytest.mark.unit
class TestMetricMapping:
    def test_errors_maps_to_reliability(self, adrs):
        t = triggers(adrs, _hr({"errors": 0.3}))
        assert any(x["attribute"] == "reliability" and x["metric"] == "errors" for x in t)


@pytest.mark.unit
class TestHealthy:
    def test_all_healthy_no_triggers(self, adrs):
        assert triggers(adrs, _hr({"reliability": 0.95, "performance": 0.9}, band="healthy")) == []


@pytest.mark.unit
class TestSuperseded:
    def test_superseded_no_triggers(self, adrs):
        t = triggers({"ADR-OLD": adrs["ADR-OLD"]}, _hr({"reliability": 0.2}))
        assert t == []


@pytest.mark.unit
class TestRealRegistry:
    def test_real_registry_intact(self):
        real_errs, real_adrs = reg.check_registry(reg.DEFAULT_DIR)
        assert real_errs == []

    def test_real_adrs_healthy_no_triggers(self):
        real_errs, real_adrs = reg.check_registry(reg.DEFAULT_DIR)
        healthy = _hr({"reliability": 0.95, "performance": 0.95, "errors": 0.95}, band="healthy")
        assert triggers(real_adrs, healthy) == []

    def test_real_adrs_degraded_reliability_promise_broken(self):
        real_errs, real_adrs = reg.check_registry(reg.DEFAULT_DIR)
        degraded = _hr({"reliability": 0.4}, band="critical")
        rt = triggers(real_adrs, degraded)
        assert any(x["kind"] == "promise_broken" and "ADR-002" in x["adrs"] for x in rt)
