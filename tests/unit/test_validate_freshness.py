"""Granular tests for validate_freshness (migrated from selftest)."""
from __future__ import annotations

import tempfile

import pytest

from validate_freshness import (
    Path,
    _default_child_context,
    assess,
    date,
)


@pytest.fixture
def today():
    return date(2026, 7, 13)


# --- Stability assessments ---

class TestStabilityAssessments:
    @pytest.mark.unit
    def test_stable_never_expires(self, today):
        assert assess({"stability": "stable", "reviewed_at": "2020-01-01"}, today)[0] == "ok"

    @pytest.mark.unit
    def test_volatile_35d_ago_is_stale(self, today):
        assert assess({"stability": "volatile", "reviewed_at": "2026-06-08"}, today)[0] == "stale"

    @pytest.mark.unit
    def test_volatile_3d_ago_is_fresh(self, today):
        assert assess({"stability": "volatile", "reviewed_at": "2026-07-10"}, today)[0] == "ok"

    @pytest.mark.unit
    def test_evolving_100d_ago_is_stale(self, today):
        assert assess({"stability": "evolving", "reviewed_at": "2026-04-04"}, today)[0] == "stale"

    @pytest.mark.unit
    def test_no_reviewed_at_returns_warn(self, today):
        assert assess({"stability": "volatile"}, today)[0] == "no-review-date"

    @pytest.mark.unit
    def test_without_stability_returns_none(self, today):
        assert assess({"title": "x"}, today) is None

    @pytest.mark.unit
    def test_custom_expires_after_days_respected(self, today):
        assert assess({"stability": "evolving", "reviewed_at": "2026-07-01",
                       "expires_after_days": 5}, today)[0] == "stale"


# --- Template and default context (v3.12.0) ---

class TestTemplateAndContext:
    @pytest.mark.unit
    def test_template_true_is_not_checked(self, today):
        assert assess({"template": True, "stability": "volatile",
                       "reviewed_at": "2020-01-01"}, today) is None

    @pytest.mark.unit
    def test_default_context_is_project_context(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / ".ai/project/context").mkdir(parents=True)
            assert _default_child_context(base) == (base / ".ai/project/context").resolve()

    @pytest.mark.unit
    def test_default_context_falls_back_to_custom(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / ".ai/custom/context").mkdir(parents=True)
            assert _default_child_context(base) == (base / ".ai/custom/context").resolve()
