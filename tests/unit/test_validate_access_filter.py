"""Гранулярные тесты validate_access_filter (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_access_filter import (  # noqa: F401
    DEMO,
    SCHEMA,
    _load,
    check,
    json,
)


@pytest.fixture(scope="module")
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(schema_example):
    assert check(schema_example) == []


@pytest.mark.unit
def test_real_demo_files_are_valid():
    if DEMO.is_dir():
        assert all(check(_load(f)) == [] for f in sorted(DEMO.glob("AFP-*.yaml")))


@pytest.mark.unit
def test_filter_stage_not_before_retrieval(schema_example):
    errs = check({**schema_example, "filter_stage": "after"})
    assert any("before_retrieval" in x for x in errs)


@pytest.mark.unit
def test_default_deny_false_is_error(schema_example):
    errs = check({**schema_example, "default_deny": False})
    assert any("default_deny" in x for x in errs)


@pytest.mark.unit
def test_role_without_access_rule(schema_example):
    less = {**schema_example, "rules": schema_example["rules"][:4]}
    errs = check(less)
    assert any("нет правила доступа" in x for x in errs)


@pytest.mark.unit
def test_secret_in_allowed_classes(schema_example):
    sec = {
        **schema_example,
        "rules": [
            {**schema_example["rules"][0], "allowed_classes": ["public", "secret"]}
        ]
        + schema_example["rules"][1:],
    }
    errs = check(sec)
    assert any("секреты не входят" in x for x in errs)


@pytest.mark.unit
def test_undeclared_data_class(schema_example):
    und = {
        **schema_example,
        "data_classes": ["public", "internal"],
        "rules": [
            {"role": "planner", "allowed_classes": ["confidential"]}
        ]
        + [
            {"role": r, "allowed_classes": ["public"]}
            for r in ["executor", "ui_reviewer", "security_reviewer", "integration"]
        ],
    }
    errs = check(und)
    assert any("не объявлен в data_classes" in x for x in errs)


@pytest.mark.unit
def test_broken_context_architecture(schema_example):
    errs = check({**schema_example, "context_architecture": "CAD1"})
    assert any("context_architecture" in x for x in errs)


@pytest.mark.unit
def test_duplicate_rule_for_role(schema_example):
    errs = check({**schema_example, "rules": schema_example["rules"] + [schema_example["rules"][0]]})
    assert any(">1 правила" in x for x in errs)
