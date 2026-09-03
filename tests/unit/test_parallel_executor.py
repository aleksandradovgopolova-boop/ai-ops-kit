"""Гранулярные тесты parallel_executor (мигрировано из test_parallel_executor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

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
