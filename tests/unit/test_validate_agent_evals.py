"""Гранулярные тесты validate_agent_evals (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_agent_evals import (  # noqa: F401
    check,
    eval_structure_errors,
)


@pytest.mark.unit
def test_changed_agent_without_eval():
    errs = check(["agents/core/task-planner.md"], evals_present=set())
    assert len(errs) == 1


@pytest.mark.unit
def test_changed_agent_with_eval():
    errs = check(["agents/core/task-planner.md"], evals_present={"task-planner"})
    assert len(errs) == 0


@pytest.mark.unit
def test_non_agent_changes():
    errs = check(
        ["registry/agents.yaml", "agents/README.md", "workflows/release.md"],
        evals_present=set(),
    )
    assert len(errs) == 0


@pytest.mark.unit
def test_existing_eval_structure_valid():
    assert eval_structure_errors("code-reviewer") == []


@pytest.mark.unit
def test_missing_eval_structure():
    assert len(eval_structure_errors("__nope__")) >= 1
