"""Granular tests for validate_quality_attributes (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_quality_attributes import (  # noqa: F401
    fitness,
    profile,
    reg,
)


def _adr(aid, qas, status="accepted"):
    return {"id": aid, "status": status, "quality_attributes": qas}


@pytest.fixture
def real_adrs():
    errs, adrs = reg.check_registry(reg.DEFAULT_DIR)
    assert errs == [], f"real ADR registry has errors: {errs}"
    return adrs


@pytest.mark.unit
def test_real_adr_registry_is_consistent():
    errs, _ = reg.check_registry(reg.DEFAULT_DIR)
    assert errs == []


@pytest.mark.unit
def test_real_registry_passes_fitness(real_adrs):
    assert fitness(real_adrs) == []


@pytest.mark.unit
def test_profile_is_nonempty_and_covers_real_attributes(real_adrs):
    p = profile(real_adrs)
    assert bool(p) and "maintainability" in p


@pytest.mark.unit
def test_degrades_without_note_is_smell():
    e = fitness({"ADR-001": _adr("ADR-001", [{"attribute": "performance", "effect": "degrades"}])})
    assert any("без note" in x for x in e)


@pytest.mark.unit
def test_degrades_with_note_is_ok():
    e = fitness({"ADR-001": _adr("ADR-001", [
        {"attribute": "performance", "effect": "degrades", "note": "кэш прогревается"},
    ])})
    assert e == []


@pytest.mark.unit
def test_improves_plus_degrades_without_tradeoff_is_contradiction():
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "security", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "security", "effect": "degrades", "note": "x"}]),
    })
    assert any("противоречие" in x for x in e)


@pytest.mark.unit
def test_improves_plus_degrades_plus_tradeoff_is_intentional():
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "security", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "security", "effect": "degrades", "note": "x"}]),
        "ADR-003": _adr("ADR-003", [{"attribute": "security", "effect": "tradeoff"}]),
    })
    assert not any("противоречие" in x for x in e)


@pytest.mark.unit
def test_superseded_adr_does_not_create_contradiction():
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "cost", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "cost", "effect": "degrades", "note": "x"}],
                        status="superseded"),
    })
    assert e == []
