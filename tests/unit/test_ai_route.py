"""Гранулярные тесты ai_route (мигрировано из test_ai_route_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.shared.ai_route import (
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


def test_unavailable_choices_stay_none_in_plain_dict_after_actual_registry_reads(monkeypatch):
    from copy import deepcopy
    from ai_ops_kit.shared import ai_route

    signals = {"task_type": "QUICK", "available_providers": [], "available_runtimes": []}
    before = deepcopy(signals)
    actual_load, reads = ai_route.load, []

    def traced_load(name):
        result = actual_load(name)
        reads.append(name)
        return result

    monkeypatch.setattr(ai_route, "load", traced_load)
    result = ai_route.route(signals)
    assert reads == ["routing-policy.yaml", "providers.yaml", "runtimes.yaml", "workflows.yaml"]
    assert type(result) is dict
    assert result["selected_provider"] is None and result["selected_runtime"] is None
    assert result["classification_confidence"] == "normal"
    assert signals == before


@pytest.mark.parametrize(("approval", "expected"), [(True, True), (False, False), ("conditional", False)])
def test_approval_keeps_existing_identity_semantics(monkeypatch, approval, expected):
    from copy import deepcopy
    from ai_ops_kit.shared import ai_route

    actual_load = ai_route.load

    def policy_load(name):
        result = deepcopy(actual_load(name))
        if name == "routing-policy.yaml":
            result["approval_rules"] = [{"default": True, "human_approval_required": approval}]
        return result

    monkeypatch.setattr(ai_route, "load", policy_load)
    result = ai_route.route({"task_type": "QUICK"})
    assert result["human_approval_required"] is expected
