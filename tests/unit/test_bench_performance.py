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
    return {"schema_version": 1, "metadata": {
        "environment": {"python": "test"}, "suite_sha256": "abc", "iterations": 3,
        "warmup": 1, "execution_context": "local", "memory_semantics": "test",
    }, "results": {"tiny": {"status": "measured", "median_ms": 100,
                            "median_peak_rss_bytes": 1024}}}


@pytest.mark.unit
class TestCommandSuites:
    def test_commands_really_execute_and_record_every_repeat_and_memory(self, tmp_path, command_suite):
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
        assert report["metadata"]["execution_context"] == "local"
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
        baseline["results"]["tiny"]["median_ms"] = quick["elapsed_ms"]
        current["results"]["tiny"]["median_ms"] = slow["elapsed_ms"]
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
        current["results"]["tiny"]["median_peak_rss_bytes"] *= 2
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
        current["results"]["tiny"]["median_ms"] *= 2
        monkeypatch.setattr(bench_performance, "run_suite", lambda *args: current)
        suite, baseline, output = (tmp_path / name for name in ("suite.json", "base.json", "new.json"))
        suite.write_text(json.dumps(command_suite))
        baseline.write_text(json.dumps(measured_receipt()))
        before = baseline.read_bytes()
        assert bench_performance.main(["--suite", str(suite), "--baseline", str(baseline), "--output", str(output)]) == 1
        assert baseline.read_bytes() == before
        assert json.loads(output.read_text())["status"] == "REGRESSION"

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
