"""Гранулярные тесты retrieval_bench (мигрировано из test_retrieval_bench_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.devtools.retrieval_bench import (
    Path,
    run_bench,
)


@pytest.fixture
def bench_setup():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "repo").mkdir()
        fixture = {
            "pricing.py": '"""apply discount pricing."""\ndef apply_discount(a):\n    return a*0.9\ndef total(a):\n    return a\n',
            "checkout.py": 'import pricing\n\ndef checkout(a):\n    return pricing.total(a)\n',
            "order.py": 'import checkout\n\ndef place():\n    return checkout.checkout(1)\n',
            "rebate.py": '"""rebate calculation."""\ndef rebate(a):\n    return a\n',
            "auth.py": '"""authentication login token handling."""\ndef login(u, p):\n    return True\n',
            "session.py": 'import auth\n\ndef session():\n    return auth.login("a", "b")\n',
            "catalog.py": '"""product catalog listing."""\ndef list_items():\n    return []\n',
            "report.py": '"""weekly report generation."""\ndef report():\n    return {}\n',
            "skidka.py": '"""расчёт скидки на заказ (RU)."""\ndef primenit_skidku(s):\n    return s\n',
            "legacy.py": '"""DEPRECATED устаревшее решение по ценам."""\ndef old_pricing():\n    pass\n',
            "noise.py": 'def f():\n    return f()\ndef g():\n    return g()\n',
        }
        for name, content in fixture.items():
            (root / "repo" / name).write_text(content, encoding="utf-8")

        golden = [
            {"query": "discount", "relevant": ["repo/pricing.py", "repo/checkout.py"]},
            {"query": "pricing", "relevant": ["repo/pricing.py"]},
            {"query": "checkout", "relevant": ["repo/checkout.py"]},
            {"query": "total", "relevant": ["repo/pricing.py"]},
            {"query": "rebate", "relevant": ["repo/rebate.py"]},
            {"query": "login", "relevant": ["repo/auth.py"]},
            {"query": "token", "relevant": ["repo/auth.py"]},
            {"query": "session", "relevant": ["repo/session.py", "repo/auth.py"]},
            {"query": "authentication", "relevant": ["repo/auth.py"]},
            {"query": "catalog", "relevant": ["repo/catalog.py"]},
            {"query": "report", "relevant": ["repo/report.py"]},
            {"query": "скидк", "relevant": ["repo/skidka.py"]},
            {"query": "устаревшее", "relevant": ["repo/legacy.py"]},
            {"query": "deprecated", "relevant": ["repo/legacy.py"]},
            {"query": "order place", "relevant": ["repo/order.py"]},
            {"query": "quantum", "relevant": []},
        ]
        yield root, golden


@pytest.mark.slow
@pytest.mark.unit
class TestRetrievalBench:
    def test_corpus_size(self, bench_setup):
        _, golden = bench_setup
        assert len(golden) >= 15

    def test_all_strategies_metrics_in_range(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        for s in ("fulltext", "graph_augmented", "semantic_lite"):
            m = rep["strategies"][s]
            assert 0 <= m["precision"] <= 1
            assert 0 <= m["recall"] <= 1
            assert 0 <= m["f1"] <= 1

    def test_graph_augmented_recall_ge_fulltext(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        ft = rep["strategies"]["fulltext"]
        ga = rep["strategies"]["graph_augmented"]
        assert ga["recall"] >= ft["recall"]

    def test_dep_case_graph_finds_checkout(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        ft = rep["strategies"]["fulltext"]
        ga = rep["strategies"]["graph_augmented"]
        q0_ft = ft["per_query"][0]["retrieved"]
        q0_ga = ga["per_query"][0]["retrieved"]
        assert "repo/checkout.py" in q0_ga
        assert "repo/checkout.py" not in q0_ft

    def test_rare_term_semantic_lite(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        sm = rep["strategies"]["semantic_lite"]
        q_reb = next(q for q in sm["per_query"] if q["query"] == "rebate")
        assert q_reb["recall"] == 1.0

    def test_ru_query_found(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        assert any(
            "repo/skidka.py" in q["retrieved"]
            for s in (rep["strategies"]["fulltext"], rep["strategies"]["graph_augmented"],
                      rep["strategies"]["semantic_lite"])
            for q in s["per_query"] if q["query"] == "скидк")

    def test_noise_no_false_relevant(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        for s_name in ("fulltext", "graph_augmented", "semantic_lite"):
            q = next(q for q in rep["strategies"][s_name]["per_query"] if q["query"] == "quantum")
            assert q["recall"] == 0.0

    def test_best_by_f1_defined(self, bench_setup):
        root, golden = bench_setup
        rep = run_bench(root, golden, ("repo",))
        assert rep["best_by_f1"] in ("fulltext", "graph_augmented", "semantic_lite")
