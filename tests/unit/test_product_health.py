"""Гранулярные тесты product_health (мигрировано из test_product_health_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from product_health import (
    compute,
)


@pytest.mark.unit
class TestIdealMetrics:
    def test_score_100(self):
        r = compute({"scope": "feature:x", "period": "2026-W30", "metrics": {
            "adoption": {"value": 0.5, "target": 0.5},
            "errors": {"value": 0.5, "target": 1.0, "direction": "lower-is-better"},
        }})
        assert r["health_score"]["value"] == 100.0

    def test_band_healthy(self):
        r = compute({"scope": "feature:x", "period": "2026-W30", "metrics": {
            "adoption": {"value": 0.5, "target": 0.5},
            "errors": {"value": 0.5, "target": 1.0, "direction": "lower-is-better"},
        }})
        assert r["health_score"]["band"] == "healthy"


@pytest.mark.unit
class TestBadMetrics:
    def test_band_critical(self):
        r = compute({"metrics": {
            "adoption": {"value": 0.1, "target": 0.5},
            "errors": {"value": 4.0, "target": 1.0, "direction": "lower-is-better"},
        }})
        assert r["health_score"]["band"] == "critical"

    def test_both_findings(self):
        r = compute({"metrics": {
            "adoption": {"value": 0.1, "target": 0.5},
            "errors": {"value": 4.0, "target": 1.0, "direction": "lower-is-better"},
        }})
        assert len(r["findings"]) == 2


@pytest.mark.unit
class TestWeightedMetrics:
    def test_weighted_score(self):
        r = compute({"metrics": {
            "adoption": {"value": 0.25, "target": 0.5},
            "reliability": {"value": 1.0, "target": 1.0},
        }, "weights": {"adoption": 3, "reliability": 1}})
        assert r["health_score"]["value"] == 62.5

    def test_band_warning(self):
        r = compute({"metrics": {
            "adoption": {"value": 0.25, "target": 0.5},
            "reliability": {"value": 1.0, "target": 1.0},
        }, "weights": {"adoption": 3, "reliability": 1}})
        assert r["health_score"]["band"] == "warning"
