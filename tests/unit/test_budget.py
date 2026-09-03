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
