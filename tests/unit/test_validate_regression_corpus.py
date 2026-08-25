"""Granular tests for validate_regression_corpus (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_regression_corpus import (  # noqa: F401
    DEFAULT_DIR,
    SCHEMA,
    check,
    check_registry,
    json,
    taxonomy,
)


@pytest.fixture
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(schema_example):
    assert check(schema_example) == []


@pytest.mark.unit
def test_real_regression_corpus_is_consistent():
    reg_errs, ids = check_registry(DEFAULT_DIR)
    assert reg_errs == [], f"real corpus errors: {reg_errs} ({len(ids)} cases)"


@pytest.mark.unit
def test_status_fixed_without_fixed_version_raises(schema_example):
    assert any("fixed_version" in x
               for x in check({**schema_example, "status": "fixed", "fixed_version": None}))


@pytest.mark.unit
def test_status_fixed_without_regression_test_raises(schema_example):
    assert any("regression_test" in x
               for x in check({**schema_example, "regression_test": " "}))


@pytest.mark.unit
def test_status_open_with_fixed_version_raises(schema_example):
    assert any("open" in x
               for x in check({**schema_example, "status": "open", "fixed_version": "3.0.19"}))


@pytest.mark.unit
def test_unknown_layer_raises(schema_example):
    assert any("affected_layer" in x
               for x in check({**schema_example, "affected_layer": "vibes"}))


@pytest.mark.unit
def test_broken_failure_id_raises(schema_example):
    assert any("failure_id" in x
               for x in check({**schema_example, "failure_id": "RC1"}))


@pytest.mark.unit
def test_occurrences_ge_2_without_on_repeat_raises(schema_example):
    assert any("occurrences>=2" in x
               for x in check({**schema_example, "occurrences": 2}))


@pytest.mark.unit
def test_escalate_without_structural_fix_raises(schema_example):
    assert any("structural_fix" in x
               for x in check({**schema_example, "occurrences": 2,
                               "on_repeat": "escalate_to_structural"}))


@pytest.mark.unit
def test_repeat_plus_escalate_plus_structural_fix_is_valid(schema_example):
    assert check({**schema_example, "occurrences": 2,
                  "on_repeat": "escalate_to_structural",
                  "structural_fix": "единственная функция apply_token + запрет прямого вызова линтером"}) == []


@pytest.mark.unit
def test_occurrences_1_without_on_repeat_is_valid(schema_example):
    assert check({**schema_example, "occurrences": 1}) == []


@pytest.mark.unit
def test_broken_on_repeat_raises(schema_example):
    assert any("on_repeat" in x
               for x in check({**schema_example, "on_repeat": "maybe"}))


@pytest.mark.unit
def test_taxonomy_by_layer_is_nonempty():
    tx = taxonomy(DEFAULT_DIR)
    assert bool(tx["by_layer"])


@pytest.mark.unit
def test_taxonomy_carries_repeated_and_structural_counters():
    tx = taxonomy(DEFAULT_DIR)
    assert "repeated_classes" in tx and "escalated_to_structural" in tx
