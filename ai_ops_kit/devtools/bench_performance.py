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
    return _validate_suite(json.loads(Path(path).read_text(encoding="utf-8")))


def _validate_suite(suite):
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


class _LeaseLost(ValueError):
    """Команда не должна стартовать без того же настоящего host-slot."""


def _lease_subprocess_kwargs():
    from ai_ops_kit.devtools import host_resource_cli
    fd = host_resource_cli.inherited_slot()
    if fd is None:
        raise _LeaseLost("shared host-slot lost or unavailable")
    return {"pass_fds": (fd,)}


def _command_worker():
    """Один свежий измеритель на попытку: RUSAGE_CHILDREN не копится между командами."""
    import resource
    import threading

    spec = json.loads(sys.argv[1])
    command = [sys.executable if arg == "{python}" else arg for arg in spec["command"]]
    started = time.perf_counter()
    error = None
    with open(spec["stdout"], "wb") as stdout, open(spec["stderr"], "wb") as stderr:
        process = subprocess.Popen(command, cwd=spec["cwd"], stdout=stdout, stderr=stderr,
                                   **_lease_subprocess_kwargs())
        expired = []

        def expire():
            # Внешний supervisor очистит всю собственную session перед возвратом sample.
            try:
                process.kill()
            except ProcessLookupError:
                expired.append(False)  # Процесс завершился на границе timeout.
            else:
                expired.append(True)

        timer = threading.Timer(spec["timeout_seconds"], expire)
        timer.daemon = True
        timer.start()
        try:
            code = process.wait()
        finally:
            timer.cancel()
            timer.join()
        error = "timeout" if any(expired) else None
    elapsed_ms = (time.perf_counter() - started) * 1000
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    print(json.dumps({"elapsed_ms": elapsed_ms, "peak_rss_bytes": int(usage.ru_maxrss *
                     (1 if sys.platform == "darwin" else 1024)),
                     "cpu_seconds": usage.ru_utime + usage.ru_stime, "returncode": code,
                     "error": error or (f"exit {code}" if code else None)}))


def measure_command(case, root, log_prefix):
    """Время команды включает создание процесса и ожидание, исключает запуск worker."""
    import os
    import signal

    spec = {**case, "cwd": str(root), "stdout": str(log_prefix) + ".stdout.log",
            "stderr": str(log_prefix) + ".stderr.log"}
    worker = subprocess.Popen([sys.executable, "-c",
                             "from ai_ops_kit.devtools.bench_performance import _command_worker; _command_worker()",
                             json.dumps(spec)], cwd=PKG, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True, **_lease_subprocess_kwargs())
    try:
        stdout, stderr = worker.communicate(timeout=case["timeout_seconds"] + 30)
    finally:
        # PGID получен из только что созданного собственного supervisor. Чужие группы не ищем.
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            leftover = False  # Собственная группа уже полностью завершилась.
        else:
            leftover = True
        worker.communicate()
    if worker.returncode:
        if "_LeaseLost" in stderr:
            raise _LeaseLost("shared host-slot lost in measurement worker")
        raise RuntimeError(f"measurement worker exit {worker.returncode}: {stderr.strip()}")
    sample = json.loads(stdout)
    if leftover and not sample.get("error"):
        sample["error"] = "background descendants outlived command"
    return {**sample, "stdout": spec["stdout"], "stderr": spec["stderr"]}


def suite_metadata(root, suite, iterations, warmup):
    """Исходники, toolchain и безопасный allowlist среды; секреты окружения не сохраняются."""
    import hashlib
    import importlib.metadata
    import os
    import platform
    import subprocess
    from datetime import datetime, timezone

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, timeout=15)

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
    if type(iterations) is not int or iterations < 1 or type(warmup) is not int or warmup < 0:
        raise ValueError("iterations must be positive and warmup nonnegative")
    _validate_suite(suite)
    _lease_subprocess_kwargs()
    metadata = suite_metadata(root, suite, iterations, warmup)
    Path(log_directory).mkdir(parents=True, exist_ok=False)
    results, lease_lost = {}, False
    for index, case in enumerate(suite["cases"]):
        samples = []
        for attempt in range(warmup + iterations):
            if lease_lost:
                break
            prefix = Path(log_directory).resolve() / f"case-{index}-attempt-{attempt}"
            try:
                sample = measure_command(case, root, prefix)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                sample = {"error": str(exc), "returncode": None}
                lease_lost = isinstance(exc, _LeaseLost)
            samples.append({**sample, "attempt": attempt + 1, "warmup": attempt < warmup})
        measured = samples[warmup:]
        successful = (len(samples) == warmup + iterations
                      and all(not sample.get("error") and sample.get("returncode") == 0 for sample in samples))
        results[case["name"]] = {"domain": case["domain"], "command": case["command"], "cwd": str(Path(root).resolve()),
                                 "timeout_seconds": case["timeout_seconds"], "samples": samples, "iterations": iterations,
                                 "command_attempts": len(samples), "repeat_count": max(0, len(samples) - 1),
                                 "status": "measured" if successful else "error"}
        for field, source in (("median_ms", "elapsed_ms"), ("median_peak_rss_bytes", "peak_rss_bytes"),
                              ("median_cpu_seconds", "cpu_seconds")):
            results[case["name"]][field] = statistics.median(s[source] for s in measured) if successful else None
    return {"schema_version": 1, "metadata": metadata, "suite": suite, "results": results}


def _validate_receipt(receipt):
    """Полный source/command/sample binding; агрегаты не заменяют выполненные попытки."""
    import hashlib
    import re
    from datetime import datetime

    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise ValueError("missing command-suite receipt")
    metadata = receipt.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("missing metadata")
    for key, length in (("sha", 40), ("dirty_sha256", 64), ("suite_sha256", 64)):
        if not isinstance(metadata.get(key), str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", metadata[key]):
            raise ValueError(f"invalid source binding: {key}")
    if (type(metadata.get("dirty")) is not bool or type(metadata.get("iterations")) is not int
            or metadata["iterations"] < 1 or type(metadata.get("warmup")) is not int
            or metadata["warmup"] < 0 or metadata.get("execution_context") not in {"local", "github_actions"}
            or not isinstance(metadata.get("memory_semantics"), str) or not metadata["memory_semantics"]):
        raise ValueError("invalid execution binding")
    if datetime.fromisoformat(metadata["started_at"]).tzinfo is None:
        raise ValueError("start time needs timezone")
    environment = metadata.get("environment")
    required = {"platform", "machine", "host", "python", "implementation", "executable"}
    if (not isinstance(environment, dict)
            or any(not isinstance(environment.get(k), str) or not environment[k] for k in required)
            or type(environment.get("cpu_count")) is not int or environment["cpu_count"] < 1
            or not isinstance(environment.get("packages"), list)
            or any(not isinstance(p, list) or len(p) != 2 or any(not isinstance(v, str) for v in p)
                   for p in environment["packages"])
            or not isinstance(environment.get("variables"), dict)):
        raise ValueError("incomplete toolchain/environment")
    suite = _validate_suite(receipt.get("suite"))
    if hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest() != metadata["suite_sha256"]:
        raise ValueError("suite hash does not match commands")
    results = receipt.get("results")
    if not isinstance(results, dict) or set(results) != {c["name"] for c in suite["cases"]}:
        raise ValueError("case set does not match suite")
    for case in suite["cases"]:
        result = results[case["name"]]
        if (not isinstance(result, dict) or any(result.get(k) != case[k]
                for k in ("domain", "command", "timeout_seconds"))
                or not _positive_number(result.get("timeout_seconds"))
                or not isinstance(result.get("cwd"), str) or not Path(result["cwd"]).is_absolute()):
            raise ValueError("result is not bound to case/argv/cwd")
        if result.get("status") != "measured":
            return f"failed case: {case['name']}"
        _validate_samples(result, metadata)
    return None


def _validate_samples(result, metadata):
    total, warmup = metadata["iterations"] + metadata["warmup"], metadata["warmup"]
    samples = result.get("samples")
    if (not isinstance(samples, list) or len(samples) != total
            or any(type(result.get(k)) is not int for k in ("iterations", "command_attempts", "repeat_count"))
            or result.get("iterations") != metadata["iterations"]
            or result.get("command_attempts") != total or result.get("repeat_count") != total - 1):
        raise ValueError("missing attempts")
    for index, sample in enumerate(samples):
        if (not isinstance(sample, dict) or type(sample.get("attempt")) is not int or sample["attempt"] != index + 1
                or type(sample.get("warmup")) is not bool or sample["warmup"] != (index < warmup)
                or type(sample.get("returncode")) is not int or sample["returncode"] != 0
                or "error" not in sample or sample["error"] is not None
                or any(not isinstance(sample.get(p), str) or not sample[p] for p in ("stdout", "stderr"))):
            raise ValueError("attempt is not successful")
        for field in ("elapsed_ms", "peak_rss_bytes", "cpu_seconds"):
            value = sample.get(field)
            if not (_positive_number(value) or field == "cpu_seconds" and type(value) in (int, float) and value == 0):
                raise ValueError(f"invalid sample metric: {field}")
    for aggregate, field in (("median_ms", "elapsed_ms"), ("median_peak_rss_bytes", "peak_rss_bytes"),
                             ("median_cpu_seconds", "cpu_seconds")):
        value = result.get(aggregate)
        if (not (_positive_number(value) or aggregate == "median_cpu_seconds" and type(value) in (int, float) and value == 0)
                or value != statistics.median(s[field] for s in samples[warmup:])):
            raise ValueError(f"aggregate does not match attempts: {aggregate}")


def compare_suites(current, baseline, threshold=1.2):
    """Несопоставимость/ошибка/потеря метрики запрещает зелёный результат."""
    if not _positive_number(threshold) or threshold <= 1:
        raise ValueError("regression threshold must exceed 1")
    try:
        errors = [_validate_receipt(receipt) for receipt in (current, baseline)]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"status": "INVALID", "reason": str(exc)}
    if any(errors):
        return {"status": "ERROR", "reason": next(error for error in errors if error)}
    for key in ("environment", "suite_sha256", "iterations", "warmup", "execution_context", "memory_semantics"):
        if current["metadata"].get(key) is None or current["metadata"].get(key) != baseline["metadata"].get(key):
            return {"status": "INCOMPARABLE", "reason": f"metadata differs: {key}"}
    if set(current["results"]) != set(baseline["results"]):
        return {"status": "INCOMPARABLE", "reason": "case set differs"}
    comparisons = {}
    for name, result in current["results"].items():
        old = baseline["results"][name]
        if result["cwd"] != old["cwd"]:
            return {"status": "INCOMPARABLE", "reason": f"cwd differs: {name}"}
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
        if args.baseline is not None:
            baseline_error = _validate_receipt(baseline)
            if baseline_error:
                raise ValueError(f"invalid baseline: {baseline_error}")
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
