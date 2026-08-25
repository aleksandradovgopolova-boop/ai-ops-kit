"""Гранулярные тесты validate_architecture_decision (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_architecture_decision import (  # noqa: F401
    SCHEMA,
    STATUS,
    check,
    json,
)


@pytest.fixture(scope="module")
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(schema_example):
    assert check(schema_example) == []


@pytest.mark.unit
def test_no_negative_consequences(schema_example):
    errs = check({**schema_example, "consequences": {"positive": ["x"], "negative": []}})
    assert any("negative" in x for x in errs)


@pytest.mark.unit
def test_broken_id(schema_example):
    errs = check({**schema_example, "id": "ADR1"})
    assert any("id" in x for x in errs)


@pytest.mark.unit
def test_unknown_status(schema_example):
    errs = check({**schema_example, "status": "done"})
    assert any("status" in x for x in errs)


@pytest.mark.unit
def test_superseded_without_superseded_by(schema_example):
    errs = check({**schema_example, "status": "superseded"})
    assert any("superseded_by" in x for x in errs)


@pytest.mark.unit
def test_superseded_with_superseded_by(schema_example):
    errs = check({**schema_example, "status": "superseded", "superseded_by": "ADR-002"})
    assert errs == []


@pytest.mark.unit
def test_broken_quality_attribute(schema_example):
    errs = check(
        {
            **schema_example,
            "quality_attributes": [{"attribute": "vibes", "effect": "improves"}],
        }
    )
    assert any("attribute" in x for x in errs)


@pytest.mark.unit
def test_broken_ui_impact(schema_example):
    errs = check({**schema_example, "ui_impact": "huge"})
    assert any("ui_impact" in x for x in errs)


@pytest.mark.unit
def test_user_facing_ui_impact(schema_example):
    errs = check({**schema_example, "ui_impact": "user_facing"})
    assert errs == []


@pytest.mark.unit
def test_empty_context(schema_example):
    errs = check({**schema_example, "context": " "})
    assert any("context" in x for x in errs)


@pytest.mark.unit
def test_status_enum_matches_schema():
    sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(sch["properties"]["status"]["enum"]) == STATUS
