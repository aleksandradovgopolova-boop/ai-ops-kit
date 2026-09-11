"""Потолок на число top-level пакетов + покрытие концептуальными слоями — ратчет (#638).

ПОВОД — ВНЕШНЕЕ ПРОДУКТОВОЕ РЕВЮ 08.09.2026 (п.21, 22). Ратчет слоёв мерил СВЯЗНОСТЬ графа импортов
(взаимные пары, циклы), но НЕ количество пакетов. `AGENTS.md` прямо разрешал «новый модуль — в свой
пакет»: 19 top-level пакетов росли бы молча, и структура отражала бы историю разработки, а не
доменную модель.

ЧТО ЗДЕСЬ. Два ратчета поверх `packages/layering.yaml`:
  * `package_ceiling` — число top-level пакетов = ПОТОЛОК (сейчас 19). Новый пакет краснеет: новая
    capability живёт в существующем домене, рост числа требует архитектурного решения. Ходит вниз.
  * `conceptual_layers` — четыре РОЛЬ-слоя (DOMAIN/APPLICATION/POLICY/ADAPTERS), ортогональные пяти
    dependency-слоям. Каждый top-level пакет отнесён ровно к одному; новый обязан быть
    классифицирован. Документарно (без переезда файлов), но покрытие проверяется — маппинг в
    ARCHITECTURE.md не расходится с деревом молча.
"""
from __future__ import annotations

import copy

import pytest

from ai_ops_kit.validation import validate_layering as vl

SPEC = vl.load_spec()
FOUR = {"DOMAIN", "APPLICATION", "POLICY", "ADAPTERS"}


@pytest.mark.contract
def test_package_count_is_exactly_at_the_ceiling():
    assert vl.package_ceiling_errors(SPEC) == []
    assert (SPEC["package_ceiling"]["count"]) == len(vl.top_level_packages())


@pytest.mark.contract
def test_every_top_level_package_has_a_conceptual_layer():
    assert vl.conceptual_layer_errors(SPEC) == []
    classified = {p for layer in SPEC["conceptual_layers"] for p in layer["packages"]}
    assert classified == set(vl.top_level_packages())


@pytest.mark.contract
def test_the_conceptual_layers_are_the_named_four():
    names = [layer["name"] for layer in SPEC["conceptual_layers"]]
    assert set(names) == FOUR and len(names) == 4, names
    for layer in SPEC["conceptual_layers"]:
        assert len(layer.get("role", "").split()) >= 8, f"{layer['name']}: роль слоя не названа"


@pytest.mark.contract
def test_role_layers_are_orthogonal_to_dependency_layers():
    """Роль-слои — не переименование dependency-слоёв: хоть один пакет лежит в них по-разному."""
    dep = {p: layer["name"] for layer in SPEC["layers"] for p in layer["packages"]}
    role = {p: layer["name"] for layer in SPEC["conceptual_layers"] for p in layer["packages"]}
    # gates: dependency=capabilities, role=POLICY; providers: capabilities vs ADAPTERS
    assert role["gates"] == "POLICY" and dep["gates"] == "capabilities"
    assert role["providers"] == "ADAPTERS" and dep["providers"] == "capabilities"


# ─── пробы: ратчет обязан краснеть ──────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_a_new_top_level_package_is_caught(tmp_path):
    """Реальный новый пакет в дереве при неизменном потолке — красное."""
    for name in vl.top_level_packages() + ["newpkg"]:
        (tmp_path / name).mkdir()
    errs = vl.package_ceiling_errors(SPEC, surface=tmp_path)
    assert any("новый top-level пакет" in e for e in errs), errs


@pytest.mark.contract
def test_a_vanished_package_forces_the_ceiling_down(tmp_path):
    for name in vl.top_level_packages()[:-1]:      # на один меньше потолка
        (tmp_path / name).mkdir()
    errs = vl.package_ceiling_errors(SPEC, surface=tmp_path)
    assert any("опустить count" in e for e in errs), errs


@pytest.mark.contract
def test_a_ceiling_without_a_number_is_not_green():
    broken = copy.deepcopy(SPEC)
    broken["package_ceiling"] = {"reason": "нет числа"}
    assert any("потолка не существует" in e for e in vl.package_ceiling_errors(broken))


@pytest.mark.contract
def test_an_unclassified_package_is_caught(tmp_path):
    for name in vl.top_level_packages() + ["orphan"]:
        (tmp_path / name).mkdir()
    errs = vl.conceptual_layer_errors(SPEC, surface=tmp_path)
    assert any("orphan" in e and "без концептуального слоя" in e for e in errs), errs


@pytest.mark.contract
def test_a_package_named_in_two_role_layers_is_caught():
    dup = copy.deepcopy(SPEC)
    dup["conceptual_layers"][0]["packages"].append(dup["conceptual_layers"][1]["packages"][0])
    assert any("нескольких роль-слоях" in e for e in vl.conceptual_layer_errors(dup))


@pytest.mark.contract
def test_a_stale_package_in_the_mapping_is_caught():
    stale = copy.deepcopy(SPEC)
    stale["conceptual_layers"][0]["packages"].append("ghostpkg")
    assert any("ghostpkg" in e and "несуществующие" in e for e in vl.conceptual_layer_errors(stale))
