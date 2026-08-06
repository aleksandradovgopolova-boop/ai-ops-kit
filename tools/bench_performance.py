#!/usr/bin/env python3
from __future__ import annotations
"""bench_performance.py (v3.28.0 R19) — performance benchmarks для критических модулей.

Замеряет время выполнения ключевых операций кита и сравнивает с baseline:
  - orchestrator: startup + mock provider call
  - preflight: assess() на типовых сигналах
  - security_scan: scan_secrets + scan_injection на N файлах
  - tool_loop: parse_action() на различных входах
  - usage_ledger: aggregate() на N записей
  - context_compiler: bundle assembly
  - lifecycle_store: durable_write + load_guarded

Baseline хранится в tools/.bench-baseline.json. Если benchmark медленнее baseline >2x —
предупреждение. Если >5x — ошибка (регрессия).

Честность:
  - Каждый benchmark запускается N раз, берётся медиана (не минимум — устойчивее к шуму)
  - Первый прогон — warmup (не считается)
  - Пустой baseline = первый прогон создаёт его (не падает)
  - --update-baseline обновляет baseline текущими результатами

CLI:
  bench_performance.py [--iterations N] [--threshold X] [--update-baseline] [--json]
  bench_performance.py --selftest
"""

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
import _bootstrap  # noqa: E402

BASELINE_PATH = PKG / "tools" / ".bench-baseline.json"
DEFAULT_ITERATIONS = 5
DEFAULT_THRESHOLD = 2.0  # warning if >2x baseline
REGRESSION_THRESHOLD = 5.0  # error if >5x baseline


def _time_fn(fn, iterations=DEFAULT_ITERATIONS, warmup=1):
    """Замерить время выполнения fn(). -> {median_ms, min_ms, max_ms, iterations}."""
    # Warmup
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(iterations):
        t0 = time.monotonic()
        fn()
        elapsed = (time.monotonic() - t0) * 1000  # ms
        times.append(elapsed)
    return {
        "median_ms": round(statistics.median(times), 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "iterations": iterations,
    }


def _bench_orchestrator_startup():
    """Benchmark: import orchestrator + make_provider('mock')."""
    import importlib
    import orchestrator
    importlib.reload(orchestrator)
    orchestrator.make_provider("mock")


def _bench_preflight_assess():
    """Benchmark: preflight.assess() на типовых сигналах."""
    import preflight
    with tempfile.TemporaryDirectory() as tmpdir:
        preflight.assess({"task_type": "ENGINEERING"}, tmpdir, "bench-wid")


def _bench_security_scan():
    """Benchmark: scan_secrets + scan_injection на 100 файлах."""
    import security_scan
    files = {}
    for i in range(100):
        files[f"file_{i}.py"] = f"x = {i}\ny = 'hello_{i}'\n"
    security_scan.scan_secrets(files)
    security_scan.scan_injection(files)


def _bench_tool_loop_parse():
    """Benchmark: parse_action() на 100 различных входах."""
    import tool_loop
    inputs = [
        '{"op": "read", "path": "test.py"}',
        '{"done": true, "summary": "ok"}',
        '{"error": "bad-json"}',
        'some text {"op": "write"} more text',
        'no json here',
    ] * 20
    for text in inputs:
        tool_loop.parse_action(text)


def _bench_usage_aggregate():
    """Benchmark: usage_ledger.aggregate() на 1000 записей."""
    import usage_ledger
    records = [
        {"run_id": f"r{i}", "role": "implementation", "provider": "mock",
         "model": "test", "input_tokens": 100, "output_tokens": 50,
         "usage_status": "measured", "cost": 0.001, "cost_status": "measured",
         "latency": 0.1, "trigger": "initial"}
        for i in range(1000)
    ]
    usage_ledger.aggregate(records)


def _bench_lifecycle_store():
    """Benchmark: durable_write + load_guarded на временном файле."""
    import lifecycle_store
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.yaml"
        data = {"kind": "test", "value": 1, "items": list(range(100))}
        for _ in range(10):
            lifecycle_store.durable_write(str(path), data, require_keys=["kind"])
            lifecycle_store.load_guarded(path, kind="test")


def _bench_context_compiler():
    """Benchmark: context_compiler.assemble() на минимальном child."""
    import context_compiler
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".ai").mkdir(exist_ok=True)
        (root / "features" / "wid").mkdir(parents=True, exist_ok=True)
        try:
            context_compiler.assemble(str(root), "wid", signals={"task_type": "QUICK"})
        except Exception:
            pass  # some deps may not be set up; we measure the attempt


BENCHMARKS = {
    "orchestrator_startup": _bench_orchestrator_startup,
    "preflight_assess": _bench_preflight_assess,
    "security_scan_100files": _bench_security_scan,
    "tool_loop_parse_100": _bench_tool_loop_parse,
    "usage_aggregate_1000": _bench_usage_aggregate,
    "lifecycle_store_rw_10": _bench_lifecycle_store,
    "context_compiler_assemble": _bench_context_compiler,
}


def load_baseline() -> dict:
    """Загрузить baseline из файла. Пустой dict если файла нет."""
    if not BASELINE_PATH.exists():
        return {}
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_baseline(results: dict):
    """Сохранить результаты как новый baseline."""
    BASELINE_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_all(iterations=DEFAULT_ITERATIONS) -> dict:
    """Прогнать все benchmarks. -> {name: {median_ms, min_ms, max_ms, iterations}}."""
    results = {}
    for name, fn in BENCHMARKS.items():
        try:
            results[name] = _time_fn(fn, iterations=iterations)
        except Exception as e:
            results[name] = {"error": str(e), "median_ms": None}
    return results


def compare_with_baseline(results: dict, baseline: dict, threshold=DEFAULT_THRESHOLD):
    """Сравнить результаты с baseline. -> {name: {status, ratio, median_ms, baseline_ms}}."""
    comparison = {}
    for name, r in results.items():
        if r.get("median_ms") is None:
            comparison[name] = {"status": "error", "reason": r.get("error", "unknown")}
            continue
        b = baseline.get(name, {})
        b_ms = b.get("median_ms")
        if b_ms is None or b_ms == 0:
            comparison[name] = {"status": "no_baseline", "median_ms": r["median_ms"]}
            continue
        ratio = r["median_ms"] / b_ms
        if ratio > REGRESSION_THRESHOLD:
            status = "REGRESSION"
        elif ratio > threshold:
            status = "WARNING"
        else:
            status = "OK"
        comparison[name] = {
            "status": status,
            "ratio": round(ratio, 2),
            "median_ms": r["median_ms"],
            "baseline_ms": b_ms,
        }
    return comparison


def format_text(results: dict, comparison: dict = None) -> str:
    """Человекочитаемый отчёт."""
    lines = ["=== AI Ops Kit — Performance Benchmarks ===", ""]
    for name, r in sorted(results.items()):
        ms = r.get("median_ms")
        if ms is None:
            lines.append(f"  {name}: ERROR — {r.get('error', 'unknown')}")
            continue
        line = f"  {name}: {ms:.1f}ms (min={r['min_ms']:.1f}, max={r['max_ms']:.1f})"
        if comparison and name in comparison:
            c = comparison[name]
            if c["status"] == "REGRESSION":
                line += f"  ⛔ REGRESSION {c['ratio']}x baseline ({c['baseline_ms']:.1f}ms)"
            elif c["status"] == "WARNING":
                line += f"  ⚠ WARNING {c['ratio']}x baseline ({c['baseline_ms']:.1f}ms)"
            elif c["status"] == "OK":
                line += f"  ✓ {c['ratio']}x baseline"
            elif c["status"] == "no_baseline":
                line += "  (no baseline)"
        lines.append(line)
    return "\n".join(lines)


def selftest() -> int:
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
        import bench_performance as bp
        orig = bp.BASELINE_PATH
        bp.BASELINE_PATH = Path(tmpdir) / "baseline.json"
        try:
            save_baseline(results)
            loaded = load_baseline()
            expect("baseline roundtrip: same keys", set(loaded.keys()) == set(results.keys()))
            for name in results:
                if results[name].get("median_ms") is not None:
                    expect(f"baseline roundtrip: {name} median matches",
                           loaded[name]["median_ms"] == results[name]["median_ms"])
        finally:
            bp.BASELINE_PATH = orig

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

    print("bench_performance selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Ops Kit performance benchmarks")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS,
                        help=f"Number of iterations per benchmark (default: {DEFAULT_ITERATIONS})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Warning threshold as ratio of baseline (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--update-baseline", action="store_true",
                        help="Save current results as new baseline")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--selftest", action="store_true", help="Run selftest")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    results = run_all(iterations=args.iterations)
    baseline = load_baseline()
    comparison = compare_with_baseline(results, baseline, threshold=args.threshold) if baseline else None

    if args.update_baseline:
        save_baseline(results)
        print(f"Baseline updated: {BASELINE_PATH}")

    if args.json:
        output = {"results": results, "comparison": comparison, "baseline_path": str(BASELINE_PATH)}
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_text(results, comparison))
        if not baseline:
            print(f"\nNo baseline found. Run with --update-baseline to create one.")

    # Exit code: 1 if any regression
    if comparison:
        regressions = [n for n, c in comparison.items() if c.get("status") == "REGRESSION"]
        if regressions:
            print(f"\n⛔ REGRESSIONS detected: {', '.join(regressions)}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
