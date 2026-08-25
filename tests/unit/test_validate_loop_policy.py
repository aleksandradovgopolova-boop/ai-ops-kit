"""Granular tests for validate_loop_policy (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_loop_policy import (
    LOOP_TYPES,
    SCHEMA,
    check,
    json,
)


@pytest.fixture
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


# --- Schema & enum ---

class TestSchemaAndEnum:
    @pytest.mark.unit
    def test_schema_example_is_valid(self, schema_example):
        assert check(schema_example) == []

    @pytest.mark.unit
    def test_enum_loop_type_matches_schema(self):
        sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(sch["properties"]["loop_type"]["enum"]) == LOOP_TYPES


# --- Validation errors ---

class TestValidationErrors:
    @pytest.mark.unit
    def test_unbounded_budgets(self, schema_example):
        errs = check({**schema_example,
                       "budgets": {"max_iterations": None, "max_tokens": None, "max_cost_usd": None}})
        assert any("unbounded" in x for x in errs)

    @pytest.mark.unit
    def test_empty_stop_conditions(self, schema_example):
        errs = check({**schema_example, "stop_conditions": []})
        assert any("stop_conditions" in x for x in errs)

    @pytest.mark.unit
    def test_stop_conditions_without_budget_exhaustion(self, schema_example):
        errs = check({**schema_example, "stop_conditions": ["всё готово"]})
        assert any("исчерпание бюджета" in x for x in errs)

    @pytest.mark.unit
    def test_empty_progress_measure(self, schema_example):
        errs = check({**schema_example, "progress_measure": " "})
        assert any("progress_measure" in x for x in errs)

    @pytest.mark.unit
    def test_unknown_loop_type(self, schema_example):
        errs = check({**schema_example, "loop_type": "magic"})
        assert any("loop_type" in x for x in errs)

    @pytest.mark.unit
    def test_broken_id(self, schema_example):
        errs = check({**schema_example, "id": "LP1"})
        assert any("id" in x for x in errs)


# --- Partial budgets ---

class TestPartialBudgets:
    @pytest.mark.unit
    def test_tokens_only_budget_is_valid(self, schema_example):
        assert check({**schema_example,
                       "budgets": {"max_iterations": None, "max_tokens": 100000,
                                   "max_cost_usd": None}}) == []
