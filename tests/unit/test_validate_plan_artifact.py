"""Гранулярные тесты validate_plan_artifact (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_plan_artifact import (  # noqa: F401
    check,
    provided_evidence,
)


@pytest.fixture
def good_plan():
    """Валидный план-артефакт."""
    return {
        "schema_version": 1,
        "kind": "plan-artifact",
        "workitem_id": "feat-1",
        "work_packages": [
            {"id": "WP1", "summary": "фильтр в контроллере", "depends_on": []},
            {"id": "WP2", "summary": "тест фильтра", "depends_on": ["WP1"]},
        ],
        "write_scope": ["src/catalog/"],
    }


@pytest.mark.unit
def test_valid_plan_no_errors(good_plan):
    """Валидный план -> без ошибок."""
    assert check(good_plan) == []


@pytest.mark.unit
def test_valid_plan_covers_required_evidence(good_plan):
    """Валидный -> закрывает три required_evidence."""
    assert provided_evidence(good_plan) == ["work_packages", "dependencies", "write_scope"]


@pytest.mark.unit
def test_empty_work_packages_is_error():
    """Пустой work_packages -> ошибка."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [],
        "write_scope": ["src/"],
    }
    assert check(bad) != []


@pytest.mark.unit
def test_missing_write_scope_is_error():
    """Отсутствует write_scope -> ошибка."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [{"id": "WP1", "summary": "x", "depends_on": []}],
    }
    errs = check(bad)
    assert any("write_scope" in e for e in errs), errs


@pytest.mark.unit
def test_depends_on_not_list_is_error():
    """depends_on не список -> ошибка."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [{"id": "WP1", "summary": "x", "depends_on": "WP0"}],
        "write_scope": ["src/"],
    }
    errs = check(bad)
    assert any("depends_on" in e for e in errs), errs


@pytest.mark.unit
def test_depends_on_nonexistent_wp_is_error():
    """depends_on на несуществующий WP -> ошибка (целостность)."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [{"id": "WP1", "summary": "x", "depends_on": ["WPX"]}],
        "write_scope": ["src/"],
    }
    errs = check(bad)
    assert any("несуществующ" in e for e in errs), errs


@pytest.mark.unit
def test_invalid_plan_evidence_is_empty():
    """Невалидный -> evidence пуст."""
    assert provided_evidence({"kind": "plan-artifact", "work_packages": []}) == []


@pytest.mark.unit
def test_depends_on_contains_dict_is_error_not_crash():
    """Регрессия: depends_on содержит dict -> ошибка (не краш unhashable)."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [{"id": "WP1", "summary": "x", "depends_on": [{"id": "WP0"}]}],
        "write_scope": ["src/"],
    }
    # Не должно быть TypeError — должна быть честная ошибка валидации
    errs = check(bad)
    assert any("строкой-id" in e for e in errs), errs


@pytest.mark.unit
def test_wp_id_not_string_is_error_not_crash():
    """Регрессия: id work_package не строка (dict) -> ошибка (не краш unhashable)."""
    bad = {
        "schema_version": 1,
        "kind": "plan-artifact",
        "work_packages": [{"id": {"nested": 1}, "summary": "x", "depends_on": []}],
        "write_scope": ["src/"],
    }
    # Не должно быть TypeError — должна быть честная ошибка валидации
    errs = check(bad)
    assert any("id должен быть строкой" in e for e in errs), errs
