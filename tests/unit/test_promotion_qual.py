"""Гранулярные тесты promotion_qual (мигрировано из test_promotion_qual_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from promotion_qual import (
    execute,
    load_plan,
    preflight,
    runbook,
    verify_negatives,
)


@pytest.mark.unit
class TestLoadPlan:
    def test_real_plan_loads_valid(self):
        plan = load_plan()
        assert plan["plan_id"] == "PQP-001"


@pytest.mark.unit
class TestVerifyNegatives:
    def test_all_negatives_proven(self):
        plan = load_plan()
        neg = verify_negatives(plan)
        assert neg["proven"] == neg["total"]
        assert neg["total"] == 10


@pytest.mark.unit
class TestPreflight:
    def test_checks_cover_four_requirements(self):
        plan = load_plan()
        pf = preflight(plan)
        assert set(pf["checks"]) == {"provider_key", "git", "node_react", "scratch_repo"}

    def test_per_run_covers_all_runs(self):
        plan = load_plan()
        pf = preflight(plan)
        assert set(pf["per_run"]) == {r["id"] for r in plan["runs"]}


@pytest.mark.unit
class TestRunbook:
    def test_runbook_covers_three_runs(self):
        plan = load_plan()
        rb = runbook(plan)
        assert len(rb) == 3
        assert all(r["commands"] for r in rb)


@pytest.mark.unit
class TestExecute:
    def test_without_readiness_blocked(self):
        plan = load_plan()
        ex = execute(plan, dry_run=False)
        assert ex["status"] in ("blocked", "ready")
        assert "passed" not in ex["status"]

    def test_dry_run(self):
        plan = load_plan()
        exd = execute(plan, dry_run=True)
        assert exd["status"] == "dry-run"
