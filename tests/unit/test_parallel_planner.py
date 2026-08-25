"""Гранулярные тесты parallel_planner (мигрировано из test_parallel_planner_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from parallel_planner import (
    WG_DEMO,
    can_parallel,
    integration_decision,
    integration_gate,
    plan,
    yaml,
)


# ── can_parallel ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCanParallel:
    def test_disjoint_independent_are_parallel(self):
        ok, _ = can_parallel(
            {"id": "a", "write_scope": ["src/a/**"]},
            {"id": "b", "write_scope": ["src/b/**"]})
        assert ok is True

    def test_overlapping_scope_serialized(self):
        ok, r = can_parallel(
            {"id": "a", "write_scope": ["src/**"]},
            {"id": "b", "write_scope": ["src/b/**"]})
        assert ok is False
        assert "write_scope" in r

    def test_depends_on_serialized(self):
        ok, r = can_parallel(
            {"id": "a", "write_scope": ["x/**"]},
            {"id": "b", "write_scope": ["y/**"], "depends_on": ["a"]})
        assert ok is False
        assert "depends_on" in r

    def test_global_scope_overlaps(self):
        """Глобальный ** пересекается с src/b/** -> сериализация."""
        ok, r = can_parallel(
            {"id": "a", "write_scope": ["**"]},
            {"id": "b", "write_scope": ["src/b/**"]})
        assert ok is False
        assert "write_scope" in r

    def test_undeclared_scope_serialized(self):
        """Незадекларированный write_scope -> сериализация (fail-closed)."""
        ok, r = can_parallel(
            {"id": "a", "write_scope": ["src/a/**"]},
            {"id": "b"})
        assert ok is False
        assert "write_scope" in r


# ── plan ────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPlan:
    @pytest.fixture(autouse=True)
    def load_demo(self):
        if WG_DEMO.exists():
            self.wg = yaml.safe_load(WG_DEMO.read_text(encoding="utf-8"))
        else:
            self.wg = None

    def test_demo_parallel_groups(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        p = plan(self.wg)
        assert any(set(g) == {"api", "ui"} for g in p["parallel_groups"])

    def test_demo_mode_hybrid(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        assert plan(self.wg)["mode"] == "hybrid"

    def test_demo_contract_first(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        assert "OrderContract" in plan(self.wg)["contract_first"]

    def test_demo_integration_order(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        assert plan(self.wg)["integration_order"][-1] == "wiring"

    def test_demo_fan_in_required(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        assert plan(self.wg)["fan_in_required"] is True

    def test_demo_valid(self):
        if self.wg is None:
            pytest.skip("WG_DEMO not found")
        assert plan(self.wg)["valid"] is True

    def test_shared_contract(self):
        wg = {"packages": [
            {"id": "a", "write_scope": ["a/**"], "shared_contracts": ["C"]},
            {"id": "b", "write_scope": ["b/**"], "shared_contracts": ["C"]},
        ]}
        assert plan(wg)["contract_first"] == ["C"]

    def test_single_package_mode(self):
        assert plan({"packages": [{"id": "a", "write_scope": ["a/**"]}]})["mode"] == "single"

    def test_dependency_chain_sequential(self):
        seq = plan({"packages": [
            {"id": "a", "write_scope": ["a/**"]},
            {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]},
        ]})
        assert seq["mode"] == "sequential"

    def test_cycle_invalid(self):
        cyc = plan({"packages": [
            {"id": "a", "write_scope": ["a/**"], "depends_on": ["b"]},
            {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]},
        ]})
        assert cyc["valid"] is False
        assert any("integration_order" in e for e in cyc["errors"])

    def test_broken_dependency_invalid(self):
        brk = plan({"packages": [{"id": "a", "write_scope": ["a/**"], "depends_on": ["ghost"]}]})
        assert brk["valid"] is False

    def test_duplicate_package_id_invalid(self):
        dup = plan({"packages": [
            {"id": "a", "write_scope": ["a/**"]},
            {"id": "a", "write_scope": ["b/**"]},
        ]})
        assert dup["valid"] is False
        assert any("дубликат" in e for e in dup["errors"])

    def test_non_dict_package_invalid(self):
        nd = plan({"packages": ["not-a-dict", {"id": "a", "write_scope": ["a/**"]}]})
        assert nd["valid"] is False
        assert any("не являются объектом" in e for e in nd["errors"])


# ── integration_decision ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestIntegrationDecision:
    def test_one_fail_blocks(self):
        assert integration_decision({"a": "pass", "b": "fail"})["proceed"] is False

    def test_all_pass_no_conflict_aggregate_green(self):
        d = integration_decision({"a": "pass", "b": "pass"}, conflicts=0, base_moved=False, aggregate_ok=True)
        assert d["proceed"]
        assert d["integration_sha_required"]
        assert d["open_pr"]

    def test_merge_conflict_blocks(self):
        assert integration_decision({"a": "pass", "b": "pass"}, conflicts=1)["proceed"] is False

    def test_base_moved_revalidation(self):
        d = integration_decision({"a": "pass", "b": "pass"}, base_moved=True)
        assert d.get("revalidation_required") is True
        assert d["open_pr"] is False

    def test_aggregate_fail_no_pr(self):
        d = integration_decision({"a": "pass", "b": "pass"}, aggregate_ok=False)
        assert d["integration_sha_required"] is True
        assert d["open_pr"] is False

    def test_empty_set_blocks(self):
        assert integration_decision({})["proceed"] is False


# ── integration_gate ────────────────────────────────────────────────────────────

INT = "1234567abc"
CSHA = "c0ffee0abc"
GOOD_RESULTS = {
    "api": {"status": "pass", "sha": "aaa1110", "gate_report": {"all_pass": True, "tested_revision": "aaa1110"}},
    "ui": {"status": "pass", "sha": "bbb2220", "gate_report": {"all_pass": True, "tested_revision": "bbb2220"}},
}


@pytest.mark.unit
class TestIntegrationGate:
    def test_evidentiary_set_opens_pr(self):
        g = integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": CSHA},
            aggregate={"all_pass": True, "tested_revision": INT}, integration_sha=INT)
        assert g["proceed"]
        assert g["integration_sha_required"]
        assert g["open_pr"]

    def test_missing_package_blocks(self):
        assert integration_gate(["api", "ui"], {"api": GOOD_RESULTS["api"]})["proceed"] is False

    def test_extra_package_blocks(self):
        assert integration_gate(["api"], GOOD_RESULTS)["proceed"] is False

    def test_bare_string_blocks(self):
        assert integration_gate(["api"], {"api": "pass"})["proceed"] is False

    def test_no_sha_blocks(self):
        assert integration_gate(
            ["api"], {"api": {"status": "pass", "gate_report": {"all_pass": True}}})["proceed"] is False

    def test_gate_report_not_green_blocks(self):
        assert integration_gate(
            ["api"], {"api": {"status": "pass", "sha": "aaa1110",
             "gate_report": {"all_pass": False, "tested_revision": "aaa1110"}}})["proceed"] is False

    def test_tested_revision_mismatch_blocks(self):
        assert integration_gate(
            ["api"], {"api": {"status": "pass", "sha": "aaa1110",
             "gate_report": {"all_pass": True, "tested_revision": "WRONG99"}}})["proceed"] is False

    def test_no_contract_sha_blocks(self):
        assert integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={})["proceed"] is False

    def test_unrealistic_contract_sha_blocks(self):
        assert integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": "nope"})["proceed"] is False

    def test_bare_bool_aggregate_proceed_no_pr(self):
        g = integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": CSHA}, aggregate=True)
        assert g["proceed"] is True
        assert g["open_pr"] is False

    def test_aggregate_wrong_sha_no_pr(self):
        g = integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": CSHA},
            aggregate={"all_pass": True, "tested_revision": "OTHER99"}, integration_sha=INT)
        assert g["proceed"] is True
        assert g["open_pr"] is False

    def test_merge_conflict_blocks(self):
        assert integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": CSHA}, conflicts=1)["proceed"] is False

    def test_base_moved_revalidation(self):
        g = integration_gate(
            ["api", "ui"], GOOD_RESULTS, shared_contracts=["OrderContract"],
            contract_shas={"OrderContract": CSHA}, base_moved=True)
        assert g.get("revalidation_required") is True
        assert g["open_pr"] is False

    def test_empty_workgraph_blocks(self):
        assert integration_gate([], {})["proceed"] is False
