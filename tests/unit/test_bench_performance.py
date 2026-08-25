"""Unit tests for tools/bench_performance.py — performance benchmarks."""
from __future__ import annotations

import json

import pytest

import bench_performance


@pytest.mark.unit
class TestRunAll:
    """Tests for run_all(): execute all benchmarks and collect results."""

    def test_all_benchmarks_return_results(self):
        """run_all() returns dict with all benchmark names."""
        results = bench_performance.run_all(iterations=1)
        assert isinstance(results, dict)
        assert set(results.keys()) == set(bench_performance.BENCHMARKS.keys())

    def test_benchmark_result_has_median_ms(self):
        """Each result dict contains a median_ms key."""
        results = bench_performance.run_all(iterations=1)
        for name, r in results.items():
            assert "median_ms" in r, f"{name} missing median_ms"

    def test_benchmark_median_ms_is_nonnegative_number(self):
        """Перенесено из монолита (прополка): median_ms — число >= 0, а не только присутствующий
        ключ. Наличие ключа не отличает измеренное 0.0 от строки/None/отрицательного мусора."""
        results = bench_performance.run_all(iterations=1)
        for name, r in results.items():
            assert isinstance(r["median_ms"], (int, float)), f"{name}: median_ms не число"
            assert r["median_ms"] >= 0, f"{name}: median_ms отрицателен"


@pytest.mark.unit
class TestBaseline:
    """Tests for baseline save/load roundtrip."""

    def test_baseline_save_load_roundtrip(self, tmp_path):
        """save then load returns same data."""
        fake_path = tmp_path / "baseline.json"
        orig = bench_performance.BASELINE_PATH
        bench_performance.BASELINE_PATH = fake_path
        try:
            data = {
                "bench_a": {"median_ms": 1.234, "min_ms": 1.0, "max_ms": 1.5, "iterations": 3},
                "bench_b": {"median_ms": 5.678, "min_ms": 5.0, "max_ms": 6.0, "iterations": 3},
            }
            bench_performance.save_baseline(data)
            loaded = bench_performance.load_baseline()
            assert set(loaded.keys()) == set(data.keys())
            for name in data:
                assert loaded[name]["median_ms"] == data[name]["median_ms"]
        finally:
            bench_performance.BASELINE_PATH = orig


@pytest.mark.unit
class TestCompareWithBaseline:
    """Tests for compare_with_baseline(): ratio-based status classification."""

    def test_compare_with_baseline_ok(self):
        """ratio < threshold → OK."""
        baseline = {"b1": {"median_ms": 10.0}}
        results = {"b1": {"median_ms": 15.0, "min_ms": 14.0, "max_ms": 16.0, "iterations": 3}}
        comparison = bench_performance.compare_with_baseline(results, baseline, threshold=2.0)
        assert comparison["b1"]["status"] == "OK"

    def test_compare_with_baseline_warning(self):
        """ratio > threshold but <= 5x → WARNING."""
        baseline = {"b1": {"median_ms": 10.0}}
        results = {"b1": {"median_ms": 25.0, "min_ms": 24.0, "max_ms": 26.0, "iterations": 3}}
        comparison = bench_performance.compare_with_baseline(results, baseline, threshold=2.0)
        assert comparison["b1"]["status"] == "WARNING"

    def test_compare_with_baseline_regression(self):
        """ratio > 5x → REGRESSION."""
        baseline = {"b1": {"median_ms": 10.0}}
        results = {"b1": {"median_ms": 60.0, "min_ms": 59.0, "max_ms": 61.0, "iterations": 3}}
        comparison = bench_performance.compare_with_baseline(results, baseline, threshold=2.0)
        assert comparison["b1"]["status"] == "REGRESSION"


@pytest.mark.unit
class TestFormatText:
    """Tests for format_text(): human-readable report."""

    def test_format_text_has_header(self):
        """Output contains 'Performance Benchmarks'."""
        results = {"b1": {"median_ms": 1.0, "min_ms": 0.5, "max_ms": 1.5, "iterations": 3}}
        text = bench_performance.format_text(results)
        assert "Performance Benchmarks" in text


# TestSelftest удалён: тело переехало в tests/unit/test_bench_performance_selftest.py
