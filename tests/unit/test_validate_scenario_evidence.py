"""Granular tests for validate_scenario_evidence (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_scenario_evidence import (  # noqa: F401
    check,
)


@pytest.fixture
def good_engineering():
    return {
        "status": "pass",
        "named_user_scenario": "владелец видит правку коллеги над общим объектом",
        "scenario_test": "tests/e2e/shared_object.py::test_two_users_one_object",
    }


@pytest.fixture
def empty_with_provided():
    return {"status": "pass", "provided": ["build_passed", "tests_passed", "tested_revision"]}


@pytest.mark.unit
def test_engineering_named_scenario_with_test_no_advisory(good_engineering):
    assert check(good_engineering, "ENGINEERING") == []


@pytest.mark.unit
def test_engineering_without_scenario_advisory_fires(empty_with_provided):
    fires = check(empty_with_provided, "ENGINEERING")
    assert len(fires) == 2


@pytest.mark.unit
def test_product_without_scenario_also_fires(empty_with_provided):
    assert len(check(empty_with_provided, "PRODUCT")) == 2


@pytest.mark.unit
def test_critical_only_scenario_no_test_one_finding():
    assert len(check({"named_user_scenario": "s"}, "CRITICAL")) == 1


@pytest.mark.unit
def test_scenario_test_not_looking_like_test_is_finding():
    assert any("не похож" in f for f in check(
        {"named_user_scenario": "s", "scenario_test": "just words"}, "ENGINEERING"))


@pytest.mark.unit
def test_quick_not_applicable_silent(empty_with_provided):
    assert check(empty_with_provided, "QUICK") == []


@pytest.mark.unit
def test_visual_not_applicable_silent(empty_with_provided):
    assert check(empty_with_provided, "VISUAL") == []


@pytest.mark.unit
def test_none_evidence_with_engineering_is_finding():
    assert check(None, "ENGINEERING") != []
