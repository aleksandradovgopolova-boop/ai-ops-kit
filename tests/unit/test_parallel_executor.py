"""Гранулярные тесты parallel_executor (мигрировано из test_parallel_executor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import concurrent.futures
import threading

import pytest

from ai_ops_kit.engine import parallel_executor as executor
from ai_ops_kit.engine.parallel_executor import (
    execute_parallel,
)


@pytest.fixture
def work_graph():
    return {"packages": [
        {"id": "api", "write_scope": ["api/**"], "shared_contracts": ["OrderContract"]},
        {"id": "ui", "write_scope": ["ui/**"], "shared_contracts": ["OrderContract"]},
        {"id": "wiring", "write_scope": ["wiring/**"], "depends_on": ["api", "ui"]},
    ]}


@pytest.fixture
def shas():
    return {"api": "aaa1110", "ui": "bbb2220", "wiring": "ccc3330"}


@pytest.fixture
def contract_shas():
    return {"OrderContract": "c0ffee0"}


def _good_runner(pkg, shas):
    s = shas[pkg["id"]]
    return {"status": "pass", "sha": s, "gate_report": {"all_pass": True, "tested_revision": s}}


def _good_integration(results):
    return ("1234567", {"all_pass": True, "tested_revision": "1234567"}, 0, False)


def _proof(pid):
    sha = {"a": "aaa1110", "b": "bbb2220", "c": "ccc3330", "d": "ddd4440"}[pid]
    return {"status": "pass", "sha": sha,
            "gate_report": {"all_pass": True, "tested_revision": sha}}


def test_ready_dependency_uses_free_slot_before_unrelated_root_finishes(tmp_path):
    """C реально пишет файл, пока B ждёт C; старый общий барьер создавал взаимное ожидание."""
    b_started, c_wrote = threading.Event(), threading.Event()
    graph = {"packages": [
        {"id": "a", "write_scope": ["a/"]},
        {"id": "b", "write_scope": ["b/"]},
        {"id": "c", "write_scope": ["c/"], "depends_on": ["a"]},
    ]}

    def runner(pkg):
        pid = pkg["id"]
        if pid == "a":
            assert b_started.wait(2), "B не стартовал вместе с A"
        if pid == "b":
            b_started.set()
            assert c_wrote.wait(2), "готовый C ждёт посторонний B"
        (tmp_path / pid).write_text(pid)
        if pid == "c":
            assert not (tmp_path / "b").exists()
            c_wrote.set()
        return _proof(pid)

    def integrate(results):
        assert list(results) == ["a", "b", "c"]
        assert {p.name: p.read_text() for p in tmp_path.iterdir()} == {"a": "a", "b": "b", "c": "c"}
        return _good_integration(results)

    result = execute_parallel(graph, runner, integrate)
    assert result["proceed"] is True
    assert result["delivery"]["intents"] == 1


@pytest.mark.parametrize("bad", [
    {"status": "fail"},
    {"status": "pass", "sha": "aaa1110", "gate_report": {"all_pass": False, "tested_revision": "aaa1110"}},
    {"status": "pass", "sha": "aaa1110", "gate_report": {"all_pass": True, "tested_revision": "wrong"}},
    {"status": "pass", "sha": "not-a-sha", "gate_report": {"all_pass": True, "tested_revision": "not-a-sha"}},
])
def test_unproven_dependency_never_launches_child(tmp_path, bad):
    graph = {"packages": [{"id": "a", "write_scope": ["a/"]},
                           {"id": "c", "write_scope": ["c/"], "depends_on": ["a"]}]}

    def runner(pkg):
        (tmp_path / pkg["id"]).write_text("actually ran")
        return bad if pkg["id"] == "a" else _proof("c")

    def integrate(_):
        pytest.fail("fan-in запущен после недоказанной зависимости")

    result = execute_parallel(graph, runner, integrate)
    assert (tmp_path / "a").read_text() == "actually ran"
    assert not (tmp_path / "c").exists()
    assert result["package_results"]["c"]["status"] == "blocked-dependency"
    assert result["delivery"]["intents"] == 0


def test_cancelled_future_cannot_start_dependents_or_fan_in(monkeypatch, tmp_path):
    real_executor = concurrent.futures.ThreadPoolExecutor

    class CancelFirst(real_executor):
        def submit(self, fn, *args, **kwargs):
            pkg = args[-1]
            if pkg["id"] == "a":
                future = concurrent.futures.Future()
                assert future.cancel()
                assert not future.set_running_or_notify_cancel()
                return future
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr(executor._cf, "ThreadPoolExecutor", CancelFirst)
    graph = {"packages": [{"id": "a", "write_scope": ["a/"]},
                           {"id": "c", "write_scope": ["c/"], "depends_on": ["a"]}]}

    def runner(pkg):
        (tmp_path / pkg["id"]).write_text("ran")
        return _proof(pkg["id"])

    result = execute_parallel(graph, runner, lambda _: pytest.fail("cancelled fan-in"))
    assert list(tmp_path.iterdir()) == []
    assert result["package_results"]["a"]["status"] == "error"
    assert "CancelledError" in result["package_results"]["a"]["error"]
    assert result["package_results"]["c"]["status"] == "blocked-dependency"
    assert result["delivery"]["open_pr"] is False


@pytest.mark.parametrize("limit", [1, 2, 8])
def test_ready_scheduler_never_exceeds_two_or_requested_lower_limit(tmp_path, limit):
    started, release = threading.Event(), threading.Event()
    lock, active, peak = threading.Lock(), set(), []
    expected = min(2, limit)
    graph = {"packages": [{"id": pid, "write_scope": [f"{pid}/"]} for pid in "abcd"]}

    def runner(pkg):
        pid = pkg["id"]
        with lock:
            active.add(pid)
            peak.append(len(active))
            if len(active) == expected:
                started.set()
        assert release.wait(2), "контроллер не освободил исполнителей"
        (tmp_path / pid).write_text(pid)
        with lock:
            active.remove(pid)
        return _proof(pid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as controller:
        future = controller.submit(execute_parallel, graph, runner, _good_integration, max_parallel=limit)
        try:
            assert started.wait(2)
        finally:
            release.set()
        result = future.result(timeout=5)
    assert max(peak) == expected
    assert {p.name for p in tmp_path.iterdir()} == set("abcd")
    assert result["proceed"] is True


@pytest.mark.parametrize("scope", [["shared/**"], ["./shared/"], ["shared\\"], ["**"], [], None, [None]])
def test_ready_dependent_waits_for_conflicting_active_writer(tmp_path, scope):
    b_started, a_finished = threading.Event(), threading.Event()
    graph = {"packages": [
        {"id": "a", "write_scope": ["a/"]},
        {"id": "b", "write_scope": ["shared/child/"]},
        {"id": "c", "write_scope": scope, "depends_on": ["a"]},
    ]}

    def runner(pkg):
        pid = pkg["id"]
        if pid == "a":
            assert b_started.wait(2)
            a_finished.set()
        elif pid == "b":
            b_started.set()
            assert a_finished.wait(2)
            (tmp_path / "shared").write_text("b")
        else:
            assert (tmp_path / "shared").read_text() == "b"
            (tmp_path / "shared").write_text("bc")
        return _proof(pid)

    result = execute_parallel(graph, runner, _good_integration)
    assert result["proceed"] is True
    assert (tmp_path / "shared").read_text() == "bc"


@pytest.mark.unit
class TestHappyPath:
    def test_proceed_and_fan_in(self, work_graph, shas, contract_shas):
        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), _good_integration, contract_shas=contract_shas)
        assert r["proceed"]
        assert r["stage"] == "fan-in"

    def test_all_packages_executed(self, work_graph, shas, contract_shas):
        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), _good_integration, contract_shas=contract_shas)
        assert set(r["package_results"]) == {"api", "ui", "wiring"}

    def test_parallel_trace(self, work_graph, shas, contract_shas):
        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), _good_integration, contract_shas=contract_shas)
        assert any(t["pkg"] in ("api", "ui") and t["mode"] == "parallel" for t in r["trace"])

    def test_single_delivery_intent_with_pr(self, work_graph, shas, contract_shas):
        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), _good_integration, contract_shas=contract_shas)
        assert r["delivery"]["intents"] == 1
        assert r["delivery"]["open_pr"]
        assert r["delivery"]["integration_sha"] == "1234567"


@pytest.mark.unit
class TestAggregateShaMismatch:
    def test_wrong_aggregate_sha_no_pr(self, work_graph, shas, contract_shas):
        def wrong_agg(results):
            return ("1234567", {"all_pass": True, "tested_revision": "OTHER99"}, 0, False)
        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), wrong_agg, contract_shas=contract_shas)
        assert r["delivery"]["open_pr"] is False


@pytest.mark.unit
class TestPackageFailure:
    def test_one_fail_blocks_fan_in(self, work_graph, shas, contract_shas):
        ran_ids = set()

        def ui_fails(pkg):
            ran_ids.add(pkg["id"])
            if pkg["id"] == "ui":
                return {"status": "fail", "sha": "bbb2220", "gate_report": {"all_pass": False, "tested_revision": "bbb2220"}}
            return _good_runner(pkg, shas)

        called = {"n": 0}

        def counting_integration(results):
            called["n"] += 1
            return _good_integration(results)

        r = execute_parallel(work_graph, ui_fails, counting_integration, contract_shas=contract_shas)
        assert r["stage"] == "pre-fan-in"
        assert called["n"] == 0
        assert r["delivery"]["intents"] == 0

    def test_dependency_aware_stop(self, work_graph, shas, contract_shas):
        ran_ids = set()

        def ui_fails(pkg):
            ran_ids.add(pkg["id"])
            if pkg["id"] == "ui":
                return {"status": "fail", "sha": "bbb2220", "gate_report": {"all_pass": False, "tested_revision": "bbb2220"}}
            return _good_runner(pkg, shas)

        r = execute_parallel(work_graph, ui_fails, _good_integration, contract_shas=contract_shas)
        assert "wiring" not in ran_ids
        assert r["package_results"]["wiring"]["status"] == "blocked-dependency"


@pytest.mark.unit
class TestRunnerException:
    def test_exception_becomes_structural_error(self, work_graph, shas, contract_shas):
        def boom(pkg):
            if pkg["id"] == "api":
                raise RuntimeError("provider timeout")
            return _good_runner(pkg, shas)

        r = execute_parallel(work_graph, boom, _good_integration, contract_shas=contract_shas)
        assert r["package_results"]["api"]["status"] == "error"
        assert "provider timeout" in r["package_results"]["api"].get("error", "")
        assert r["proceed"] is False
        assert r["delivery"]["intents"] == 0


@pytest.mark.unit
class TestContractFirst:
    def test_unfixed_contract_blocks_packages(self, work_graph, shas, contract_shas):
        ran = {"n": 0}

        def counting_runner(pkg):
            ran["n"] += 1
            return _good_runner(pkg, shas)

        r = execute_parallel(work_graph, counting_runner, _good_integration, contract_shas={})
        assert r["stage"] == "contract-first"
        assert ran["n"] == 0


@pytest.mark.unit
class TestMergeConflict:
    def test_conflict_on_fan_in_blocks_pr(self, work_graph, shas, contract_shas):
        def conflict_integration(results):
            return ("1234567", {"all_pass": True, "tested_revision": "1234567"}, 1, False)

        r = execute_parallel(work_graph, lambda p: _good_runner(p, shas), conflict_integration, contract_shas=contract_shas)
        assert r["proceed"] is False
        assert r["delivery"]["open_pr"] is False


@pytest.mark.unit
class TestCyclicDependency:
    def test_cycle_blocks_at_plan(self, contract_shas):
        cyc = {"packages": [
            {"id": "a", "write_scope": ["a/**"], "depends_on": ["b"]},
            {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]},
        ]}
        r = execute_parallel(cyc, lambda p: {"status": "pass"}, _good_integration, contract_shas={})
        assert r["stage"] == "plan"
        assert r["proceed"] is False


@pytest.mark.unit
class TestMissingSha:
    def test_package_without_sha_blocks(self, contract_shas):
        def no_sha_runner(pkg):
            return {"status": "pass", "gate_report": {"all_pass": True}}

        r = execute_parallel(
            {"packages": [{"id": "a", "write_scope": ["a/**"]}]},
            no_sha_runner, _good_integration, contract_shas={},
        )
        assert r["proceed"] is False
