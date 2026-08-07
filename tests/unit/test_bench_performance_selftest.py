"""Селфтест bench_performance, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from bench_performance import (  # noqa: F401 — имена, которые использует тело
    BASELINE_PATH,
    BENCHMARKS,
    Path,
    compare_with_baseline,
    format_text,
    load_baseline,
    run_all,
    save_baseline,
    tempfile,
)


@pytest.mark.slow
def test_bench_performance_selftest():
    """Selftest: benchmarks запускаются, результаты — положительные числа."""
    ok = True

    def expect(label: str, cond: bool):
        nonlocal ok
        if not cond:
            print(f"  FAIL: {label}")
            ok = False

    # 1. Все benchmarks возвращают результаты
    results = run_all(iterations=2)
    expect("all benchmarks returned", len(results) == len(BENCHMARKS))

    # 2. Каждый результат — dict с median_ms
    for name, r in results.items():
        if r.get("error"):
            continue  # some benchmarks may fail in minimal env
        expect(f"{name}: median_ms is number",
               isinstance(r.get("median_ms"), (int, float)) and r["median_ms"] >= 0)

    # 3. Baseline save/load roundtrip
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_baseline = Path(tmpdir) / "baseline.json"
        save_baseline(results, tmp_baseline)
        loaded = load_baseline(tmp_baseline)
        expect("baseline roundtrip: same keys", set(loaded.keys()) == set(results.keys()))
        for name in results:
            if results[name].get("median_ms") is not None:
                expect(f"baseline roundtrip: {name} median matches",
                       loaded[name]["median_ms"] == results[name]["median_ms"])
        expect("selftest НЕ трогает baseline репозитория", not tmp_baseline.samefile(BASELINE_PATH)
               if BASELINE_PATH.exists() else True)

    # 4. Comparison logic
    baseline = {"test_bench": {"median_ms": 10.0}}
    comparison = compare_with_baseline(
        {"test_bench": {"median_ms": 15.0, "min_ms": 14.0, "max_ms": 16.0, "iterations": 3}},
        baseline, threshold=2.0
    )
    expect("comparison: 1.5x is OK", comparison["test_bench"]["status"] == "OK")

    comparison2 = compare_with_baseline(
        {"test_bench": {"median_ms": 25.0, "min_ms": 24.0, "max_ms": 26.0, "iterations": 3}},
        baseline, threshold=2.0
    )
    expect("comparison: 2.5x is WARNING", comparison2["test_bench"]["status"] == "WARNING")

    comparison3 = compare_with_baseline(
        {"test_bench": {"median_ms": 60.0, "min_ms": 59.0, "max_ms": 61.0, "iterations": 3}},
        baseline, threshold=2.0
    )
    expect("comparison: 6x is REGRESSION", comparison3["test_bench"]["status"] == "REGRESSION")

    # 5. format_text
    text = format_text(results)
    expect("format_text: has header", "Performance Benchmarks" in text)

    assert ok, "перенесённый селфтест bench_performance: см. строки FAIL в выводе"
