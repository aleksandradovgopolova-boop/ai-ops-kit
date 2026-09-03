"""Гранулярные тесты delegation_advisor (мигрировано из test_delegation_advisor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops.delegation_advisor import (
    advise,
    check,
)


@pytest.mark.unit
class TestAdvise:
    def test_30_files_triggers_delegation(self):
        r = advise({"exploration_files": 30})
        assert any(x["trigger"] == "repository_wide_exploration" for x in r)

    def test_return_summary_not_raw(self):
        r = advise({"exploration_files": 30})
        assert r and "релевантные пути" in r[0]["return_to_main"]
        assert "все прочитанные файлы" in r[0]["do_not_return"]

    def test_check_valid(self):
        r = advise({"exploration_files": 30})
        assert check(r) == []

    def test_3_files_below_threshold(self):
        r = advise({"exploration_files": 3})
        assert not r

    def test_compare_6_files_triggers_delegation(self):
        r = advise({"compare_files": 6})
        assert any(x["trigger"] == "many_file_comparison" for x in r)

    def test_large_log_triggers_delegation(self):
        r = advise({"log_lines": 2000})
        assert any(x["trigger"] == "large_log_analysis" for x in r)

    def test_research_review_mechanical_three_recommendations(self):
        r = advise({"external_research": True, "independent_review": True, "mass_mechanical_inspection": True})
        assert len(r) == 3

    def test_research_delegates_to_research_subagent(self):
        r = advise({"external_research": True, "independent_review": True, "mass_mechanical_inspection": True})
        assert any(x["delegate_to"] == "research-сабагент" for x in r)

    def test_empty_signals_no_recommendations(self):
        assert advise({}) == []


@pytest.mark.unit
class TestCheck:
    def test_raw_return_caught(self):
        bad = [{"trigger": "x", "return_to_main": ["все прочитанные файлы"], "do_not_return": []}]
        assert check(bad) != []
