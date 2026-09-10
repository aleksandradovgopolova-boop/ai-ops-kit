# -*- coding: utf-8 -*-
"""Инвентарь «объявлено → исполняется» имеет ЗУБЫ (validate_enforcement_inventory).

Три обязательных теста на capability (AGENTS.md):
  * positive     — инвентарь репозитория валиден: каждый dev-инструмент, pre-commit-ХУК и baseline
                   покрыт, доказательства резолвятся; mypy честно enforced, часть хуков — local_only;
  * fail-closed  — необъявленное исполнение (инструмент/хук без записи), протухшее доказательство
                   (enforced_at не находит паттерн), беспричинный unenforced/local_only и мёртвый
                   baseline — каждый краснеет;
  * side-effect  — declared_dev_tools реально читает ОБА источника (requirements-dev + pyproject),
                   declared_hooks реально читает id хуков из .pre-commit-config.yaml.
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


# ─── pre-commit-хуки: охват + резолюция доказательств ───────────────────────────────────────────

def test_every_declared_hook_is_in_inventory():
    """Каждый хук из .pre-commit-config.yaml присутствует в инвентаре — иначе охват дыряв."""
    spec = vei.load_spec()
    inv = {h["id"] for h in spec.get("pre_commit_hooks") or []}
    declared = vei.declared_hooks()
    assert declared, "не удалось прочитать ни одного хука из .pre-commit-config.yaml"
    assert declared <= inv, f"хуки объявлены, но не в инвентаре: {sorted(declared - inv)}"


def test_undeclared_hook_is_caught():
    """Мутация: хук объявлен в .pre-commit-config, но отсутствует в инвентаре — check() краснеет."""
    spec = vei.load_spec()
    victim = next(iter(vei.declared_hooks()))
    thin = dict(spec, pre_commit_hooks=[
        h for h in spec["pre_commit_hooks"] if h["id"] != victim])
    errors = vei.check(thin)
    assert any(victim in e and "не в инвентаре" in e for e in errors), errors


def test_stale_hook_entry_is_caught():
    """Запись про хук, которого в .pre-commit-config уже нет, — мёртвая, краснеет."""
    spec = vei.load_spec()
    fat = dict(spec, pre_commit_hooks=list(spec["pre_commit_hooks"]) + [
        {"id": "хук-которого-нет", "status": "local_only", "reason": "выдумка"}])
    errors = vei.check(fat)
    assert any("хук-которого-нет" in e and "мёртвая запись" in e for e in errors), errors


def test_every_enforced_hook_evidence_resolves():
    """Каждый enforced-хук имеет enforced_at, чей паттерн реально находится в названном файле."""
    spec = vei.load_spec()
    enforced = [h for h in spec["pre_commit_hooks"] if h["status"] == "enforced"]
    assert enforced, "ожидался хотя бы один enforced-хук (ruff/selftest-smoke/commit-contract)"
    for h in enforced:
        ea = h["enforced_at"]
        assert vei._resolves(vei.PKG, ea["file"], ea["pattern"]), (h["id"], ea)


def test_rotted_hook_evidence_is_caught():
    """enforced_at хука, чей паттерн не находится в файле, — протухшее доказательство зеркала."""
    spec = vei.load_spec()
    broken = dict(spec, pre_commit_hooks=[
        (dict(h, enforced_at={"file": ".github/workflows/package-quality.yml",
                              "pattern": "этого-паттерна-точно-нет- zzz"})
         if h["id"] == "commit-contract" else h)
        for h in spec["pre_commit_hooks"]])
    errors = vei.check(broken)
    assert any("commit-contract" in e and "протухло" in e for e in errors), errors


def test_local_only_hook_without_reason_is_caught():
    """local_only без причины — необъяснённое «в CI не зеркалён»."""
    spec = vei.load_spec()
    broken = dict(spec, pre_commit_hooks=[
        (dict(h, reason="") if h["id"] == "check-yaml" else h)
        for h in spec["pre_commit_hooks"]])
    errors = vei.check(broken)
    assert any("check-yaml" in e and "без причины" in e for e in errors), errors


def test_baseline_not_read_by_its_consumer_is_caught():
    """consumed_by, который baseline не упоминает, — заявленный потребитель его не читает."""
    spec = vei.load_spec()
    broken = dict(spec, ratchet_baselines=[
        {"name": "packages/module-size-baseline.yaml",
         "consumed_by": "ai_ops_kit/validation/validate_layering.py"}]  # layering его не читает
        + [b for b in spec["ratchet_baselines"] if "module-size" not in b["name"]])
    errors = vei.check(broken)
    assert any("module-size-baseline" in e and "не упоминает" in e for e in errors), errors
