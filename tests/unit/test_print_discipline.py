# -*- coding: utf-8 -*-
"""Ратчет дисциплины вывода имеет ЗУБЫ (validate_print_discipline, F-08).

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидатор на РЕПОЗИТОРИИ зелёный; аллоу-лист берётся из слоя entrypoints
                   layering.yaml, а не из хардкода;
  * fail-closed  — новый print сверх потолка, печать в библиотечном пакете без записи, мёртвая
                   запись и потолок на entrypoint — каждый краснеет;
  * side-effect  — счётчик считает РЕАЛЬНЫЕ вызовы print по AST (не подстроку).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "ai_ops_kit" / "validation"))

import validate_print_discipline as vpd  # noqa: E402

pytestmark = [pytest.mark.unit]


# ─── positive ───────────────────────────────────────────────────────────────────────────────────

def test_real_repository_is_green(capsys):
    rc = vpd.main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PRINT-DISCIPLINE-OK" in out, out


def test_allowlist_comes_from_layering_entrypoints():
    """Аллоу-лист — слой entrypoints layering.yaml (один источник), а не список в валидаторе."""
    allowed = vpd.entrypoint_packages()
    assert {"cli", "devtools", "validation"} <= allowed, allowed
    # библиотечный пакет НЕ в аллоу-листе
    assert "engine" not in allowed and "shared" not in allowed, allowed


def test_ast_counts_real_print_calls(tmp_path):
    """side-effect: считаются вызовы print, а не подстрока 'print(' в комментарии/строке."""
    f = tmp_path / "m.py"
    f.write_text("print('a')\n# print('not a call')\nx = 'print( also not'\nprint('b')\n",
                 encoding="utf-8")
    assert vpd._count_prints(f) == 2


# ─── fail-closed ──────────────────────────────────────────────────────────────────────────────────

ALLOWED = {"cli", "devtools", "validation"}


def test_growth_over_ceiling_is_caught():
    errors = vpd.check({"engine": 140}, {"engine": 139}, ALLOWED)
    assert any("engine" in e and "при потолке 139" in e for e in errors), errors


def test_library_print_without_ceiling_is_caught():
    """Библиотечный пакет напечатал, а записи в baseline нет — новый источник печати молча."""
    errors = vpd.check({"lifecycle": 5}, {}, ALLOWED)
    assert any("секции ceilings нет" in e for e in errors), errors
    errors2 = vpd.check({"lifecycle": 5, "engine": 139}, {"engine": 139}, ALLOWED)
    assert any("lifecycle" in e and "нет в ceilings" in e for e in errors2), errors2


def test_entrypoint_is_not_constrained():
    """cli печатает сколько угодно — он точка входа, потолка у него нет и быть не должно."""
    assert vpd.check({"cli": 9999}, {"engine": 139}, ALLOWED) == [] or \
        all("cli" not in e for e in vpd.check({"cli": 9999, "engine": 139}, {"engine": 139}, ALLOWED))


def test_ceiling_on_entrypoint_is_caught():
    errors = vpd.check({"cli": 5, "engine": 139}, {"cli": 5, "engine": 139}, ALLOWED)
    assert any("cli" in e and "entrypoint" in e for e in errors), errors


def test_stale_ceiling_for_missing_package_is_caught():
    errors = vpd.check({"engine": 139}, {"engine": 139, "ghost": 3}, ALLOWED)
    assert any("ghost" in e and "которого нет" in e for e in errors), errors


def test_shrink_asks_to_rebaseline():
    """Перевод print -> данные опускает число; ратчет просит опустить потолок (не падение продукта)."""
    errors = vpd.check({"engine": 100}, {"engine": 139}, ALLOWED)
    assert any("engine" in e and "потолок снизился" in e for e in errors), errors
