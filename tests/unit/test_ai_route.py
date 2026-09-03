"""Гранулярные тесты ai_route (мигрировано из test_ai_route_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.ai_route import (
    REQUIRED_KEYS,
    SCENARIOS,
    route,
)


@pytest.mark.unit
class TestAiRouteScenarios:
    @pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
    def test_scenario_has_required_keys(self, sc):
        d = route(sc["inp"])
        missing = [k for k in REQUIRED_KEYS if k not in d or d[k] in (None, "")]
        assert not missing, f"нет ключей {missing}"

    @pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
    def test_scenario_expected_values(self, sc):
        d = route(sc["inp"])
        for k, v in sc["expect"].items():
            assert d.get(k) == v, f"{k}={d.get(k)!r} != ожидалось {v!r}"

    @pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
    def test_scenario_has_reasons(self, sc):
        d = route(sc["inp"])
        assert d.get("reasons"), "пустые reasons"
