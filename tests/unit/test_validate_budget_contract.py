"""Гранулярные тесты validate_budget_contract (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_budget_contract import (  # noqa: F401
    DEMO,
    ON_EXH,
    SCHEMA,
    check,
    check_registry,
    json,
)


@pytest.fixture(scope="module")
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(schema_example):
    assert check(schema_example) == []


@pytest.mark.unit
def test_real_demo_is_valid():
    errs, _ = check_registry(DEMO)
    assert errs == []


@pytest.mark.unit
def test_limits_without_boundaries(schema_example):
    errs = check(
        {
            **schema_example,
            "limits": {
                "max_model_calls": None,
                "max_iterations": None,
                "max_tokens": None,
                "max_cost_usd": None,
                "max_wall_seconds": None,
            },
        }
    )
    assert any("хотя бы одна граница" in x for x in errs)


@pytest.mark.unit
def test_hard_true_with_degrade(schema_example):
    errs = check({**schema_example, "hard": True, "on_exhaustion": "degrade"})
    assert any("degrade" in x for x in errs)


@pytest.mark.unit
def test_hard_false_with_degrade(schema_example):
    errs = check({**schema_example, "hard": False, "on_exhaustion": "degrade"})
    assert errs == []


@pytest.mark.unit
def test_scope_loop_without_lp_ref(schema_example):
    errs = check({**schema_example, "scope": "loop", "scope_ref": "loop1"})
    assert any("LP-NNN" in x for x in errs)


@pytest.mark.unit
def test_scope_work_graph_requires_wg_ref(schema_example):
    errs = check({**schema_example, "scope": "work_graph", "scope_ref": "x"})
    assert any("WG-NNN" in x for x in errs)


@pytest.mark.unit
def test_empty_enforced_by(schema_example):
    errs = check({**schema_example, "enforced_by": " "})
    assert any("enforced_by" in x for x in errs)


@pytest.mark.unit
def test_broken_id(schema_example):
    errs = check({**schema_example, "id": "BUD1"})
    assert any("id" in x for x in errs)


@pytest.mark.unit
def test_on_exhaustion_enum_matches_schema():
    sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(sch["properties"]["on_exhaustion"]["enum"]) == ON_EXH
