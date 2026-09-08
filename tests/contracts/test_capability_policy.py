"""Настройки как capability policy — 7 осей намерением, planned не выдан за готовое (#644).

Вторая половина #632: настройки задаются intent-level выбором по оси (registry/capability-policy.yaml),
а не набором флагов; резолвер (ai_ops_kit/checks/capability_policy) раскладывает намерение на
внутренние флаги. Честность (§26, инвариант деклараций): у каждого выбора status implemented|planned,
planned-выбор резолвер НЕ выдаёт за готовый, а default обязан быть implemented. Контракт-тест по
образцу test_domain_model / test_decision_boundary: читает реестр И зовёт продуктовый код.
"""
from __future__ import annotations

import copy

import pytest

from ai_ops_kit.checks import capability_policy as cp

POLICY = cp.load_policy()
SEVEN = {"communication", "autonomy", "watch", "quality", "team", "design", "cost"}


@pytest.mark.contract
def test_exactly_the_seven_named_axes():
    assert set(POLICY["axes"]) == SEVEN


@pytest.mark.contract
def test_the_registry_is_honest():
    assert cp.honesty_errors() == [], "\n  - ".join([""] + cp.honesty_errors())


@pytest.mark.contract
def test_every_axis_default_is_an_implemented_choice():
    for axis, a in POLICY["axes"].items():
        assert a["choices"][a["default"]]["status"] == "implemented", axis


@pytest.mark.contract
def test_the_three_built_axes_are_fully_implemented():
    """Communication/Autonomy/Team построены целиком — резолвятся по любому выбору."""
    for axis in ("communication", "autonomy", "team"):
        for choice in POLICY["axes"][axis]["choices"]:
            r = cp.resolve(axis, choice, POLICY)
            assert r["status"] == "implemented" and r["value"] == choice, (axis, choice)


@pytest.mark.contract
def test_implemented_choice_resolves_to_a_value():
    r = cp.resolve("communication", "debug", POLICY)
    assert r["status"] == "implemented" and r["value"] == "debug"
    assert r["resolves_to"] == "communication.audience"


@pytest.mark.contract
def test_planned_choice_is_not_passed_off_as_ready():
    r = cp.resolve("watch", "continuous", POLICY)
    assert r["status"] == "planned" and r["value"] is None      # НЕ выдаётся за готовое


@pytest.mark.contract
def test_unknown_axis_or_choice_is_an_honest_refusal():
    assert cp.resolve("nope", "x", POLICY)["status"] == "unknown"
    assert cp.resolve("cost", "nope", POLICY)["status"] == "unknown"


@pytest.mark.contract
def test_resolve_all_uses_defaults_for_unspecified_axes():
    r = cp.resolve_all({"communication": "technical"}, POLICY)
    assert set(r) == SEVEN
    assert r["communication"]["value"] == "technical"
    assert r["watch"]["choice"] == "nightly"                    # default подставлен
    assert r["cost"]["choice"] == "balanced" and r["cost"]["status"] == "implemented"


# ─── пробы: честность обязана краснеть ───────────────────────────────────────────────────────────

@pytest.mark.contract
def test_a_default_pointing_at_a_planned_choice_is_caught():
    p = copy.deepcopy(POLICY)
    p["axes"]["watch"]["default"] = "continuous"                # continuous — planned
    assert any("watch" in e and "implemented" in e for e in cp.honesty_errors(p))


@pytest.mark.contract
def test_a_bad_status_is_caught():
    p = copy.deepcopy(POLICY)
    p["axes"]["cost"]["choices"]["economy"]["status"] = "maybe"
    assert any("cost.economy" in e for e in cp.honesty_errors(p))


@pytest.mark.contract
def test_a_missing_mechanism_file_is_caught():
    p = copy.deepcopy(POLICY)
    p["axes"]["quality"]["mechanism"] = "quality/does-not-exist.yaml"
    assert any("quality" in e and "резолвится" in e for e in cp.honesty_errors(p))


@pytest.mark.contract
def test_an_axis_without_resolves_to_is_caught():
    p = copy.deepcopy(POLICY)
    del p["axes"]["team"]["resolves_to"]
    assert any("team" in e and "resolves_to" in e for e in cp.honesty_errors(p))
