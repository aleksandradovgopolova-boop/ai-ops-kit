"""Гранулярные тесты validate_capability_scope (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_capability_scope import (  # noqa: F401
    DEMO,
    SCHEMA,
    WG_DEMO,
    _load,
    _load_dir,
    check,
    check_coverage,
    json,
)


@pytest.fixture(scope="module")
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(schema_example):
    assert check(schema_example) == []


@pytest.mark.unit
def test_network_without_justification(schema_example):
    errs = check(
        {**schema_example, "allowed_permissions": ["read-only", "network"]}
    )
    assert any("network" in x for x in errs)


@pytest.mark.unit
def test_network_with_justification(schema_example):
    errs = check(
        {
            **schema_example,
            "allowed_permissions": ["read-only", "network"],
            "justification": {"network": "внешний вызов платёжного API"},
        }
    )
    assert errs == []


@pytest.mark.unit
def test_execution_without_justification(schema_example):
    errs = check({**schema_example, "allowed_permissions": ["execution"]})
    assert any("execution" in x for x in errs)


@pytest.mark.unit
def test_unknown_permission_level(schema_example):
    errs = check({**schema_example, "allowed_permissions": ["god-mode"]})
    assert any("неизвестный уровень" in x for x in errs)


@pytest.mark.unit
def test_broken_id(schema_example):
    errs = check({**schema_example, "id": "PCS1"})
    assert any("id" in x for x in errs)


@pytest.mark.unit
def test_full_package_coverage():
    wg = {"id": "WG-001", "packages": [{"id": "api"}, {"id": "ui"}, {"id": "wiring"}]}
    full = [
        {"id": "PCS-001", "work_graph": "WG-001", "package": "api"},
        {"id": "PCS-002", "work_graph": "WG-001", "package": "ui"},
        {"id": "PCS-003", "work_graph": "WG-001", "package": "wiring"},
    ]
    assert check_coverage(wg, full) == []


@pytest.mark.unit
def test_package_without_pcs():
    wg = {"id": "WG-001", "packages": [{"id": "api"}, {"id": "ui"}, {"id": "wiring"}]}
    full = [
        {"id": "PCS-001", "work_graph": "WG-001", "package": "api"},
        {"id": "PCS-002", "work_graph": "WG-001", "package": "ui"},
    ]
    errs = check_coverage(wg, full)
    assert any("БЕЗ capability-scope" in x for x in errs)


@pytest.mark.unit
def test_pcs_for_package_outside_wg():
    wg = {"id": "WG-001", "packages": [{"id": "api"}, {"id": "ui"}, {"id": "wiring"}]}
    full = [
        {"id": "PCS-001", "work_graph": "WG-001", "package": "api"},
        {"id": "PCS-002", "work_graph": "WG-001", "package": "ui"},
        {"id": "PCS-003", "work_graph": "WG-001", "package": "wiring"},
        {"id": "PCS-009", "work_graph": "WG-001", "package": "ghost"},
    ]
    errs = check_coverage(wg, full)
    assert any("вне WG-001" in x for x in errs)


@pytest.mark.unit
def test_duplicate_pcs_for_package():
    wg = {"id": "WG-001", "packages": [{"id": "api"}, {"id": "ui"}, {"id": "wiring"}]}
    full = [
        {"id": "PCS-001", "work_graph": "WG-001", "package": "api"},
        {"id": "PCS-002", "work_graph": "WG-001", "package": "ui"},
        {"id": "PCS-003", "work_graph": "WG-001", "package": "wiring"},
        {"id": "PCS-009", "work_graph": "WG-001", "package": "api"},
    ]
    errs = check_coverage(wg, full)
    assert any(">1 PCS" in x for x in errs)


@pytest.mark.unit
def test_real_pcs_are_valid():
    real = _load_dir(DEMO)
    assert all(check(p) == [] for p in real) and len(real) >= 1


@pytest.mark.unit
def test_real_pcs_cover_wg001():
    if WG_DEMO.exists():
        real = _load_dir(DEMO)
        if real:
            assert check_coverage(_load(WG_DEMO), real) == []
