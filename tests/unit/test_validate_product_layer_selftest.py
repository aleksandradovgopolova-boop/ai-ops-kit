"""Валидация Product Operating Layer: отчёт Missing/Invalid/Outdated/Valid (PR-5).

Инвариант — ЧЕТЫРЕ состояния, и «пустая секция != отсутствующая, но и != заполненная». Способ
подделать — свести к «есть/нет» или принять пустой раздел за Valid. Три теста на capability:

  * positive     — на свежеустановленном слое все обязательные артефакты Valid, отчёт сходится;
  * fail-closed  — нет `.ai-ops/` -> все Missing и check() возвращает ошибки; пустой раздел паспорта
                   -> Invalid, а не Valid;
  * side-effect  — валидатор ЧИТАЕТ содержимое: паспорт с заголовками-без-тела становится Invalid с
                   названием пустых разделов, а не проходит как заполненный.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.validation import validate_product_layer as VPL

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
REG = AR.load()


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_vpl", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bootstrapped(installer, tmp_path):
    (tmp_path / "README.md").write_text("# Демо\n\nсервис.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    installer._seed_product_layer(tmp_path)
    return tmp_path


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_bootstrapped_layer_is_all_valid(installer, tmp_path):
    r = _bootstrapped(installer, tmp_path)
    assert VPL.check(r) == []
    rep = VPL.report(r)
    assert rep["ok"] is True
    assert rep["counts"]["valid"] == len(AR.artifacts(REG))
    assert rep["counts"]["missing"] == rep["counts"]["invalid"] == 0


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

def test_empty_repo_layer_is_all_missing(tmp_path):
    rep = VPL.report(tmp_path)
    assert rep["ok"] is False
    assert rep["counts"]["missing"] == len(AR.artifacts(REG))
    errs = VPL.check(tmp_path)
    assert errs and all("missing" in e for e in errs)


def test_present_but_empty_passport_is_invalid(installer, tmp_path):
    """`.ai-ops/PRODUCT_PASSPORT.md` со всеми заголовками, но пустыми телами -> Invalid, не Valid."""
    r = _bootstrapped(installer, tmp_path)
    art = AR.artifact(REG, "product_passport")
    secs = art["structure"]["required_sections"]
    hollow = "<!-- template-version: 1 -->\n# П\n" + "".join(f"## {s}\n<!-- пусто -->\n" for s in secs)
    (r / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(hollow, encoding="utf-8")
    rep = VPL.report(r)
    assert rep["artifacts"]["product_passport"]["state"] == "invalid"
    assert rep["ok"] is False


# ── side-effect ──────────────────────────────────────────────────────────────────────────────────

def test_validator_names_the_empty_sections(installer, tmp_path):
    """Доказательство чтения СОДЕРЖИМОГО: причина Invalid называет именно пустые разделы."""
    r = _bootstrapped(installer, tmp_path)
    art = AR.artifact(REG, "product_passport")
    secs = art["structure"]["required_sections"]
    hollow = "<!-- template-version: 1 -->\n# П\n" + "".join(f"## {s}\n" for s in secs)
    (r / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(hollow, encoding="utf-8")
    reason = VPL.report(r)["artifacts"]["product_passport"]["reason"]
    assert "пуст" in reason and secs[0] in reason
