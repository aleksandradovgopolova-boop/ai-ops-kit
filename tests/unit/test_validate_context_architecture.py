"""Гранулярные тесты validate_context_architecture (миграция с селфтеста)."""
from __future__ import annotations

import pytest

from validate_context_architecture import (
    CANON,
    SCHEMA,
    check,
    json,
)


@pytest.fixture(scope="module")
def example():
    """Первый пример из JSON-схемы — базовый валидный документ."""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
@pytest.mark.slow
class TestContextArchitectureValidation:

    def test_schema_example_is_valid(self, example):
        assert check(example) == []

    def test_pipeline_order_violation_detected(self, example):
        errs = check({**example,
                      "retrieval_pipeline": ["full_text", "repository_graph", "budgeted_role_view"]})
        assert any("порядк" in x for x in errs)

    def test_semantic_fallback_first_rejected(self, example):
        errs = check({**example,
                      "retrieval_pipeline": ["semantic_fallback", "reranking", "budgeted_role_view"]})
        assert any("сначала вектор" in x for x in errs)

    def test_missing_exact_revision_binding_rejected(self, example):
        errs = check({**example,
                      "invariants": {**example["invariants"], "exact_revision_binding": False}})
        assert any("exact_revision_binding" in x for x in errs)

    def test_incomplete_role_views_rejected(self, example):
        errs = check({**example, "role_views": ["planner"]})
        assert any("role_views" in x for x in errs)

    def test_incomplete_cache_key_rejected(self, example):
        errs = check({**example, "cache_key": ["repository", "sha"]})
        assert any("cache_key" in x for x in errs)

    def test_non_context_compiler_builds_on_rejected(self, example):
        errs = check({**example, "builds_on": "новая vector-db"})
        assert any("context_compiler" in x for x in errs)

    def test_propposed_allows_incomplete_role_views(self, example):
        assert check({**example, "status": "proposed", "role_views": ["planner"]}) == []

    def test_bad_id_rejected(self, example):
        errs = check({**example, "id": "CAD1"})
        assert any("id" in x for x in errs)

    def test_enum_stage_matches_schema(self, example):
        schema_enum = set(
            json.loads(SCHEMA.read_text(encoding="utf-8"))
            ["properties"]["retrieval_pipeline"]["items"]["enum"]
        )
        assert schema_enum == set(CANON)
