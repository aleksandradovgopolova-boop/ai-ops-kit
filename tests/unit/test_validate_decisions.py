"""Гранулярные тесты validate_decisions (миграция с селфтеста)."""
from __future__ import annotations

import pytest

from validate_decisions import (
    PKG,
    check,
    yaml,
)


@pytest.fixture(scope="module")
def valid_registry():
    """Минимальный валидный реестр решений."""
    return {
        "schema_version": 1, "kind": "decisions-registry",
        "episodes": [{"id": "ep-1", "question": "q", "decision": "d", "reason": "r",
                       "reversibility": "two-way", "date": "2026-07-13"}],
        "principles": [{"id": "dp-1", "principle": "p", "scope": ["s"], "status": "ratified",
                         "confidence": "high", "recurrence_count": 3, "review_date": "2026-12-01",
                         "derived_from": ["ep-1"]}],
        "outcomes": [{"decision": "ep-1", "outcome": "ok"}],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestDecisionsValidation:

    def test_valid_registry_no_errors(self, valid_registry):
        e, w = check(valid_registry)
        assert e == []

    def test_retired_without_retired_reason_rejected(self):
        e, _ = check({"principles": [{"id": "dp-x", "principle": "p", "scope": ["s"],
                                       "status": "retired", "confidence": "low",
                                       "recurrence_count": 1, "review_date": "2026-01-01",
                                       "derived_from": []}], "episodes": []})
        assert any("retired_reason" in x for x in e)

    def test_derived_from_nonexistent_episode_rejected(self):
        e, _ = check({"principles": [{"id": "dp-y", "principle": "p", "scope": ["s"],
                                       "status": "ratified", "confidence": "high",
                                       "recurrence_count": 2, "review_date": "2026-01-01",
                                       "derived_from": ["ep-nope"]}], "episodes": []})
        assert any("ep-nope" in x for x in e)

    def test_invalid_reversibility_rejected(self):
        e, _ = check({"principles": [], "episodes": [
            {"id": "ep-z", "question": "q", "decision": "d", "reason": "r",
             "reversibility": "maybe", "date": "2026-07-13"}]})
        assert any("reversibility" in x for x in e)

    def test_ratified_from_single_case_warns(self):
        _, w = check({"principles": [{"id": "dp-w", "principle": "p", "scope": ["s"],
                                       "status": "ratified", "confidence": "high",
                                       "recurrence_count": 1, "review_date": "2026-12-01",
                                       "derived_from": []}], "episodes": []})
        assert any("одного случая" in x for x in w)

    def test_kit_registry_is_valid(self):
        reg = PKG / "decisions" / "registry.yaml"
        if reg.exists():
            e, _ = check(yaml.safe_load(reg.read_text(encoding="utf-8")))
            assert e == []
