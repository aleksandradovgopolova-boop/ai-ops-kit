"""Доменная ось Product/Work/Run/Decision/Outcome НАЗВАНА данными — и её имена ложатся на РЕАЛЬНЫЙ
механизм (issue #630, внешнее ревью 08.09.2026).

`registry/product-operating-model.yaml -> domain_model` — не декларация в вакууме: каждая из пяти
сущностей заявляет `implemented_by` со `status` и `where`, а этот тест ПРОВЕРЯЕТ, что заявленный
файл механизма реально существует, статус честен, и объявлен инвариант «Work владеет жизненным
циклом». Тот же приём, что у test_decision_boundary.py для границы решений.

Тест ПОВЕДЕНЧЕСКИЙ: импортирует продуктовый валидатор кита (`validate_product_model`) и ЗОВЁТ его
`check_domain_model` над реальным реестром — доказывает, что порча оси краснеет, а не просто
описана в комментарии.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.validation import validate_product_model as vpm

KIT = Path(__file__).resolve().parents[2]
MODEL_REL = "registry/product-operating-model.yaml"


@pytest.fixture(scope="module")
def model():
    doc = yaml.safe_load((KIT / MODEL_REL).read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "product-operating-model.yaml не разобран в mapping"
    return doc


def _entities(model):
    return {x["id"]: x for x in model["domain_model"]["entities"]}


# ── форма оси: ровно пять названных сущностей ────────────────────────────────────────────────────

def test_domain_model_declares_exactly_five_entities(model):
    ids = set(_entities(model))
    assert ids == {"product", "work", "run", "decision", "outcome"}, (
        f"доменная ось должна называть ровно пять сущностей, а не {ids}")


def test_each_entity_owns_something_and_has_one_liner(model):
    for eid, ent in _entities(model).items():
        assert (ent.get("one_liner") or "").strip(), f"{eid}: нет one_liner"
        assert ent.get("owns"), f"{eid}: пустой owns — сущность ничем не владеет"


# ── честность деклараций implemented_by ──────────────────────────────────────────────────────────

def test_implemented_by_status_is_honest(model):
    for eid, ent in _entities(model).items():
        for row in ent.get("implemented_by") or []:
            assert row.get("status") in ("implemented", "planned"), (
                f"{eid}: статус '{row.get('status')}' не из (implemented, planned)")


def test_named_mechanism_files_exist(model):
    """Заявленный файл механизма (`where`) РЕАЛЬНО существует — связь не выдумана."""
    for eid, ent in _entities(model).items():
        for row in ent.get("implemented_by") or []:
            where = row.get("where")
            if where is None:
                assert row.get("status") == "planned", (
                    f"{eid}: implemented без файла — where не может быть null")
                continue
            assert (KIT / where).exists(), f"{eid}: названного файла нет — {where}"


# ── инвариант: Work владеет жизненным циклом ──────────────────────────────────────────────────────

def test_work_owns_lifecycle_invariant_declared(model):
    invs = {x["id"]: x for x in model["domain_model"].get("invariants") or []}
    assert "work_owns_lifecycle" in invs, "не объявлен инвариант work_owns_lifecycle"
    inv = invs["work_owns_lifecycle"]
    assert (inv.get("rule") or "").strip(), "work_owns_lifecycle: нет rule"
    assert (inv.get("never") or "").strip(), "work_owns_lifecycle: нет never"


# ── валидатор кита краснеет на порче оси (поведенческий вызов продуктового кода) ──────────────────

def test_validator_passes_on_real_registry(model):
    assert vpm.check_domain_model(model) == [], (
        "валидатор нашёл ошибки в реальной доменной оси — реестр или ссылки испорчены")


def test_validator_reddens_on_missing_entity(model):
    import copy
    broken = copy.deepcopy(model)
    broken["domain_model"]["entities"] = [
        e for e in broken["domain_model"]["entities"] if e["id"] != "work"]
    errs = vpm.check_domain_model(broken)
    assert any("work" in x for x in errs), "убрали Work из оси, а валидатор смолчал"


def test_validator_reddens_on_fabricated_mechanism_file(model):
    import copy
    broken = copy.deepcopy(model)
    broken["domain_model"]["entities"][0]["implemented_by"] = [
        {"where": "ai_ops_kit/does_not_exist.py", "status": "implemented"}]
    errs = vpm.check_domain_model(broken)
    assert any("does_not_exist" in x for x in errs), (
        "implemented-строка указывает на несуществующий файл, а валидатор смолчал")
