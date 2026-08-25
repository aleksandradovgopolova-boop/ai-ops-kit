"""Гранулярные тесты semantic_lite (мигрировано из test_semantic_lite_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from semantic_lite import (
    Path,
    build_index,
    search,
)


@pytest.fixture
def small_index():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "repo").mkdir()
        (root / "repo" / "relevant.py").write_text(
            "def f():\n    rebate = 1\n    return rebate\n", encoding="utf-8")
        (root / "repo" / "noise.py").write_text(
            "def g():\n    return 0\n    return 0\n    return 0\n    return 0\n", encoding="utf-8")
        (root / "repo" / "other.py").write_text(
            "def h():\n    return 1\n", encoding="utf-8")
        yield build_index(root, ("repo",))


@pytest.mark.unit
class TestTfIdfRanking:
    def test_rare_term_boosts_relevant(self, small_index):
        res = search(small_index, "return rebate", k=3)
        top = [r["file"] for r in res]
        assert top and top[0] == "repo/relevant.py"

    def test_noise_ranked_lower(self, small_index):
        res = search(small_index, "return rebate", k=3)
        top = [r["file"] for r in res]
        if "repo/noise.py" in top:
            assert top.index("repo/noise.py") > top.index("repo/relevant.py")

    def test_rare_word_only(self, small_index):
        r2 = [x["file"] for x in search(small_index, "rebate", k=3)]
        assert r2 == ["repo/relevant.py"]

    def test_scores_in_range(self, small_index):
        res = search(small_index, "return rebate", k=3)
        assert all(0 < r["score"] <= 1.0001 for r in res)


@pytest.mark.slow
@pytest.mark.unit
class TestRealIndex:
    def test_real_index_builds(self):
        real = build_index()
        assert real["n"] > 50

    def test_budget_query(self):
        real = build_index()
        rr = search(real, "budget contract enforcement", k=5)
        assert any("budget" in r["file"] for r in rr)
