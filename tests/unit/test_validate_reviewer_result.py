"""Granular tests for validate_reviewer_result (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_reviewer_result import (  # noqa: F401
    _gate_ids,
    check,
)


@pytest.fixture
def gate_ids():
    return _gate_ids()


@pytest.fixture
def valid_fail():
    return {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "reviewer": "code-reviewer", "reviewed_revision": "abc1234",
        "status": "fail",
        "checks": [{"id": "acceptance_scenario_3", "status": "fail",
                     "evidence": {"file": "src/orders/filter.ts", "lines": "74-91"}}],
        "blockers": ["Empty state for zero matching orders is missing"],
    }


@pytest.mark.unit
def test_valid_fail_with_blockers(valid_fail, gate_ids):
    assert check(valid_fail, gate_ids) == []


@pytest.mark.unit
def test_fail_without_blockers_raises(valid_fail, gate_ids):
    assert any("blockers" in e for e in check({**valid_fail, "blockers": []}, gate_ids))


@pytest.mark.unit
def test_warn_without_blockers_raises(gate_ids):
    warn_no_bl = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "warn", "checks": [{"id": "c1", "status": "warn"}],
    }
    assert any("blockers" in e for e in check(warn_no_bl, gate_ids))


@pytest.mark.unit
def test_warn_with_blockers_is_valid(gate_ids):
    warn_with_bl = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "warn", "checks": [{"id": "c1", "status": "warn"}],
        "blockers": ["ярус 500 не покрыт тестом"],
    }
    assert check(warn_with_bl, gate_ids) == []


@pytest.mark.unit
def test_fail_checks_with_status_pass_raises(valid_fail, gate_ids):
    incoherent = {**valid_fail, "status": "pass"}
    assert any("несогласованно" in e for e in check(incoherent, gate_ids))


@pytest.mark.unit
def test_unknown_gate_raises(valid_fail, gate_ids):
    assert any("отсутствует" in e for e in check({**valid_fail, "gate": "nope"}, gate_ids))


@pytest.mark.unit
def test_valid_pass(gate_ids):
    okr = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "pass", "checks": [{"id": "c1", "status": "pass"}],
    }
    assert check(okr, gate_ids) == []


@pytest.mark.unit
def test_empty_checks_rejected_by_default(gate_ids):
    """По умолчанию (структурный путь) пустой checks — порок формы: reviewer-result без checks
    не принимается. Строгость структурного контракта не ослаблена."""
    prose = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "pass", "checks": [],
    }
    assert any("непустым" in e for e in check(prose, gate_ids))


@pytest.mark.unit
def test_empty_checks_allowed_for_prose_verdict(gate_ids):
    """(#614) allow_empty_checks=True: прозаический вердикт (`Recommendation: pass`) несёт status,
    но структурных checks у него нет — пустой список для него ДОПУСТИМ, структура не условие вердикта."""
    prose = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "pass", "checks": [], "prose_verdict": True,
    }
    assert check(prose, gate_ids, allow_empty_checks=True) == []


@pytest.mark.unit
def test_prose_warn_still_needs_blockers_even_with_empty_checks(gate_ids):
    """(#614) Послабление касается ТОЛЬКО пустых checks: warn/fail по-прежнему обязаны нести
    непустой blockers (блокирующий вердикт без причины запрещён)."""
    warn_no_bl = {
        "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
        "status": "warn", "checks": [], "prose_verdict": True,
    }
    assert any("blockers" in e for e in check(warn_no_bl, gate_ids, allow_empty_checks=True))
