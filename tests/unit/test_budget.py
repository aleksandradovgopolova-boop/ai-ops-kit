"""Unit tests for tools/budget.py — execution budget enforcement."""
from __future__ import annotations

import pytest

from ai_ops_kit.shared import budget as budget_mod
from ai_ops_kit.shared.budget import Budget, BudgetExceeded


@pytest.mark.unit
class TestBudgetCreation:
    """Tests for Budget construction and from_dict."""

    def test_default_budget_unlimited(self):
        b = Budget()
        assert b.max_model_calls is None
        assert b.max_cost is None
        assert b.model_calls == 0
        assert b.cost == 0.0

    def test_budget_with_max_calls(self):
        b = Budget(max_model_calls=10)
        assert b.max_model_calls == 10
        assert b.remaining_calls() == 10

    def test_from_dict_reads_fields(self):
        b = Budget.from_dict({"max_model_calls": 5, "max_cost": 1.5})
        assert b.max_model_calls == 5
        assert b.max_cost == 1.5

    def test_from_dict_none_returns_unlimited(self):
        b = Budget.from_dict(None)
        assert b.max_model_calls is None
        assert b.max_cost is None

    def test_from_dict_empty_dict(self):
        b = Budget.from_dict({})
        assert b.max_model_calls is None


@pytest.mark.unit
class TestBudgetCharging:
    """Tests for charge_call() and limit enforcement."""

    def test_charge_increments_calls(self):
        b = Budget(max_model_calls=5)
        b.charge_call()
        b.charge_call()
        assert b.model_calls == 2
        assert b.remaining_calls() == 3

    def test_charge_exceeds_max_raises(self):
        b = Budget(max_model_calls=2)
        b.charge_call()
        b.charge_call()
        with pytest.raises(BudgetExceeded):
            b.charge_call()

    def test_ceiling_never_exceeded(self):
        """After BudgetExceeded, model_calls must NOT exceed the limit."""
        b = Budget(max_model_calls=2)
        b.charge_call()
        b.charge_call()
        with pytest.raises(BudgetExceeded):
            b.charge_call()
        assert b.model_calls == 2  # not 3
        assert b.remaining_calls() == 0

    def test_unlimited_budget_never_blocks(self):
        b = Budget()
        for _ in range(100):
            b.charge_call()
        assert b.model_calls == 100
        assert b.remaining_calls() is None

    def test_cost_budget_enforced(self):
        b = Budget(max_cost=1.0)
        b.charge_call(cost=0.6)
        with pytest.raises(BudgetExceeded):
            b.charge_call(cost=0.6)

    def test_cost_zero_does_not_trigger(self):
        b = Budget(max_cost=1.0)
        b.charge_call(cost=0.0)  # zero cost shouldn't trigger
        assert b.model_calls == 1


@pytest.mark.unit
class TestBudgetSerialization:
    """Tests for to_dict()."""

    def test_to_dict_contains_all_fields(self):
        b = Budget(max_model_calls=10, max_cost=5.0)
        b.charge_call(cost=1.0)
        d = b.to_dict()
        assert d["max_model_calls"] == 10
        assert d["model_calls"] == 1
        assert d["max_cost"] == 5.0
        assert d["cost"] == 1.0
        assert d["remaining_calls"] == 9


@pytest.mark.parametrize("declaration", [False, 0, [], {"max_model_calls": True},
    {"max_model_calls": -1}, {"max_model_calls": 1.5}, {"max_cost": float("nan")},
    {"max_physical_calls": 3}])
def test_invalid_budget_cannot_turn_into_unlimited(declaration):
    with pytest.raises(ValueError):
        Budget.from_dict(declaration)


@pytest.mark.parametrize("limits", [{"max_cost": 1}, {"max_duration": "1m"}])
def test_unknown_next_call_bound_refuses_before_charge(limits):
    budget = Budget.from_dict(limits)
    with pytest.raises(BudgetExceeded, match="unsupported"):
        budget.charge_call()
    assert budget.model_calls == 0


def test_unknown_cost_is_not_reported_as_zero():
    budget = Budget(max_model_calls=1)
    budget.charge_call()
    assert budget.to_dict()["cost"] is None


def test_shared_admission_is_bounded_across_real_threads():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    budget, start = Budget(max_model_calls=3), Barrier(12)
    def attempt(_):
        start.wait(5)
        try:
            budget.charge_call()
        except BudgetExceeded:
            return False
        return True
    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(attempt, range(12)))
    assert sum(admitted) == budget.model_calls == 3
    assert budget.remaining_calls() == 0


def test_existing_shared_counter_survives_resolution_and_conflicts_refuse():
    budget = Budget(max_model_calls=3)
    budget.charge_call()
    assert budget_mod.resolve_budget(budget, {"max_model_calls": 3}) is budget
    assert budget.model_calls == 1
    with pytest.raises(ValueError, match="conflict"):
        budget_mod.resolve_budget(budget, {"max_model_calls": 4})


def test_actual_runplan_preserves_declared_limits_without_aliasing():
    from ai_ops_kit.engine import run_plan
    declaration = {"max_model_calls": 3}
    plan = run_plan.build_plan({"task_type": "QUICK", "execution_budget": declaration}, workitem_id="capped")
    assert plan["execution_budget"]["max_model_calls"] == 3
    plan["execution_budget"]["max_model_calls"] = 9
    assert declaration["max_model_calls"] == 3


def test_child_schema_declares_actual_runtime_economy_vocabulary():
    import json
    from pathlib import Path
    from ai_ops_kit.engops import session_launcher
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/child-config.schema.json").read_text())
    block = schema["properties"]["session_economy"]
    assert set(session_launcher.AUTONOMY_DEFAULTS) <= set(block["properties"])
    assert block["additionalProperties"] is False


def test_controller_persists_actual_shared_limits(tmp_path):
    import yaml
    from ai_ops_kit.engine import ai_ops_run
    shared = Budget(max_model_calls=2)
    rep = ai_ops_run.run("T", {"task_type": "QUICK"}, tmp_path, feature="budget-plan",
                         engine="controller", execute=False, budget=shared)
    assert rep["status"] == "planned" and shared.model_calls == 0
    plan = yaml.safe_load((tmp_path / "features/budget-plan/run-plan.yaml").read_text())
    assert plan["execution_budget"]["max_model_calls"] == 2


@pytest.mark.parametrize("declaration", [{"max_model_calls": 0}, {"max_cost": 1}, {"max_duration": "1m"}])
def test_controller_refuses_before_any_execution_artifact(tmp_path, declaration):
    from ai_ops_kit.engine import ai_ops_run
    calls = []
    rep = ai_ops_run.run("T", {}, tmp_path, budget=declaration, execute=True,
                        proposer=lambda _: calls.append("model"))
    assert rep["ready_for_pr"] is False and rep["blocked_by"] == "execution-budget"
    assert calls == [] and list(tmp_path.iterdir()) == []
