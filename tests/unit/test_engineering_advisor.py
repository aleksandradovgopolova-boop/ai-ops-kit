"""Гранулярные тесты engineering_advisor (мигрировано из test_engineering_advisor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops.engineering_advisor import (
    advise,
    check,
)


@pytest.mark.unit
class TestAdvise:
    def test_advise_on_empty_repo_returns_engineering_advice(self, tmp_path):
        result = advise(str(tmp_path))
        assert result.get("kind") == "EngineeringAdvice"

    def test_check_valid(self, tmp_path):
        result = advise(str(tmp_path))
        assert check(result) == []

    def test_recommendations_is_list(self, tmp_path):
        result = advise(str(tmp_path))
        assert isinstance(result.get("recommendations", []), list)

    def test_summary_is_string(self, tmp_path):
        result = advise(str(tmp_path))
        assert isinstance(result.get("summary"), str)


@pytest.mark.unit
class TestCheck:
    def test_invalid_data_returns_errors(self):
        errors = check({"kind": "wrong"})
        assert errors
