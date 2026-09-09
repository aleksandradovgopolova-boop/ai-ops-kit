# -*- coding: utf-8 -*-
"""Инвентарь «объявлено → исполняется» имеет ЗУБЫ (validate_enforcement_inventory).

Три обязательных теста на capability (AGENTS.md):
  * positive     — инвентарь репозитория валиден: каждый dev-инструмент и baseline покрыт,
                   доказательства резолвятся; mypy честно помечен unenforced;
  * fail-closed  — необъявленное исполнение (инструмент без записи), протухшее доказательство
                   (enforced_at не находит паттерн), беспричинный unenforced и мёртвый baseline —
                   каждый краснеет;
  * side-effect  — declared_dev_tools реально читает ОБА источника (requirements-dev + pyproject).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "ai_ops_kit" / "validation"))

import validate_enforcement_inventory as vei  # noqa: E402

pytestmark = [pytest.mark.unit]


# ─── positive: реальный репозиторий чист ────────────────────────────────────────────────────────

def test_real_repository_inventory_is_valid(capsys):
    rc = vei.main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ENFORCEMENT-INVENTORY-OK" in out, out


def test_mypy_is_now_enforced_with_resolving_evidence():
    """F-05 ЗАКРЫТ: mypy включён на фундаменте, и его доказательство исполнения РЕАЛЬНО резолвится.

    До «реши mypy» инвентарь честно звал его unenforced; теперь звал бы ложью, если бы enforced_at
    не находился. Тест держит именно связку «enforced -> доказательство существует», а не слово.
    """
    spec = vei.load_spec()
    mypy = next(t for t in spec["dev_tools"] if t["name"] == "mypy")
    assert mypy["status"] == "enforced", mypy
    ea = mypy["enforced_at"]
    assert vei._resolves(vei.PKG, ea["file"], ea["pattern"]), ea


def test_declared_dev_tools_reads_both_sources():
    """side-effect: опись объявленного строится по requirements-dev И pyproject [dev]."""
    declared = vei.declared_dev_tools()
    assert {"pytest", "ruff", "mypy", "pre-commit"} <= declared, declared


# ─── fail-closed: каждый класс нарушения краснеет ───────────────────────────────────────────────

def test_undeclared_enforcement_is_caught():
    """Инструмент объявлен в зависимостях, но не в инвентаре — молча невидимое исполнение."""
    spec = vei.load_spec()
    thin = dict(spec, dev_tools=[t for t in spec["dev_tools"] if t["name"] != "ruff"])
    errors = vei.check(thin)
    assert any("ruff" in e and "не в инвентаре" in e for e in errors), errors


def test_stale_inventory_entry_is_caught():
    """Запись про инструмент, которого в зависимостях уже нет, — мёртвая, краснеет."""
    spec = vei.load_spec()
    fat = dict(spec, dev_tools=list(spec["dev_tools"]) + [
        {"name": "black", "status": "enforced",
         "enforced_at": {"file": "pyproject.toml", "pattern": "black"}}])
    errors = vei.check(fat)
    assert any("black" in e and "мёртвая запись" in e for e in errors), errors


def test_rotted_evidence_is_caught():
    """enforced_at, чей паттерн не находится в файле, — протухшее доказательство."""
    spec = vei.load_spec()
    broken = dict(spec, dev_tools=[
        (dict(t, enforced_at={"file": ".github/workflows/package-quality.yml",
                              "pattern": "этого-паттерна-точно-нет- zzz"})
         if t["name"] == "ruff" else t)
        for t in spec["dev_tools"]])
    errors = vei.check(broken)
    assert any("ruff" in e and "протухло" in e for e in errors), errors


def test_unenforced_without_reason_is_caught():
    """unenforced без причины — необъяснённое «объявлено, но не исполняется»."""
    spec = vei.load_spec()
    broken = dict(spec, dev_tools=[
        (dict(t, status="unenforced", reason="") if t["name"] == "mypy" else t)
        for t in spec["dev_tools"]])
    # у mypy уберём reason и заодно оставим его объявленным — проверяем именно «без причины»
    for t in broken["dev_tools"]:
        if t["name"] == "mypy":
            t.pop("reason", None)
    errors = vei.check(broken)
    assert any("mypy" in e and "без причины" in e for e in errors), errors


def test_baseline_not_read_by_its_consumer_is_caught():
    """consumed_by, который baseline не упоминает, — заявленный потребитель его не читает."""
    spec = vei.load_spec()
    broken = dict(spec, ratchet_baselines=[
        {"name": "packages/module-size-baseline.yaml",
         "consumed_by": "ai_ops_kit/validation/validate_layering.py"}]  # layering его не читает
        + [b for b in spec["ratchet_baselines"] if "module-size" not in b["name"]])
    errors = vei.check(broken)
    assert any("module-size-baseline" in e and "не упоминает" in e for e in errors), errors
