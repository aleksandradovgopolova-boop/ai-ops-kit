"""Гранулярные тесты effect_metrics (мигрировано из test_effect_metrics_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json
import tempfile

import pytest

from effect_metrics import (
    Path,
    build,
)


@pytest.fixture
def history_dir():
    with tempfile.TemporaryDirectory() as td:
        h = Path(td)

        def entry(ts, verdict, stage, filled):
            return json.dumps({"schema_version": 1, "ts": ts, "feature": "f",
                               "verdict": verdict, "current_stage": stage,
                               "coverage": {"filled": filled}, "problems": 0, "warns": 0})

        (h / "feat-a.jsonl").write_text("\n".join([
            entry("2026-07-01T10:00:00+00:00", "PROBLEM", "discovery", 1),
            entry("2026-07-04T10:00:00+00:00", "WARN", "delivery", 5),
            entry("2026-07-08T10:00:00+00:00", "OK", "retrospective", 9),
        ]) + "\n", encoding="utf-8")
        (h / "feat-b.jsonl").write_text(
            entry("2026-07-09T10:00:00+00:00", "OK", "definition", 3) + "\n",
            encoding="utf-8")
        yield h


@pytest.mark.unit
class TestBuildPerFeature:
    def test_feat_a_sufficient(self, history_dir):
        r = build(history_dir)
        assert r["per_feature"]["feat-a"]["sufficient"] is True

    def test_feat_a_problem_rate(self, history_dir):
        r = build(history_dir)
        assert r["per_feature"]["feat-a"]["problem_rate"] == 0.33

    def test_feat_a_period_days(self, history_dir):
        r = build(history_dir)
        assert r["per_feature"]["feat-a"]["period_days"] == 7.0

    def test_feat_a_stages_advanced(self, history_dir):
        r = build(history_dir)
        assert r["per_feature"]["feat-a"]["stages_advanced"] == 10

    def test_feat_b_insufficient(self, history_dir):
        r = build(history_dir)
        assert r["per_feature"]["feat-b"]["sufficient"] is False


@pytest.mark.unit
class TestBuildAggregate:
    def test_median_days_to_retrospective(self, history_dir):
        r = build(history_dir)
        assert r["aggregate"]["median_days_to_retrospective"] == 7.0

    def test_baseline_not_ready(self, history_dir):
        r = build(history_dir)
        assert r["aggregate"]["baseline_ready"] is False
