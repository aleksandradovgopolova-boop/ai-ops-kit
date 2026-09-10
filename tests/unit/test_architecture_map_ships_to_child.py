"""Машинный реестр Архитектурной конституции + слой-подсказка едут в дочку (#825).

По образцу `test_constitution_map_ships_to_child.py` (uiux). Держим ЧЕРЕЗ ГРАНИЦУ ПОСТАВКИ:
машинная карта `constitution_id -> статья` (`standards/architecture/rules.yaml`) и оперативный
слой-подсказка агенту (`arch.rules.md`) копируются в `.ai/managed` дочки — иначе конституция
остаётся прозой в репозитории кита, а её ID в дочке нечем резолвить.

ПОВЕДЕНЧЕСКИЙ: импортирует `installer` и ЗОВЁТ `managed_set()` — сверка идёт против реального
набора доставки, а не против чтения файла глазами.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_REL = "standards/architecture/rules.yaml"
OPS_REL = "standards/architecture/arch.rules.md"


def _installer():
    spec = importlib.util.spec_from_file_location(
        "_inst_for_arch_map", REPO_ROOT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _delivered() -> dict:
    """{relative_target: source_path} по фактическому managed_set() (дефолт — все пакеты)."""
    return {rel: src for src, rel in _installer().managed_set()}


@pytest.mark.unit
def test_machine_registry_ships_to_child():
    """Карта статей едет в дочку — ID конституции там резолвится."""
    delivered = _delivered()
    assert RULES_REL in delivered, (
        f"{RULES_REL} не входит в managed_set — конституция не доедет до дочки")


@pytest.mark.unit
def test_operational_layer_stays_parent_side():
    """Оперативный слой arch.rules.md — родительский (footprint-бюджет узкий): в дочку едет только
    компактный реестр rules.yaml, из которого при нужде производится тот же слой. Как uiux."""
    delivered = _delivered()
    assert OPS_REL not in delivered, (
        f"{OPS_REL} не должен ехать в дочку — едет только компактный реестр rules.yaml")


@pytest.mark.unit
def test_delivered_registry_is_resolvable():
    """Доставляемый реестр — валидный YAML со статьями и стабильными ID (не пустой/битый)."""
    delivered = _delivered()
    src = delivered[RULES_REL]
    doc = yaml.safe_load(Path(src).read_text(encoding="utf-8"))
    rules = doc.get("rules") or []
    assert rules, "доставляемый rules.yaml пуст — нечего резолвить в дочке"
    ids = {r["id"] for r in rules}
    assert doc.get("rules_total") == len(rules) == len(ids), "битый реестр: счётчик/дубли ID"
    # каждая статья несёт машинные поля, по которым дочка судит (gate/enforced_in)
    assert all("gate" in r and "enforced_in" in r for r in rules), "в реестре нет gate/enforced_in"


@pytest.mark.unit
def test_source_constitution_does_not_ship():
    """Источник (27-КБ ARCHITECTURE_CONSTITUTION.md) в дочку НЕ едет — только компактные генераты."""
    delivered = _delivered()
    assert "standards/architecture/ARCHITECTURE_CONSTITUTION.md" not in delivered, (
        "тяжёлый источник не должен ехать в дочку — едут только rules.yaml + arch.rules.md")
