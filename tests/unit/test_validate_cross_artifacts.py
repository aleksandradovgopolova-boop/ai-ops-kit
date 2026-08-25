"""Гранулярные тесты validate_cross_artifacts (миграция с селфтеста)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_cross_artifacts import (
    DASHBOARD,
    DS_BAD,
    DS_OK,
    TP_OK,
    TRACKING,
    check_feature,
)


@pytest.fixture
def feature_dir():
    """Возвращает фабрику для создания тестовых feature-директорий."""
    with tempfile.TemporaryDirectory() as td:
        def mk(name, tp=None, ds=None):
            d = Path(td) / name
            (d / "analytics").mkdir(parents=True)
            if tp is not None:
                (d / TRACKING).write_text(tp, encoding="utf-8")
            if ds is not None:
                (d / DASHBOARD).write_text(ds, encoding="utf-8")
            return d
        yield mk


@pytest.mark.unit
@pytest.mark.slow
class TestCrossArtifactsValidation:

    def test_consistent_pair_is_clean(self, feature_dir):
        p, w, s = check_feature(feature_dir("a", TP_OK, DS_OK))
        assert (len(p), len(w)) == (0, 0)

    def test_undeclared_event_in_dashboard_is_problem(self, feature_dir):
        p, _, _ = check_feature(feature_dir("b", TP_OK, DS_BAD))
        assert len(p) > 0

    def test_no_dashboard_spec_is_skip(self, feature_dir):
        p, _, s = check_feature(feature_dir("c", TP_OK, None))
        assert len(p) == 0 and s is not None

    def test_dashboard_without_tracking_plan_is_problem(self, feature_dir):
        p, _, _ = check_feature(feature_dir("d", None, DS_OK))
        assert len(p) == 1

    def test_unparseable_tracking_plan_is_warn_not_fail(self, feature_dir):
        p, w, _ = check_feature(feature_dir("e", "# Tracking Plan\nбез таблицы\n", DS_OK))
        assert (len(p), len(w)) == (0, 1)
