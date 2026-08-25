"""Гранулярные тесты pipeline_helpers (мигрировано из test_pipeline_helpers_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from pipeline_helpers import (
    NO_SELF_REVIEW,
    _intake_evidence,
    _parse_yaml_block,
    _profile_summary,
    _reviewable_gates,
)


@pytest.mark.unit
class TestImports:
    def test_profile_summary_callable(self):
        assert callable(_profile_summary)

    def test_intake_evidence_callable(self):
        assert callable(_intake_evidence)

    def test_reviewable_gates_callable(self):
        assert callable(_reviewable_gates)

    def test_parse_yaml_block_callable(self):
        assert callable(_parse_yaml_block)

    def test_no_self_review_contains_security(self):
        assert "security" in NO_SELF_REVIEW
