"""Granular tests for validate_integration_trace (migrated from selftest)."""
from __future__ import annotations

import copy

import pytest

from validate_integration_trace import (
    DEMO,
    SCHEMA,
    _chk_ig,
    _load,
    analyze,
    check,
    json,
)


@pytest.fixture
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.fixture
def mutate(schema_example):
    """Helper to deep-copy example and override integration fields."""
    def _mut(**over):
        d = copy.deepcopy(schema_example)
        d["integration"].update(over)
        return d
    return _mut


# --- Schema & analysis ---

class TestSchemaAndAnalysis:
    @pytest.mark.unit
    def test_schema_example_is_valid(self, schema_example):
        assert check(schema_example) == []

    @pytest.mark.unit
    def test_analysis_values(self, schema_example):
        a = analyze(schema_example)
        assert a["speedup"] == round(280 / 190, 3)
        assert a["coordination_overhead"] == 70
        assert a["beneficial"]

    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_integration_trace_demo_is_consistent(self):
        if DEMO.is_dir():
            assert all(check(_load(f)) == [] for f in sorted(DEMO.glob("IT-*.yaml")))


# --- Integration checks ---

class TestIntegrationChecks:
    @pytest.mark.unit
    def test_integration_sha_equals_package_sha(self, schema_example):
        errs = _chk_ig(schema_example, integration_sha="aaaaaaa")
        assert any("НОВЫЙ integration-SHA" in x for x in errs)

    @pytest.mark.unit
    def test_completed_true_without_rerun(self, mutate):
        errs = check(mutate(aggregate_checks_rerun=False))
        assert any("aggregate_checks_rerun" in x for x in errs)

    @pytest.mark.unit
    def test_completed_true_new_sha_false(self, mutate):
        errs = check(mutate(new_sha=False))
        assert any("new_sha" in x for x in errs)

    @pytest.mark.unit
    def test_conflicts_with_completed_is_block(self, mutate):
        errs = check(mutate(fan_in_conflicts=2))
        assert any("КОНФЛИКТ=BLOCK" in x for x in errs)

    @pytest.mark.unit
    def test_conflicts_without_completed_is_valid(self, schema_example):
        blocked = copy.deepcopy(schema_example)
        blocked["integration"] = {
            "completed": False, "integration_sha": None, "new_sha": False,
            "aggregate_checks_rerun": False, "fan_in_conflicts": 2}
        assert check(blocked) == []


# --- Timing & structural ---

class TestTimingAndStructural:
    @pytest.mark.unit
    def test_actual_less_than_max_package(self, schema_example):
        bad_t = copy.deepcopy(schema_example)
        bad_t["wall_seconds_actual"] = 50
        errs = check(bad_t)
        assert any("самого долгого" in x for x in errs)

    @pytest.mark.unit
    def test_baseline_not_equal_sum(self, schema_example):
        bad_b = copy.deepcopy(schema_example)
        bad_b["sequential_baseline_seconds"] = 999
        errs = check(bad_b)
        assert any("сумма времён" in x for x in errs)

    @pytest.mark.unit
    def test_broken_id(self, schema_example):
        errs = check({**schema_example, "id": "IT1"})
        assert any("id должен" in x for x in errs)
