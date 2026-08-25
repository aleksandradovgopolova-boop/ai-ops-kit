"""Гранулярные тесты validate_requirements_artifact."""
from __future__ import annotations

import pytest

from validate_requirements_artifact import check, provided_evidence


@pytest.fixture
def valid_artifact():
    return {
        "schema_version": 1,
        "kind": "requirements-artifact",
        "workitem_id": "feat-1",
        "requirements": [
            {
                "id": "R1",
                "statement": "фильтр по статусу сужает список",
                "acceptance": ["when статус=paid then только оплаченные"],
            }
        ],
    }


@pytest.mark.unit
class TestCheck:
    def test_valid_artifact_no_errors(self, valid_artifact):
        assert check(valid_artifact) == []

    def test_empty_requirements_has_errors(self):
        errors = check({"schema_version": 1, "kind": "requirements-artifact", "requirements": []})
        assert errors != []

    def test_missing_acceptance_is_error(self):
        errors = check({
            "schema_version": 1,
            "kind": "requirements-artifact",
            "requirements": [{"id": "R1", "statement": "x"}],
        })
        assert any("acceptance" in e for e in errors)

    def test_missing_statement_is_error(self):
        errors = check({
            "schema_version": 1,
            "kind": "requirements-artifact",
            "requirements": [{"id": "R1", "acceptance": ["a"]}],
        })
        assert any("statement" in e for e in errors)

    def test_wrong_kind_is_error(self):
        errors = check({"kind": "x", "requirements": []})
        assert any("kind" in e for e in errors)

    def test_duplicate_id_is_error(self):
        errors = check({
            "schema_version": 1,
            "kind": "requirements-artifact",
            "requirements": [
                {"id": "R1", "statement": "a", "acceptance": ["s"]},
                {"id": "R1", "statement": "b", "acceptance": ["s"]},
            ],
        })
        assert any("дубл" in e for e in errors)


@pytest.mark.unit
class TestProvidedEvidence:
    def test_valid_covers_both_evidence(self, valid_artifact):
        assert provided_evidence(valid_artifact) == ["testable_requirements", "acceptance_scenarios"]

    def test_empty_requirements_empty_evidence(self):
        assert provided_evidence({"kind": "requirements-artifact", "requirements": []}) == []
