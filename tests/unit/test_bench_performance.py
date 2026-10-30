"""Unit tests for tools/bench_performance.py — performance benchmarks."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from ai_ops_kit.devtools import bench_performance


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


# Command-series tests run tiny controlled commands, never the real CI/runtime suite.
@pytest.fixture
def command_suite(tmp_path):
    marker = tmp_path / "executed.txt"
    return {"schema_version": 1, "cases": [{
        "name": "tiny-runtime", "domain": "runtime", "timeout_seconds": 5,
        "command": ["{python}", "-c", f"from pathlib import Path; p=Path({str(marker)!r}); "
                    "p.write_text(p.read_text()+'x' if p.exists() else 'x'); payload=bytearray(1024*1024)"],
    }]}


def measured_receipt():
    import hashlib
    suite = {"schema_version": 1, "cases": [{"name": "tiny", "domain": "runtime",
             "command": ["true"], "timeout_seconds": 5}]}
    samples = [{"attempt": i + 1, "warmup": i == 0, "returncode": 0, "error": None,
                "elapsed_ms": 100, "peak_rss_bytes": 1024, "cpu_seconds": 0.1,
                "stdout": f"/tmp/tiny-{i}.stdout", "stderr": f"/tmp/tiny-{i}.stderr"} for i in range(4)]
    return {"schema_version": 1, "metadata": {
        "sha": "a" * 40, "dirty": False, "dirty_sha256": "b" * 64,
        "started_at": "2026-10-28T00:00:00+00:00",
        "environment": {"python": "test", "platform": "test", "machine": "test", "host": "test",
                        "implementation": "test", "executable": sys.executable, "cpu_count": 1,
                        "packages": [], "variables": {}},
        "suite_sha256": hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(), "iterations": 3,
        "warmup": 1, "execution_context": "local", "memory_semantics": "test",
    }, "suite": suite, "results": {"tiny": {**suite["cases"][0], "cwd": "/tmp", "status": "measured",
          "iterations": 3, "command_attempts": 4, "repeat_count": 3, "samples": samples,
          "median_ms": 100, "median_peak_rss_bytes": 1024, "median_cpu_seconds": 0.1}}}


def set_receipt_metric(receipt, aggregate, sample_field, value):
    result = receipt["results"]["tiny"]
    result[aggregate] = value
    for sample in result["samples"]:
        sample[sample_field] = value


@pytest.fixture
def command_lease(monkeypatch, tmp_path):
    from ai_ops_kit.devtools import host_resource_cli
    lock = tmp_path / "unit-only.lock"
    with host_resource_cli.host_slot("unit-1409", "local", path=lock) as fd:
        monkeypatch.setenv("AI_OPS_HOST_SLOT_FD", str(fd))
        monkeypatch.setenv("AI_OPS_HOST_SLOT_PATH", str(lock))
        yield fd


@pytest.mark.unit
@pytest.mark.usefixtures("command_lease")
class TestCommandSuites:
    @pytest.mark.parametrize("actions,context", [(None, "local"), ("false", "local"),
                                                ("true", "github_actions")])
    def test_commands_really_execute_and_record_every_repeat_and_memory(
            self, tmp_path, command_suite, monkeypatch, actions, context):
        # Среда теста задаётся явно: сам pytest тоже может работать внутри Actions.
        for key in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            monkeypatch.delenv(key, raising=False)
        if actions is not None:
            monkeypatch.setenv("GITHUB_ACTIONS", actions)
        if context == "github_actions":
            monkeypatch.setenv("GITHUB_RUN_ID", "1409")
            monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
        report = bench_performance.run_suite(command_suite, bench_performance.PKG, tmp_path / "logs", 2, 1)
        # Сначала реальный эффект всех трёх команд, затем проверка receipt.
        assert (tmp_path / "executed.txt").read_text() == "xxx"
        result = report["results"]["tiny-runtime"]
        assert result["status"] == "measured"
        assert result["iterations"] == 2
        assert result["command_attempts"] == 3
        assert result["repeat_count"] == 2
        assert [s["warmup"] for s in result["samples"]] == [True, False, False]
        assert result["median_ms"] > 0
        assert result["median_peak_rss_bytes"] >= 1024 * 1024
        assert result["median_cpu_seconds"] >= 0
        assert all(Path(s["stdout"]).is_file() and Path(s["stderr"]).is_file() for s in result["samples"])
        assert len(report["metadata"]["sha"]) == 40
        assert len(report["metadata"]["dirty_sha256"]) == 64
        assert report["metadata"]["environment"]["executable"] == sys.executable
        assert report["metadata"]["execution_context"] == context
        assert report["metadata"]["ci_run_id"] == ("1409" if context == "github_actions" else None)
        assert report["metadata"]["ci_run_attempt"] == ("2" if context == "github_actions" else None)
        # JSON roundtrip must preserve compatibility (tuples in metadata used to differ from lists).
        restored = json.loads(json.dumps(report))
        assert bench_performance.compare_suites(report, restored)["status"] == "OK"

    def test_failed_attempt_cannot_be_saved_as_measured(self, tmp_path, command_suite):
        command_suite["cases"][0]["command"] = ["{python}", "-c", "raise SystemExit(7)"]
        report = bench_performance.run_suite(command_suite, bench_performance.PKG, tmp_path / "logs", 1, 0)
        result = report["results"]["tiny-runtime"]
        assert result["samples"][0]["returncode"] == 7
        assert result["status"] == "error"
        assert result["median_ms"] is None
        assert bench_performance.compare_suites(report, report)["status"] == "ERROR"

    def test_timeout_is_failed_measurement(self, tmp_path):
        case = {"command": ["{python}", "-c", "import time; time.sleep(10)"], "timeout_seconds": 0.05}
        sample = bench_performance.measure_command(case, tmp_path, tmp_path / "timeout")
        assert sample["error"] == "timeout"
        assert sample["returncode"] != 0

    def test_warmup_failure_is_not_discarded(self, monkeypatch, tmp_path, command_suite):
        samples = iter([{"returncode": 1, "error": "failed warmup"},
                        {"returncode": 0, "error": None, "elapsed_ms": 1, "peak_rss_bytes": 1024, "cpu_seconds": 0.1}])
        monkeypatch.setattr(bench_performance, "measure_command", lambda *args: next(samples))
        report = bench_performance.run_suite(command_suite, bench_performance.PKG, tmp_path / "logs", 1, 1)
        assert report["results"]["tiny-runtime"]["status"] == "error"

    def test_controlled_slow_command_runs_before_regression_is_detected(self, tmp_path):
        delay = tmp_path / "delay"
        marker = tmp_path / "marker"
        delay.write_text("0")
        case = {"command": ["{python}", "-c",
                            f"from pathlib import Path; import time; time.sleep(float(Path({str(delay)!r}).read_text())); "
                            f"Path({str(marker)!r}).write_text('executed')"], "timeout_seconds": 5}
        quick = bench_performance.measure_command(case, tmp_path, tmp_path / "quick")
        delay.write_text("0.25")
        slow = bench_performance.measure_command(case, tmp_path, tmp_path / "slow")
        assert marker.read_text() == "executed"
        assert slow["returncode"] == quick["returncode"] == 0
        assert slow["elapsed_ms"] - quick["elapsed_ms"] > 150
        baseline, current = measured_receipt(), measured_receipt()
        set_receipt_metric(baseline, "median_ms", "elapsed_ms", quick["elapsed_ms"])
        set_receipt_metric(current, "median_ms", "elapsed_ms", slow["elapsed_ms"])
        assert bench_performance.compare_suites(current, baseline)["status"] == "REGRESSION"

    @pytest.mark.parametrize("change", ["schema", "cases", "environment", "iterations", "warmup", "suite_sha256", "missing_metric", "error", "zero", "nan"])
    def test_invalid_or_incomparable_receipt_is_never_green(self, change):
        baseline = measured_receipt()
        current = copy.deepcopy(baseline)
        if change == "schema":
            current["schema_version"] = 99
        elif change == "cases":
            current["results"]["extra"] = current["results"]["tiny"]
        elif change in {"environment", "iterations", "warmup", "suite_sha256"}:
            current["metadata"][change] = "different"
        elif change == "missing_metric":
            del current["results"]["tiny"]["median_peak_rss_bytes"]
        elif change == "error":
            baseline["results"]["tiny"]["status"] = "error"
        else:
            current["results"]["tiny"]["median_ms"] = 0 if change == "zero" else float("nan")
        assert bench_performance.compare_suites(current, baseline)["status"] in {"INVALID", "INCOMPARABLE", "ERROR"}

    def test_memory_regression_fails_even_when_time_is_stable(self):
        baseline, current = measured_receipt(), measured_receipt()
        set_receipt_metric(current, "median_peak_rss_bytes", "peak_rss_bytes", 2048)
        assert bench_performance.compare_suites(current, baseline)["status"] == "REGRESSION"
        assert bench_performance.compare_suites(baseline, baseline)["status"] == "OK"

    @pytest.mark.parametrize("bad_case", [
        {"name": "x", "domain": "runtime", "command": "echo hi", "timeout_seconds": 1},
        {"name": "x", "domain": "unknown", "command": ["true"], "timeout_seconds": 1},
        {"name": "x", "domain": "ci", "command": ["true"], "timeout_seconds": -1},
    ])
    def test_bad_suite_rejected_before_commands(self, tmp_path, bad_case):
        path = tmp_path / "suite.json"
        path.write_text(json.dumps({"schema_version": 1, "cases": [bad_case]}))
        with pytest.raises(ValueError):
            bench_performance.load_suite(path)

    def test_command_cli_requires_real_host_slot_before_any_effect(self, monkeypatch, tmp_path, command_suite, capsys):
        from ai_ops_kit.devtools import host_resource_cli
        monkeypatch.setattr(host_resource_cli, "inherited_slot", lambda: None)
        suite = tmp_path / "suite.json"
        suite.write_text(json.dumps(command_suite))
        output = tmp_path / "receipt.json"
        assert bench_performance.main(["--suite", str(suite), "--output", str(output)]) == 2
        assert not (tmp_path / "executed.txt").exists()
        assert not output.exists()
        assert "shared slot" in capsys.readouterr().err

    def test_cli_keeps_baseline_bytes_and_returns_nonzero_on_regression(self, monkeypatch, tmp_path, command_suite):
        from ai_ops_kit.devtools import host_resource_cli
        monkeypatch.setattr(host_resource_cli, "inherited_slot", lambda: 123)
        current = measured_receipt()
        set_receipt_metric(current, "median_ms", "elapsed_ms", 200)
        monkeypatch.setattr(bench_performance, "run_suite", lambda *args: current)
        suite, baseline, output = (tmp_path / name for name in ("suite.json", "base.json", "new.json"))
        suite.write_text(json.dumps(command_suite))
        baseline.write_text(json.dumps(measured_receipt()))
        before = baseline.read_bytes()
        assert bench_performance.main(["--suite", str(suite), "--baseline", str(baseline), "--output", str(output)]) == 1
        assert baseline.read_bytes() == before
        assert json.loads(output.read_text())["status"] == "REGRESSION"

    @pytest.mark.parametrize("payload", [None, {}, []])
    def test_explicit_invalid_baseline_stops_before_commands(
            self, monkeypatch, tmp_path, command_suite, capsys, payload):
        suite, baseline, output = (tmp_path / name for name in ("suite.json", "base.json", "new.json"))
        suite.write_text(json.dumps(command_suite))
        baseline.write_text(json.dumps(payload))
        before = baseline.read_bytes()
        # Без проверки baseline эти команды действительно оставляют marker.
        report = bench_performance.run_suite(command_suite, bench_performance.PKG, tmp_path / "proof", 1, 0)
        marker = tmp_path / "executed.txt"
        assert report["results"]["tiny-runtime"]["status"] == "measured"
        assert marker.read_text() == "x"
        marker.unlink()
        assert bench_performance.main(["--suite", str(suite), "--baseline", str(baseline),
                                       "--output", str(output), "--iterations", "1", "--warmup", "0"]) == 2
        assert not marker.exists()
        assert not output.exists()
        assert not output.with_suffix(".logs").exists()
        assert baseline.read_bytes() == before
        assert "ERROR" in capsys.readouterr().err

    def test_cli_never_overwrites_existing_receipt(self, tmp_path):
        output = tmp_path / "existing.json"
        output.write_text("keep")
        with pytest.raises(SystemExit) as exc:
            bench_performance.main(["--suite", "unused", "--output", str(output)])
        assert exc.value.code == 2
        assert output.read_text() == "keep"

    def test_measurement_preserves_real_lease_through_both_subprocesses(self, monkeypatch, tmp_path):
        from ai_ops_kit.devtools import host_resource_cli
        lock, marker = tmp_path / "fixture.lock", tmp_path / "lease-confirmed"
        case = {"command": ["{python}", "-c",
                            "from pathlib import Path; from ai_ops_kit.devtools.host_resource_cli import inherited_slot; "
                            f"assert inherited_slot() is not None; Path({str(marker)!r}).write_text('lease-held')"],
                "timeout_seconds": 5}
        with host_resource_cli.host_slot("fixture-1409", "local", path=lock) as fd:
            monkeypatch.setenv("AI_OPS_HOST_SLOT_FD", str(fd))
            monkeypatch.setenv("AI_OPS_HOST_SLOT_PATH", str(lock))
            sample = bench_performance.measure_command(case, bench_performance.PKG, tmp_path / "lease")
            assert marker.read_text() == "lease-held"
            assert sample["returncode"] == 0
            assert host_resource_cli.inherited_slot() == fd
        # Только тестовый резерв: общий production host-slot тест не занимает.
        with host_resource_cli.host_slot("fixture-reacquire", "local", path=lock):
            assert lock.is_file()

    @pytest.mark.parametrize("suite", [[], None, {"schema_version": 1, "cases": [None]}])
    def test_nonobject_suite_or_case_is_rejected(self, tmp_path, suite):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(suite))
        with pytest.raises(ValueError):
            bench_performance.load_suite(path)

    @pytest.mark.parametrize("side", ["current", "baseline"])
    @pytest.mark.parametrize("binding", ["sha", "dirty", "dirty_sha256", "environment", "started_at"])
    def test_missing_source_binding_is_invalid(self, side, binding):
        current, baseline = measured_receipt(), measured_receipt()
        del (current if side == "current" else baseline)["metadata"][binding]
        assert bench_performance.compare_suites(current, baseline)["status"] == "INVALID"

    @pytest.mark.parametrize("damage", ["suite", "samples", "argv", "hash", "aggregate", "sample_error"])
    def test_receipt_must_bind_actual_attempts_to_commands(self, damage):
        baseline = measured_receipt()
        result = baseline["results"]["tiny"]
        if damage == "suite":
            del baseline["suite"]
        elif damage == "samples":
            del result["samples"]
        elif damage == "argv":
            result["command"] = ["other"]
        elif damage == "hash":
            baseline["suite"]["cases"][0]["command"] = ["other"]
        elif damage == "aggregate":
            result["median_ms"] = 200
        else:
            result["samples"][0]["error"] = "failed warmup"
        assert bench_performance.compare_suites(measured_receipt(), baseline)["status"] == "INVALID"

    def test_distinct_source_revisions_are_named_but_can_be_compared(self):
        current, baseline = measured_receipt(), measured_receipt()
        current["metadata"]["sha"] = "c" * 40
        assert bench_performance.compare_suites(current, baseline)["status"] == "OK"

    def test_lost_fixture_inode_prevents_subprocess(self, tmp_path, command_lease):
        from ai_ops_kit.devtools import host_resource_cli
        import os
        assert host_resource_cli.inherited_slot() == command_lease
        lock = Path(os.environ["AI_OPS_HOST_SLOT_PATH"])
        lock.unlink()
        lock.write_text("different test inode")
        assert host_resource_cli.inherited_slot() is None
        marker = tmp_path / "must-not-execute"
        case = {"command": ["{python}", "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
                "timeout_seconds": 1}
        with pytest.raises(ValueError, match="host-slot"):
            bench_performance.measure_command(case, tmp_path, tmp_path / "lost")
        assert not marker.exists()

    def test_loss_after_first_attempt_stops_further_commands(self, tmp_path, monkeypatch, command_suite, command_lease):
        import os
        from ai_ops_kit.devtools import host_resource_cli
        duplicate = os.dup(command_lease)
        monkeypatch.setenv("AI_OPS_HOST_SLOT_FD", str(duplicate))
        assert host_resource_cli.inherited_slot() == duplicate
        measure = bench_performance.measure_command
        def first_then_lose(*args):
            result = measure(*args)
            os.close(duplicate)
            return result
        monkeypatch.setattr(bench_performance, "measure_command", first_then_lose)
        report = bench_performance.run_suite(command_suite, bench_performance.PKG, tmp_path / "lost-logs", 3, 0)
        assert (tmp_path / "executed.txt").read_text() == "x"
        assert report["results"]["tiny-runtime"]["status"] == "error"
        assert len(report["results"]["tiny-runtime"]["samples"]) == 2
        assert bench_performance.compare_suites(report, report)["status"] == "ERROR"

    @pytest.mark.parametrize("event", ["parent-exit", "worker-terminate", "outer-timeout"])
    def test_owned_process_group_is_cleaned_before_return(self, tmp_path, monkeypatch, event):
        import os
        import signal
        import subprocess
        import time
        started, late = tmp_path / "started", tmp_path / "late"
        child = (f"from pathlib import Path; import os,time; Path({str(started)!r}).write_text(str(os.getpid())); "
                 f"time.sleep(.6); Path({str(late)!r}).touch()")
        parent = (f"import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,'-c',{child!r}]); "
                  f"deadline=time.monotonic()+5\nwhile not Path({str(started)!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\n")
        if event != "parent-exit":
            parent += "time.sleep(10)\n"
        case = {"command": ["{python}", "-c", parent], "timeout_seconds": 5}
        original_popen = subprocess.Popen
        if event != "parent-exit":
            def controlled_popen(*args, **kwargs):
                worker = original_popen(*args, **kwargs)
                if "_command_worker" not in str(args[0]):
                    return worker
                communicate = worker.communicate
                triggered = False
                def trigger(*a, **kw):
                    nonlocal triggered
                    if not triggered:
                        triggered = True
                        deadline = time.monotonic() + 5
                        while not started.exists() and time.monotonic() < deadline:
                            time.sleep(.01)
                        assert started.exists(), "prove child started before interrupting owned worker"
                        if event == "outer-timeout":
                            raise subprocess.TimeoutExpired(worker.args, 0)
                        worker.terminate()
                    return communicate(*a, **kw)
                worker.communicate = trigger
                return worker
            monkeypatch.setattr(subprocess, "Popen", controlled_popen)
        try:
            if event == "parent-exit":
                sample = bench_performance.measure_command(case, tmp_path, tmp_path / event)
                assert sample["error"] == "background descendants outlived command"
            else:
                with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
                    bench_performance.measure_command(case, tmp_path, tmp_path / event)
            assert started.exists()
            pid = int(started.read_text())
            time.sleep(.75)
            assert not late.exists(), "owned child cannot create a late effect after measurement returns"
            status = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, check=False).stdout.strip()
            assert not status or status.startswith("Z"), status
        finally:
            if started.exists():
                try:
                    os.kill(int(started.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
