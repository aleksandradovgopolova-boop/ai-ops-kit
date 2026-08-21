"""Bootstrap Product Operating Layer: `ai-ops init` создаёт `.ai-ops/` (PR-3).

Инвариант — все обязательные артефакты создаются ВАЛИДНО (структура полна, версия актуальна), а не
просто как пустые файлы (`is_file()` != заполнен). Состав берётся из реестра артефактов (PR-4), а не
из хардкода. Три теста на capability:

  * positive     — на чистом репо создаются все артефакты реестра, каждый VALID; Passport собран из
                   фактов и содержательно заполнен;
  * fail-closed  — существующие файлы владельца НЕ перезаписываются; нет реестра -> установка не
                   падает, а честно сообщает пропуск;
  * side-effect  — состав определяется РЕЕСТРОМ: every required document/config artifact получает
                   файл; директория шаблонов синхронизируется копией версий кита.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import passport_generator as PG
from ai_ops_kit.planning import product_templates as PT

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
REG = AR.load()


@pytest.fixture(scope="module")
def installer():
    """Модуль установщика (installer/ai_ops.py) как объект — тот же приём, что в test_unwired."""
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(tmp_path):
    (tmp_path / "README.md").write_text("# Демо\n\nсервис.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    return tmp_path


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_bootstrap_creates_all_registry_artifacts_valid(installer, tmp_path):
    r = _repo(tmp_path)
    installer._seed_product_layer(r)
    for art in AR.artifacts(REG):
        st = PT.state_of(r, art, REG)
        assert st["state"] == PT.VALID, f"{art['id']}: {st}"


def test_bootstrap_passport_is_generated_and_filled(installer, tmp_path):
    r = _repo(tmp_path)
    installer._seed_product_layer(r)
    passport = (r / ".ai-ops" / "PRODUCT_PASSPORT.md").read_text(encoding="utf-8")
    req = AR.artifact(REG, "product_passport")["structure"]["required_sections"]
    filled, empty = PG.is_filled(passport, req)
    assert filled, f"пустые разделы: {empty}"
    assert "1.0.0" in passport                         # факт из VERSION, а не заготовка


def test_templates_dir_synced_with_kit_versions(installer, tmp_path):
    r = _repo(tmp_path)
    installer._seed_product_layer(r)
    tdir = r / ".ai-ops" / "templates"
    assert (tdir / "PRODUCT_PASSPORT.md").is_file()
    # копия соответствует версии кита
    kit = (PKG / "templates" / "product-layer" / "PRODUCT_PASSPORT.md").read_text(encoding="utf-8")
    assert (tdir / "PRODUCT_PASSPORT.md").read_text(encoding="utf-8") == kit


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

def test_existing_owner_files_are_not_overwritten(installer, tmp_path):
    r = _repo(tmp_path)
    d = r / ".ai-ops"
    d.mkdir()
    owner = "<!-- template-version: 1 -->\n# Мой roadmap\n## Now\nсвоё\n## Next\n\n## Later\n"
    (d / "ROADMAP.md").write_text(owner, encoding="utf-8")
    rep = installer._seed_product_layer(r)
    assert (d / "ROADMAP.md").read_text(encoding="utf-8") == owner
    assert any(x["artifact"].endswith("ROADMAP.md") and x["action"] == "exists" for x in rep)


def test_missing_registry_does_not_crash_install(installer, tmp_path, monkeypatch):
    """Нет реестра -> установка не падает, а честно сообщает пропуск (fail-open по данным, fail-closed по факту)."""
    monkeypatch.setattr(installer, "PKG", tmp_path)    # PKG без registry/artifact-registry.yaml
    rep = installer._seed_product_layer(tmp_path)
    assert rep and "skipped-no-registry" in rep[0]["action"]


# ── side-effect ──────────────────────────────────────────────────────────────────────────────────

def test_composition_comes_from_registry_not_hardcode(installer, tmp_path):
    """Каждый document/config артефакт реестра получает файл — состав определяет РЕЕСТР."""
    r = _repo(tmp_path)
    installer._seed_product_layer(r)
    for art in AR.artifacts(REG):
        if art.get("kind") in ("document", "config"):
            assert (r / art["path"]).is_file(), f"{art['id']} не создан"
