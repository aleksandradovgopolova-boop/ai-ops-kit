"""Granular tests for validate_work_graph (migrated from selftest)."""
from __future__ import annotations

import copy

import pytest

from validate_work_graph import (  # noqa: F401
    DEMO,
    _load,
    _overlap,
    check_bundle,
    check_ip,
    check_wg,
    cross_check,
)


@pytest.fixture(scope="module")
def demo_data():
    """Load the demo work-graph data once."""
    wg = _load(DEMO / "work-graph.yaml")
    psd = _load(DEMO / "parallel-safety-decision.yaml")
    ip = _load(DEMO / "integration-plan.yaml")
    return wg, psd, ip


@pytest.mark.unit
@pytest.mark.slow
class TestValidateWorkGraph:
    """Validation of work-graph bundles."""

    def test_real_demo_bundle_is_valid(self):
        assert check_bundle(DEMO) == []

    def test_non_topological_integration_order_produces_error(self, demo_data):
        wg, _, _ = demo_data
        bad = copy.deepcopy(wg)
        bad["integration_order"] = ["wiring", "api", "ui"]
        assert any("топологичен" in x for x in check_wg(bad))

    def test_depends_on_nonexistent_package_produces_error(self, demo_data):
        wg, _, _ = demo_data
        bad = copy.deepcopy(wg)
        bad["packages"][2]["depends_on"] = ["ghost"]
        assert any("несуществующий" in x for x in check_wg(bad))

    def test_requires_new_integration_sha_false_produces_error(self, demo_data):
        _, _, ip = demo_data
        assert any(
            "requires_new_integration_sha" in x
            for x in check_ip({**ip, "requires_new_integration_sha": False})
        )

    def test_psd_parallel_safe_with_overlapping_write_scope(self, demo_data):
        wg, psd, ip = demo_data
        bad_wg = copy.deepcopy(wg)
        bad_wg["packages"][1]["write_scope"] = ["src/api/shared/**"]
        e = cross_check(bad_wg, psd, ip)
        assert any("пересекающиеся write_scope" in x for x in e)

    def test_psd_parallel_safe_for_dependent_packages(self, demo_data):
        wg, psd, ip = demo_data
        bad_psd = copy.deepcopy(psd)
        bad_psd["classifications"] = [
            {"packages": ["api", "wiring"], "safe": True, "reason": "x"}
        ]
        e = cross_check(wg, bad_psd, ip)
        assert any("связаны depends_on" in x for x in e)

    def test_psd_work_graph_mismatch(self, demo_data):
        wg, psd, ip = demo_data
        e = cross_check(wg, {**psd, "work_graph": "WG-999"}, ip)
        assert any("PSD.work_graph" in x for x in e)


@pytest.mark.unit
@pytest.mark.slow
class TestOverlapHelper:
    """Write-scope overlap detection."""

    def test_no_overlap_api_vs_ui(self):
        assert _overlap(["src/api/**"], ["src/ui/**"]) is False

    def test_overlap_src_vs_src_api(self):
        assert _overlap(["src/**"], ["src/api/**"]) is True
