"""Unit tests for tools/atomic_planner.py — work package assessment and decomposition."""
from __future__ import annotations

from pathlib import Path

import pytest

import atomic_planner


@pytest.fixture
def child_root(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
    return root


@pytest.mark.unit
class TestEstimate:
    """Tests for estimate(): work package sizing."""

    def test_estimate_returns_subsystems(self, child_root):
        est = atomic_planner.estimate({"affected_areas": ["core", "auth"]}, child_root=child_root)
        assert est["subsystems"] == ["auth", "core"]  # sorted

    def test_estimate_has_completion_criterion(self, child_root):
        est = atomic_planner.estimate({"size": "small"}, child_root=child_root)
        assert est["completion_criterion"]


@pytest.mark.unit
class TestAssess:
    """Tests for assess(): decomposition decision."""

    def test_atomic_small_single_subsystem(self, child_root):
        result = atomic_planner.assess(
            {"task_type": "QUICK", "size": "small", "affected_areas": ["core"]},
            child_root=child_root)
        assert result["should_decompose"] is False
        assert result["atomic"] is True

    def test_many_subsystems_triggers_decomposition(self, child_root):
        result = atomic_planner.assess(
            {"task_type": "ENGINEERING", "size": "medium",
             "affected_areas": ["catalog", "orders", "billing", "search"]},
            child_root=child_root)
        assert result["should_decompose"] is True
        assert "by-subsystem" in result["decomposition_axes"]

    def test_independent_results_triggers_by_result(self, child_root):
        result = atomic_planner.assess(
            {"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
             "independent_results": 3},
            child_root=child_root)
        assert "by-result" in result["decomposition_axes"]

    def test_large_size_triggers_by_size(self, child_root):
        result = atomic_planner.assess(
            {"task_type": "ENGINEERING", "size": "large", "affected_areas": ["core"]},
            child_root=child_root)
        assert "by-size" in result["decomposition_axes"]

    def test_constraint_note_present(self, child_root):
        result = atomic_planner.assess({"size": "small", "affected_areas": ["core"]},
                                       child_root=child_root)
        assert "продуктовый смысл" in result["constraint_note"]

    def test_acceptance_criteria_present(self, child_root):
        result = atomic_planner.assess({"size": "small", "affected_areas": ["core"]},
                                       child_root=child_root)
        assert len(result["acceptance"]) == 3


@pytest.mark.unit
class TestDecompose:
    """Tests for decompose(): concrete work package generation."""

    def test_atomic_has_no_packages(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "QUICK", "size": "small", "affected_areas": ["core"]},
            wid="wi-a", child_root=child_root)
        assert result["work_packages"] == []
        assert result["primary_axis"] is None

    def test_by_subsystem_creates_packages(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "ENGINEERING", "size": "medium",
             "affected_areas": ["catalog", "orders", "billing", "search"]},
            wid="wi-b", child_root=child_root)
        assert result["primary_axis"] == "by-subsystem"
        assert len(result["work_packages"]) == 4
        # First package has no deps, second depends on first
        assert result["work_packages"][0]["depends_on"] == []
        assert result["work_packages"][1]["depends_on"] == [result["work_packages"][0]["id"]]

    def test_by_result_creates_n_packages(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
             "independent_results": 3},
            wid="wi-c", child_root=child_root)
        assert result["primary_axis"] == "by-result"
        assert len(result["work_packages"]) == 3

    def test_size_creates_two_packages(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "ENGINEERING", "size": "xl", "affected_areas": ["core"]},
            wid="wi-d", child_root=child_root)
        assert len(result["work_packages"]) == 2
        assert result["work_packages"][1]["depends_on"] == [result["work_packages"][0]["id"]]

    def test_packages_have_write_scope(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "ENGINEERING", "size": "medium",
             "affected_areas": ["catalog", "orders"]},
            wid="wi-e", child_root=child_root)
        for pkg in result["work_packages"]:
            assert "write_scope" in pkg

    def test_human_confirms_flag(self, child_root):
        result = atomic_planner.decompose(
            {"task_type": "ENGINEERING", "size": "large", "affected_areas": ["core"]},
            wid="wi-f", child_root=child_root)
        assert result["human_confirms"] is True
