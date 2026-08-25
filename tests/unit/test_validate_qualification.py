"""Granular tests for validate_qualification (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_qualification import (  # noqa: F401
    PKG,
    check,
    yaml,
)


@pytest.fixture
def valid_workflows():
    return {"QUICK", "ENGINEERING", "PRODUCT"}


@pytest.fixture
def valid_package():
    return {
        "kind": "qualification-scenarios",
        "scenarios": [{
            "id": "s1", "title": "t", "task": "do", "task_type": "QUICK",
            "acceptance": ["a"], "proves": "p", "flags": ["--sandbox"],
        }],
        "os_stack_matrix": {"os": ["macOS"], "stacks": ["node"]},
    }


@pytest.mark.unit
def test_valid_package_no_errors(valid_package, valid_workflows):
    assert check(valid_package, valid_workflows) == []


@pytest.mark.unit
def test_unknown_task_type_raises_error(valid_package, valid_workflows):
    bad = {**valid_package, "scenarios": [{
        "id": "s1", "title": "t", "task": "d", "task_type": "NOPE",
        "acceptance": ["a"], "proves": "p",
    }]}
    assert any("NOPE" in e for e in check(bad, valid_workflows))


@pytest.mark.unit
def test_unknown_flag_raises_error(valid_package, valid_workflows):
    bad = {**valid_package, "scenarios": [{
        "id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
        "acceptance": ["a"], "proves": "p", "flags": ["--ghost"],
    }]}
    assert any("--ghost" in e for e in check(bad, valid_workflows))


@pytest.mark.unit
def test_missing_required_field_raises_error(valid_workflows):
    pkg = {
        "kind": "qualification-scenarios",
        "scenarios": [{
            "id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
            "acceptance": ["a"],
        }],
        "os_stack_matrix": {"os": ["m"], "stacks": ["n"]},
    }
    assert any("proves" in e for e in check(pkg, valid_workflows))


@pytest.mark.unit
def test_missing_matrix_raises_error(valid_workflows):
    pkg = {
        "kind": "qualification-scenarios",
        "scenarios": [{
            "id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
            "acceptance": ["a"], "proves": "p",
        }],
    }
    assert any("os_stack_matrix" in e for e in check(pkg, valid_workflows))


@pytest.mark.unit
def test_shipped_scenarios_yaml_is_valid():
    real = PKG / "qualification" / "scenarios.yaml"
    if real.exists():
        assert check(yaml.safe_load(real.read_text(encoding="utf-8"))) == []
