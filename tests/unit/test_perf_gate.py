"""#1409: схема гейта скорости и памяти, принятая владельцем 18.11.2026.

Время — только парой «база и кандидат на одной машине в одном прогоне»: между машинами GitHub
одно и то же время различается до 1,73×. Память — против принятой базы по устойчивым полям
окружения: между машинами она расходится не больше чем на 2%.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.devtools import perf_gate

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "qualification/evidence/performance-baseline-1409"
CI_RUNS = EVIDENCE / "ci-25eca8ab"


def receipt(ms=100.0, rss=1024, host="runner-a", run_id="7", python="3.12.16", platform_="Linux-7.0-x86_64"):
    suite = {"schema_version": 1, "cases": [{"name": "tiny", "domain": "runtime",
             "command": ["true"], "timeout_seconds": 5}]}
    samples = [{"attempt": i + 1, "warmup": i == 0, "returncode": 0, "error": None,
                "elapsed_ms": ms, "peak_rss_bytes": rss, "cpu_seconds": 0.1,
                "stdout": f"/tmp/t-{i}.out", "stderr": f"/tmp/t-{i}.err"} for i in range(4)]
    return {"schema_version": 1, "metadata": {
        "sha": "a" * 40, "dirty": False, "dirty_sha256": "b" * 64,
        "started_at": "2026-11-18T00:00:00+00:00",
        "environment": {"python": python, "platform": platform_, "machine": "x86_64", "host": host,
                        "implementation": "CPython", "executable": sys.executable, "cpu_count": 4,
                        "packages": [["pyyaml", "6.0.3"]], "variables": {}},
        "suite_sha256": hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(),
        "iterations": 3, "warmup": 1, "execution_context": "github_actions",
        "ci_run_id": run_id, "ci_run_attempt": "1", "memory_semantics": "max child RSS",
    }, "suite": suite, "results": {"tiny": {**suite["cases"][0], "cwd": "/tmp", "status": "measured",
          "iterations": 3, "command_attempts": 4, "repeat_count": 3, "samples": samples,
          "median_ms": ms, "median_peak_rss_bytes": rss, "median_cpu_seconds": 0.1}}}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestPairedTime:
    def test_slower_candidate_on_the_same_machine_is_a_regression(self):
        verdict = perf_gate.compare_paired_time(receipt(ms=100), receipt(ms=150))
        assert verdict["status"] == "REGRESSION"
        assert verdict["cases"]["tiny"]["ratio"] == pytest.approx(1.5)

    def test_noise_below_threshold_is_ok(self):
        assert perf_gate.compare_paired_time(receipt(ms=100), receipt(ms=110))["status"] == "OK"

    def test_faster_candidate_is_ok(self):
        assert perf_gate.compare_paired_time(receipt(ms=100), receipt(ms=50))["status"] == "OK"

    @pytest.mark.parametrize("change", [{"host": "runner-b"}, {"run_id": "8"}, {"python": "3.12.17"}])
    def test_time_is_never_compared_across_machines_or_runs(self, change):
        verdict = perf_gate.compare_paired_time(receipt(), receipt(**change))
        assert verdict["status"] == "INCOMPARABLE"

    def test_memory_difference_does_not_change_the_time_verdict(self):
        assert perf_gate.compare_paired_time(receipt(rss=1024), receipt(rss=9999))["status"] == "OK"

    def test_failed_or_broken_receipt_is_never_green(self):
        failed = receipt()
        failed["results"]["tiny"]["status"] = "error"
        assert perf_gate.compare_paired_time(receipt(), failed)["status"] == "ERROR"
        broken = receipt()
        broken["metadata"]["sha"] = "nope"
        assert perf_gate.compare_paired_time(broken, receipt())["status"] == "INVALID"

    def test_threshold_must_exceed_one(self):
        with pytest.raises(ValueError):
            perf_gate.compare_paired_time(receipt(), receipt(), threshold=1.0)


class TestMemoryAgainstAcceptedBaseline:
    def test_other_machine_kernel_and_patch_python_stay_comparable(self):
        accepted = receipt(host="runner-a", python="3.12.16", platform_="Linux-7.0-x86_64")
        current = receipt(host="runner-z", python="3.12.18", platform_="Linux-7.1-x86_64", run_id="99")
        current["metadata"]["environment"]["packages"] = [["pyyaml", "6.0.4"]]
        assert perf_gate.compare_memory(current, accepted)["status"] == "OK"

    def test_memory_growth_over_threshold_is_a_regression(self):
        verdict = perf_gate.compare_memory(receipt(rss=1300), receipt(rss=1000))
        assert verdict["status"] == "REGRESSION"
        assert verdict["cases"]["tiny"]["ratio"] == pytest.approx(1.3)

    def test_time_difference_does_not_change_the_memory_verdict(self):
        assert perf_gate.compare_memory(receipt(ms=900), receipt(ms=100))["status"] == "OK"

    @pytest.mark.parametrize("field,value", [("python", "3.13.1"), ("machine", "arm64"),
                                             ("cpu_count", 2), ("platform", "macOS-15-arm64")])
    def test_different_stable_environment_is_incomparable(self, field, value):
        current = receipt()
        current["metadata"]["environment"][field] = value
        assert perf_gate.compare_memory(current, receipt())["status"] == "INCOMPARABLE"

    def test_changed_suite_needs_a_new_accepted_baseline(self):
        current = receipt()
        current["suite"]["cases"][0]["timeout_seconds"] = 6
        current["results"]["tiny"]["timeout_seconds"] = 6
        current["metadata"]["suite_sha256"] = hashlib.sha256(
            json.dumps(current["suite"], sort_keys=True).encode()).hexdigest()
        assert perf_gate.compare_memory(current, receipt())["status"] == "INCOMPARABLE"


class TestVerdict:
    @pytest.mark.parametrize("time_status,memory_status,overall,code", [
        ("OK", "OK", "OK", 0),
        ("REGRESSION", "OK", "REGRESSION", 1),
        ("OK", "REGRESSION", "REGRESSION", 1),
        ("REGRESSION", "INCOMPARABLE", "INCOMPARABLE", 2),
        ("INVALID", "OK", "INVALID", 2),
    ])
    def test_worst_part_decides_and_unknown_is_never_green(self, time_status, memory_status, overall, code):
        verdict = perf_gate.combine({"status": time_status}, {"status": memory_status})
        assert verdict["status"] == overall
        assert perf_gate.exit_code(verdict) == code

    def test_summary_names_both_parts_in_plain_words(self):
        text = perf_gate.format_summary(perf_gate.combine(
            perf_gate.compare_paired_time(receipt(ms=100), receipt(ms=150)),
            perf_gate.compare_memory(receipt(), receipt())))
        assert "Время" in text and "Память" in text and "tiny" in text and "1.50" in text


class TestRealCiEvidence:
    """Квитанции трёх прогонов 13.11.2026 — это и есть данные, на которых прежняя схема ошибалась."""

    def test_old_false_regression_between_same_named_runners_is_now_incomparable(self):
        first = load(CI_RUNS / "run-43408859348/base.json")
        later = load(CI_RUNS / "run-43409263821/base.json")
        assert first["metadata"]["environment"]["host"] == later["metadata"]["environment"]["host"]
        assert perf_gate.compare_paired_time(first, later)["status"] == "INCOMPARABLE"

    @pytest.mark.parametrize("run", ["run-43408859348", "run-43409103304", "run-43409263821"])
    def test_base_and_repeat_on_one_machine_pass_the_paired_time_gate(self, run):
        verdict = perf_gate.compare_paired_time(load(CI_RUNS / run / "base.json"),
                                                load(CI_RUNS / run / "repeat.json"))
        assert verdict["status"] == "OK", verdict

    @pytest.mark.parametrize("run", ["run-43408859348", "run-43409103304", "run-43409263821"])
    def test_every_ci_run_passes_memory_against_the_accepted_baseline(self, run):
        accepted = load(EVIDENCE / "accepted-memory-baseline.json")
        for side in ("base", "repeat"):
            verdict = perf_gate.compare_memory(load(CI_RUNS / run / f"{side}.json"), accepted)
            assert verdict["status"] == "OK", verdict


def git_repo(path):
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "f.txt").write_text("x")
    (path / ".gitignore").write_text("ran.marker\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


@pytest.fixture
def lease(monkeypatch, tmp_path):
    from ai_ops_kit.devtools import host_resource_cli
    lock = tmp_path / "unit-only.lock"
    with host_resource_cli.host_slot("unit-1409-pair", "local", path=lock) as fd:
        monkeypatch.setenv("AI_OPS_HOST_SLOT_FD", str(fd))
        monkeypatch.setenv("AI_OPS_HOST_SLOT_PATH", str(lock))
        yield fd


@pytest.fixture
def pair_setup(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    suite = {"schema_version": 1, "cases": [{"name": "tiny", "domain": "runtime", "timeout_seconds": 10,
             "command": ["{python}", "-c", "import pathlib; pathlib.Path('ran.marker').touch()"]}]}
    return {"suite": suite, "base": base, "base_sha": git_repo(base), "candidate": candidate,
            "candidate_sha": git_repo(candidate), "out": tmp_path / "out"}


def steady_window():
    return {"boot_id": "boot-a", "pswpin": 0, "pswpout": 0}


@pytest.mark.usefixtures("lease")
class TestRunPair:
    def run(self, setup, window=None, **overrides):
        args = {"suite": setup["suite"], "base_root": setup["base"], "base_sha": setup["base_sha"],
                "candidate_root": setup["candidate"], "candidate_sha": setup["candidate_sha"],
                "out_dir": setup["out"], "iterations": 1, "warmup": 0,
                "window_reader": window or steady_window, **overrides}
        return perf_gate.run_pair(**args)

    def test_both_sides_really_run_in_their_own_checkout(self, pair_setup):
        verdict = self.run(pair_setup)
        assert (pair_setup["base"] / "ran.marker").exists()
        assert (pair_setup["candidate"] / "ran.marker").exists()
        base = load(pair_setup["out"] / "base.json")
        candidate = load(pair_setup["out"] / "candidate.json")
        assert base["metadata"]["sha"] == pair_setup["base_sha"]
        assert candidate["metadata"]["sha"] == pair_setup["candidate_sha"]
        assert verdict["time"]["status"] in {"OK", "REGRESSION"}
        assert load(pair_setup["out"] / "window.json")["qualification"] == "CANDIDATE"

    def test_wrong_source_is_refused_before_any_command(self, pair_setup):
        verdict = self.run(pair_setup, base_sha="f" * 40)
        assert verdict["status"] == "INVALID"
        assert not (pair_setup["base"] / "ran.marker").exists()
        assert not (pair_setup["candidate"] / "ran.marker").exists()

    def test_dirty_checkout_is_refused_before_any_command(self, pair_setup):
        (pair_setup["candidate"] / "f.txt").write_text("changed")
        assert self.run(pair_setup)["status"] == "INVALID"
        assert not (pair_setup["base"] / "ran.marker").exists()

    def test_missing_window_guard_is_refused_before_any_command(self, pair_setup):
        assert self.run(pair_setup, window=lambda: None)["status"] == "INVALID"
        assert not (pair_setup["base"] / "ran.marker").exists()

    @pytest.mark.parametrize("after", [{"boot_id": "boot-b", "pswpin": 0, "pswpout": 0},
                                       {"boot_id": "boot-a", "pswpin": 5, "pswpout": 0}])
    def test_swap_or_reboot_during_the_pair_rejects_the_window(self, pair_setup, after):
        readings = iter([steady_window(), after])
        verdict = self.run(pair_setup, window=lambda: next(readings))
        assert verdict["status"] == "REJECTED_WINDOW"
        assert perf_gate.exit_code(verdict) == 2
        assert load(pair_setup["out"] / "window.json")["qualification"] == "REJECTED"

    def test_command_that_dirties_the_checkout_rejects_the_window(self, pair_setup):
        pair_setup["suite"]["cases"][0]["command"] = ["{python}", "-c",
                                                      "import pathlib; pathlib.Path('f.txt').write_text('y')"]
        verdict = self.run(pair_setup)
        assert verdict["status"] == "REJECTED_WINDOW"
        assert load(pair_setup["out"] / "window.json")["source_unchanged"] is False


class TestCli:
    def test_compare_writes_verdict_and_returns_regression_code(self, tmp_path):
        paths = {}
        for name, data in {"base": receipt(ms=100), "candidate": receipt(ms=200), "memory": receipt()}.items():
            paths[name] = tmp_path / f"{name}.json"
            paths[name].write_text(json.dumps(data))
        output = tmp_path / "verdict.json"
        code = perf_gate.main(["compare", "--base", str(paths["base"]), "--candidate", str(paths["candidate"]),
                               "--memory-baseline", str(paths["memory"]), "--output", str(output)])
        assert code == 1
        assert load(output)["status"] == "REGRESSION"

    def test_internal_failure_is_not_reported_as_regression(self, tmp_path, monkeypatch):
        path = tmp_path / "r.json"
        path.write_text(json.dumps(receipt()))
        monkeypatch.setattr(perf_gate, "compare_paired_time", lambda *a: 1 / 0)
        assert perf_gate.main(["compare", "--base", str(path), "--candidate", str(path),
                               "--memory-baseline", str(path)]) == 2

    def test_unreadable_input_is_not_executed(self, tmp_path):
        code = perf_gate.main(["compare", "--base", str(tmp_path / "none.json"), "--candidate",
                               str(tmp_path / "none.json"), "--memory-baseline", str(tmp_path / "none.json")])
        assert code == 2

    def test_accepted_baseline_is_an_untouched_copy_of_a_real_ci_receipt(self):
        accepted = (EVIDENCE / "accepted-memory-baseline.json").read_bytes()
        assert accepted == (CI_RUNS / "run-43408859348/base.json").read_bytes()
        assert perf_gate.compare_memory(json.loads(accepted), copy.deepcopy(json.loads(accepted)))["status"] == "OK"
