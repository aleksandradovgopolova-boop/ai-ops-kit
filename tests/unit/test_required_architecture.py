"""SR-7: ARCHITECTURE.md — единый обязательный архитектурный артефакт.

Решение владельца 2026-09-07: канонический источник архитектуры — корневой ARCHITECTURE.md;
прежние context/system/{SystemOverview,RepositoryMap}.md — уходящие через окно вывода. Эти тесты
держат: один обязательный архитектурный артефакт, шаблон едет, содержимое уходящих мигрируется,
и сам кит догфудит (имеет заполненный ARCHITECTURE.md).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]


def _load_installer():
    spec = importlib.util.spec_from_file_location("installer_ai_ops_arch_under_test",
                                                  KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_ships():
    assert (KIT / "templates" / "system" / "ARCHITECTURE.md").is_file(), \
        "шаблон ARCHITECTURE.md обязан ехать (SR-7)"


def test_manifest_declares_architecture_required_with_template():
    m = yaml.safe_load((KIT / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))
    pom = m["session_orchestration"]["product_operating_model"]
    assert "ARCHITECTURE.md" in pom["required_repo_artifacts"]
    assert pom["templates"].get("architecture", "").endswith("system/ARCHITECTURE.md")


def test_contour_canonical_is_architecture_old_ones_deprecated():
    pom = yaml.safe_load((KIT / "registry" / "product-operating-model.yaml").read_text(encoding="utf-8"))
    sysc = next(c for c in pom["contours"] if c["id"] == "system_architecture")
    sot = {s["path"]: s.get("required") for s in sysc["source_of_truth"]}
    assert sot.get("ARCHITECTURE.md") is True, "ARCHITECTURE.md должен быть обязательным"
    assert sot.get("context/system/SystemOverview.md") is False, "SystemOverview — уходящий (required:false)"
    assert sot.get("context/system/RepositoryMap.md") is False, "RepositoryMap — уходящий (required:false)"


def test_migration_composes_legacy_into_architecture(tmp_path):
    mod = _load_installer()
    d = tmp_path / "context" / "system"
    d.mkdir(parents=True)
    (d / "SystemOverview.md").write_text("# System Overview\nграницы\n", encoding="utf-8")
    (d / "RepositoryMap.md").write_text("# Repository Map\nкаталоги\n", encoding="utf-8")
    out = mod._child_scaffolding()._migrate_legacy_architecture(tmp_path)
    assert out and out[0]["action"] == "migrated-from-legacy"
    text = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "границы" in text and "каталоги" in text


def test_migration_idempotent_when_architecture_exists(tmp_path):
    mod = _load_installer()
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nсвоё\n", encoding="utf-8")
    d = tmp_path / "context" / "system"
    d.mkdir(parents=True)
    (d / "SystemOverview.md").write_text("# System Overview\nграницы\n", encoding="utf-8")
    assert mod._child_scaffolding()._migrate_legacy_architecture(tmp_path) == []
    assert "своё" in (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_kit_dogfoods_filled_architecture():
    """Кит сам держит заполненный ARCHITECTURE.md (иначе planning_seeded провалится, SR-7)."""
    arch = KIT / "ARCHITECTURE.md"
    assert arch.is_file(), "у самого кита обязан быть корневой ARCHITECTURE.md (догфуд)"
    text = arch.read_text(encoding="utf-8")
    for marker in ("template: true", "Это заготовка"):
        assert marker not in text, f"ARCHITECTURE.md кита — заготовка (маркер {marker!r})"
