#!/usr/bin/env python3
"""bench_performance.py (v3.28.0 R19) — performance benchmarks для критических модулей.

Замеряет время выполнения ключевых операций кита и сравнивает с baseline:
  - orchestrator: startup + mock provider call
  - preflight: assess() на типовых сигналах
  - security_scan: scan_secrets + scan_injection на N файлах
  - tool_loop: parse_action() на различных входах
  - usage_ledger: aggregate() на N записей
  - context_compiler: bundle assembly
  - lifecycle_store: durable_write + load_guarded

Microbenchmark baseline хранится в ai_ops_kit/devtools/.bench-baseline.json. Если benchmark медленнее baseline >2x —
предупреждение. Если >5x — ошибка (регрессия).

Честность:
  - Каждый benchmark запускается N раз, берётся медиана (не минимум — устойчивее к шуму)
  - Первый прогон — warmup (не считается)
  - Пустой baseline = первый прогон без сравнения; запись только явно
  - --update-baseline обновляет baseline текущими результатами

CLI:
  bench_performance.py [--iterations N] [--threshold X] [--update-baseline] [--json]
  python3 -m ai_ops_kit.devtools.host_resource_cli --owner baseline-1409 -- \
    python3 -m ai_ops_kit.devtools.bench_performance --suite suite.json --output run.json

Командные серии: явный неизменяемый --baseline run.json, повторы --iterations N,
--warmup N; время/пик RSS сравниваются с --regression-threshold (по умолчанию 1.2).
Локальная серия домена ci — реплика этапов CI, не измерение GitHub Actions.
Пик RSS — максимум child-процесса, не суммарная память параллельного дерева.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
from ai_ops_kit.shared import _bootstrap  # noqa: E402

BASELINE_PATH = PKG / "ai_ops_kit" / "devtools" / ".bench-baseline.json"
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
    from ai_ops_kit.providers import orchestrator
    importlib.reload(orchestrator)
    orchestrator.make_provider("mock")


def _bench_preflight_assess():
    """Benchmark: preflight.assess() на типовых сигналах."""
    from ai_ops_kit.gates import preflight
    with tempfile.TemporaryDirectory() as tmpdir:
        preflight.assess({"task_type": "ENGINEERING"}, tmpdir, "bench-wid")


def _bench_security_scan():
    """Benchmark: scan_secrets + scan_injection на 100 файлах."""
    from ai_ops_kit.security import security_scan
    files = {}
    for i in range(100):
        files[f"file_{i}.py"] = f"x = {i}\ny = 'hello_{i}'\n"
    security_scan.scan_secrets(files)
    security_scan.scan_injection(files)


def _bench_tool_loop_parse():
    """Benchmark: parse_action() на 100 различных входах."""
    from ai_ops_kit.engine import tool_loop
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
    from ai_ops_kit.shared import usage_ledger
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
    from ai_ops_kit.shared import lifecycle_store
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.yaml"
        data = {"kind": "test", "value": 1, "items": list(range(100))}
        for _ in range(10):
            lifecycle_store.durable_write(str(path), data, require_keys=["kind"])
            lifecycle_store.load_guarded(path, kind="test")


def _bench_context_compiler():
    """Benchmark: context_compiler.assemble() на минимальном child."""
    from ai_ops_kit.context import context_compiler
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".ai").mkdir(exist_ok=True)
        (root / "features" / "wid").mkdir(parents=True, exist_ok=True)
        try:
            context_compiler.assemble(str(root), "wid", signals={"task_type": "QUICK"})
        # Причина подавления (срез ратчета, 2026-08-12): предмет замера — ВРЕМЯ попытки, а не её
        # успех. Отсутствие зависимостей стенда штатно и на измеряемую величину не влияет.
        # Это dev-инструмент, в поставку не едет (DEV_ONLY_TOOLS).
        except Exception:  # noqa: BLE001,S110 — меряем время попытки, успех здесь не предмет
            pass


BENCHMARKS = {
    "orchestrator_startup": _bench_orchestrator_startup,
    "preflight_assess": _bench_preflight_assess,
    "security_scan_100files": _bench_security_scan,
    "tool_loop_parse_100": _bench_tool_loop_parse,
    "usage_aggregate_1000": _bench_usage_aggregate,
    "lifecycle_store_rw_10": _bench_lifecycle_store,
    "context_compiler_assemble": _bench_context_compiler,
}


def load_baseline(path=None) -> dict:
    """Загрузить baseline. path=None -> BASELINE_PATH репозитория."""
    p = Path(path) if path else BASELINE_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_baseline(results: dict, path=None):
    """Сохранить результаты как baseline. path=None -> BASELINE_PATH репозитория.

    Путь берётся аргументом, а не подменой модульной глобали: селфтест запускается как
    `python3 -m ai_ops_kit.devtools.bench_performance --selftest`, то есть модулем `__main__`, и его
    `import bench_performance as bp` создавал ВТОРОЙ объект модуля. Подмена `bp.BASELINE_PATH`
    патчила копию, а save_baseline из `__main__` продолжал писать в настоящий файл репозитория —
    каждый прогон селфтеста молча переписывал baseline замерами текущей машины. Порог «медленнее
    baseline >2x» при этом переставал что-либо значить: baseline догонял любую регрессию."""
    p = Path(path) if path else BASELINE_PATH
    p.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


def run_all(iterations=DEFAULT_ITERATIONS) -> dict:
    """Прогнать все benchmarks. -> {name: {median_ms, min_ms, max_ms, iterations}}."""
    results = {}
    for name, fn in BENCHMARKS.items():
        try:
            results[name] = _time_fn(fn, iterations=iterations)
        # Правильный образец: отказ бенчмарка становится записью результата с причиной и
        # `median_ms: None` — не нулём. Тот же инвариант, что `unavailable != 0`.
        except Exception as e:  # noqa: BLE001 — отказ становится результатом с причиной
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


# --- Command suites share this harness and the existing explicit baseline workflow. ---

def load_suite(path):
    """Прочитать команды без shell; неверный план не запускает ни одной команды."""
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(suite, dict):
        raise ValueError("suite must be an object")
    cases = suite.get("cases")
    if suite.get("schema_version") != 1 or not isinstance(cases, list) or not cases:
        raise ValueError("suite requires schema_version=1 and nonempty cases")
    names = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("case must be an object")
        name, command = case.get("name"), case.get("command")
        if (not isinstance(name, str) or not name or name in names
                or case.get("domain") not in {"ci", "runtime"}
                or not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or not arg for arg in command)
                or not _positive_number(case.get("timeout_seconds"))):
            raise ValueError("case requires unique name, ci/runtime domain, argv and positive timeout")
        names.add(name)
    return suite


def _positive_number(value):
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _command_worker():
    """Один свежий измеритель на попытку: RUSAGE_CHILDREN не копится между командами."""
    import os
    import resource
    import signal
    import threading
    from ai_ops_kit.devtools import host_resource_cli

    spec = json.loads(sys.argv[1])
    command = [sys.executable if arg == "{python}" else arg for arg in spec["command"]]
    started = time.perf_counter()
    error = None
    with open(spec["stdout"], "wb") as stdout, open(spec["stderr"], "wb") as stderr:
        process = subprocess.Popen(command, cwd=spec["cwd"], stdout=stdout, stderr=stderr,
                                   start_new_session=True, **host_resource_cli.subprocess_kwargs())
        expired = []

        def expire():
            # Только собственная группа. Timer не добавляет квант polling к короткому startup.
            try:
                os.killpg(process.pid, signal.SIGKILL)
                expired.append(True)
            except ProcessLookupError:
                pass  # Процесс успел штатно завершиться на границе timeout.

        timer = threading.Timer(spec["timeout_seconds"], expire)
        timer.daemon = True
        timer.start()
        try:
            code = process.wait()
        finally:
            timer.cancel()
            timer.join()
        error = "timeout" if expired else None
    elapsed_ms = (time.perf_counter() - started) * 1000
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    print(json.dumps({"elapsed_ms": elapsed_ms, "peak_rss_bytes": int(usage.ru_maxrss *
                     (1 if sys.platform == "darwin" else 1024)),
                     "cpu_seconds": usage.ru_utime + usage.ru_stime, "returncode": code,
                     "error": error or (f"exit {code}" if code else None)}))


def measure_command(case, root, log_prefix):
    """Время команды включает создание процесса и ожидание, исключает запуск worker."""
    import subprocess
    from ai_ops_kit.devtools import host_resource_cli

    spec = {**case, "cwd": str(root), "stdout": str(log_prefix) + ".stdout.log",
            "stderr": str(log_prefix) + ".stderr.log"}
    worker = subprocess.run([sys.executable, "-c",
                             "from ai_ops_kit.devtools.bench_performance import _command_worker; _command_worker()",
                             json.dumps(spec)], cwd=PKG, capture_output=True, text=True,
                            timeout=case["timeout_seconds"] + 30, **host_resource_cli.subprocess_kwargs())
    if worker.returncode:
        raise RuntimeError(f"measurement worker exit {worker.returncode}: {worker.stderr.strip()}")
    return {**json.loads(worker.stdout), "stdout": spec["stdout"], "stderr": spec["stderr"]}


def suite_metadata(root, suite, iterations, warmup):
    """Исходники, toolchain и безопасный allowlist среды; секреты окружения не сохраняются."""
    import hashlib
    import importlib.metadata
    import os
    import platform
    import subprocess
    from datetime import datetime, timezone

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)

    sha = git("rev-parse", "HEAD").decode().strip()
    diff = git("diff", "--binary", "HEAD", "--")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    fingerprint = hashlib.sha256(diff)
    for path in sorted(p for p in untracked if p):
        fingerprint.update(path)
        fingerprint.update(hashlib.sha256((Path(root) / os.fsdecode(path)).read_bytes()).digest())
    environment = {
        "platform": platform.platform(), "machine": platform.machine(), "host": platform.node(),
        "python": platform.python_version(), "implementation": platform.python_implementation(),
        "executable": sys.executable, "cpu_count": os.cpu_count(),
        "packages": sorted([d.metadata["Name"], d.version] for d in importlib.metadata.distributions()),
        "variables": {key: os.environ.get(key) for key in
                      ("PATH", "PYTHONHASHSEED", "PYTEST_ADDOPTS", "PYTHONPATH", "PYTHON", "AI_OPS_PYTHON",
                       "LC_ALL", "LANG", "TZ", "OMP_NUM_THREADS", "CI")},
    }
    return {"sha": sha, "dirty": bool(git("status", "--porcelain")),
            "dirty_sha256": fingerprint.hexdigest(), "environment": environment,
            "suite_sha256": hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(),
            "iterations": iterations, "warmup": warmup,
            "started_at": datetime.now(timezone.utc).isoformat(), "load_average": os.getloadavg(),
            "execution_context": "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
            "ci_run_id": os.environ.get("GITHUB_RUN_ID"), "ci_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "memory_semantics": "RUSAGE_CHILDREN ru_maxrss; max child RSS, not sum of concurrent process RSS"}


def run_suite(suite, root, log_directory, iterations=DEFAULT_ITERATIONS, warmup=1):
    """Последовательные повторы, включая ошибочные; warmup сохраняется отдельно."""
    if not isinstance(iterations, int) or iterations < 1 or not isinstance(warmup, int) or warmup < 0:
        raise ValueError("iterations must be positive and warmup nonnegative")
    metadata = suite_metadata(root, suite, iterations, warmup)
    Path(log_directory).mkdir(parents=True, exist_ok=False)
    results = {}
    for index, case in enumerate(suite["cases"]):
        samples = []
        for attempt in range(warmup + iterations):
            prefix = Path(log_directory).resolve() / f"case-{index}-attempt-{attempt}"
            try:
                sample = measure_command(case, root, prefix)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                sample = {"error": str(exc), "returncode": None}
            samples.append({**sample, "attempt": attempt + 1, "warmup": attempt < warmup})
        measured = samples[warmup:]
        successful = all(not sample.get("error") and sample.get("returncode") == 0 for sample in samples)
        results[case["name"]] = {"domain": case["domain"], "command": case["command"], "cwd": str(Path(root).resolve()),
                                 "timeout_seconds": case["timeout_seconds"], "samples": samples, "iterations": iterations,
                                 "command_attempts": len(samples), "repeat_count": len(samples) - 1,
                                 "status": "measured" if successful else "error"}
        for field, source in (("median_ms", "elapsed_ms"), ("median_peak_rss_bytes", "peak_rss_bytes"),
                              ("median_cpu_seconds", "cpu_seconds")):
            results[case["name"]][field] = statistics.median(s[source] for s in measured) if successful else None
    return {"schema_version": 1, "metadata": metadata, "suite": suite, "results": results}


def compare_suites(current, baseline, threshold=1.2):
    """Несопоставимость/ошибка/потеря метрики запрещает зелёный результат."""
    if not _positive_number(threshold) or threshold <= 1:
        raise ValueError("regression threshold must exceed 1")
    for receipt in (current, baseline):
        if (not isinstance(receipt, dict) or receipt.get("schema_version") != 1
                or not isinstance(receipt.get("metadata"), dict)
                or not isinstance(receipt.get("results"), dict) or not receipt["results"]):
            return {"status": "INVALID", "reason": "missing command-suite receipt"}
    for key in ("environment", "suite_sha256", "iterations", "warmup", "execution_context", "memory_semantics"):
        if current["metadata"].get(key) is None or current["metadata"].get(key) != baseline["metadata"].get(key):
            return {"status": "INCOMPARABLE", "reason": f"metadata differs: {key}"}
    if set(current["results"]) != set(baseline["results"]):
        return {"status": "INCOMPARABLE", "reason": "case set differs"}
    comparisons = {}
    for name, result in current["results"].items():
        old = baseline["results"][name]
        if result.get("status") != "measured" or old.get("status") != "measured":
            return {"status": "ERROR", "reason": f"failed case: {name}"}
        ratios = {}
        for metric in ("median_ms", "median_peak_rss_bytes"):
            if not _positive_number(result.get(metric)) or not _positive_number(old.get(metric)):
                return {"status": "INVALID", "reason": f"missing/invalid {name}.{metric}"}
            ratios[metric] = result[metric] / old[metric]
        comparisons[name] = {"status": "REGRESSION" if max(ratios.values()) > threshold else "OK", "ratios": ratios}
    return {"status": "REGRESSION" if any(c["status"] == "REGRESSION" for c in comparisons.values()) else "OK",
            "threshold": threshold, "cases": comparisons}


def command_suite_main(args, parser):
    from ai_ops_kit.devtools import host_resource_cli

    if not args.output:
        parser.error("--suite requires --output (a new receipt file)")
    output = Path(args.output).resolve()
    if output.exists() or (args.baseline and output == Path(args.baseline).resolve()):
        parser.error("output must be new and distinct from baseline")
    if args.update_baseline:
        parser.error("command suites keep the baseline immutable; select a receipt using --baseline")
    try:
        suite = load_suite(args.suite)
        if (args.iterations < 1 or args.warmup < 0 or not _positive_number(args.regression_threshold)
                or args.regression_threshold <= 1):
            raise ValueError("positive iterations, nonnegative warmup and threshold >1 required")
        baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
        # Не запускаем произвольные серии без реального общего lease. Wrapper проверяет нагрузку.
        if host_resource_cli.inherited_slot() is None:
            raise ValueError("command suite requires host_resource_cli shared slot")
        receipt = run_suite(suite, PKG, output.with_suffix(".logs"), args.iterations, args.warmup)
        receipt["comparison"] = compare_suites(receipt, baseline, args.regression_threshold) if baseline is not None else None
        receipt["status"] = (receipt["comparison"]["status"] if receipt["comparison"] else
                             "NO_BASELINE" if all(r["status"] == "measured" for r in receipt["results"].values()) else "ERROR")
        output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "receipt": str(output)}, ensure_ascii=False))
    return 0 if receipt["status"] in {"OK", "NO_BASELINE"} else 1


def main(argv=None):
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
    parser.add_argument("--suite", type=Path, help="JSON command suite (requires shared host slot)")
    parser.add_argument("--output", type=Path, help="New command-suite receipt; logs saved beside it")
    parser.add_argument("--baseline", type=Path, help="Explicit immutable command-suite baseline receipt")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup commands per case, also recorded")
    parser.add_argument("--regression-threshold", type=float, default=1.2, help="Command time/RSS failure ratio")
    args = parser.parse_args(argv)
    if args.suite:
        return command_suite_main(args, parser)
    if args.output or args.baseline:
        parser.error("--output/--baseline require --suite")
    if args.iterations < 1:
        parser.error("--iterations must be positive")

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
