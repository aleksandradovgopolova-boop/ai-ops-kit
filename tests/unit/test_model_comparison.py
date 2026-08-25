"""Гранулярные тесты model_comparison (мигрировано из test_model_comparison_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from model_comparison import (
    DEMO,
    SCHEMA,
    _load_dir,
    check,
    compare,
    json,
)


def _mbr(model, tier, total, passed, fg, ff, cost):
    return {
        "kind": "ModelBenchResult", "model": model, "provider": "p", "task_tier": tier,
        "quality": {"total": total, "pass": passed, "false_green": fg, "false_fail": ff,
                     "fix_recovered": 0},
        "economics": {"tokens": None, "cost_usd": cost, "latency_s": None},
    }


@pytest.mark.unit
class TestSchemaValidation:
    def test_example_from_schema_is_valid(self):
        ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
        assert check(ex) == []

    def test_pass_greater_than_total_raises_error(self):
        ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
        bad = {**ex, "quality": {"total": 1, "pass": 2, "false_green": 0, "false_fail": 0, "fix_recovered": 0}}
        results = check(bad)
        assert any("pass > total" in x for x in results)


@pytest.mark.unit
class TestCompareEngineering:
    @pytest.fixture(autouse=True)
    def setup_results(self):
        self.res = [
            _mbr("strong", "ENGINEERING", 10, 9, 0, 1, 0.50),
            _mbr("weak", "ENGINEERING", 10, 3, 0, 0, 0.02),
            _mbr("unsafe-cheap", "ENGINEERING", 10, 10, 2, 0, 0.001),
        ]
        self.cmp = compare(self.res)
        self.eng = self.cmp["tiers"]["ENGINEERING"]

    def test_unsafe_disqualified(self):
        assert any(d["model"] == "unsafe-cheap" for d in self.eng["disqualified"])
        assert all(r["model"] != "unsafe-cheap" for r in self.eng["ranked"])

    def test_strong_recommended(self):
        assert self.eng["recommended"] == "strong"

    def test_ranking_order(self):
        assert [r["model"] for r in self.eng["ranked"]] == ["strong", "weak"]


@pytest.mark.unit
class TestCompareQuick:
    def test_cheaper_recommended_at_equal_quality(self):
        res = [
            _mbr("strong", "QUICK", 5, 5, 0, 0, 0.30),
            _mbr("weak", "QUICK", 5, 5, 0, 0, 0.01),
        ]
        q = compare(res)["tiers"]["QUICK"]
        assert q["recommended"] == "weak"


@pytest.mark.unit
class TestCompareFailClosed:
    def test_all_unsafe_returns_no_recommendation(self):
        allbad = compare([_mbr("a", "UI", 5, 5, 1, 0, 0.1)])["tiers"]["UI"]
        assert allbad["recommended"] is None


@pytest.mark.unit
class TestDemoData:
    def test_real_demo_data_is_valid(self):
        real = _load_dir(DEMO)
        assert len(real) >= 1
        assert all(check(r) == [] for r in real)
