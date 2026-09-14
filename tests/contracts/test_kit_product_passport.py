"""Кит держит собственный Product Passport — тот же артефакт, что требует от каждой дочки.

Кит объявляет себя образцом для дочерних репозиториев (`AGENTS.md`), а Product Passport —
обязательный артефакт продуктового слоя (`registry/artifact-registry.yaml -> product_passport`).
Раньше кит требовал паспорт от дочки, а у себя его не держал — тот же класс, что R-21 («требует план
от дочек, не имея своего»). Этот контракт стережёт, чтобы паспорт кита существовал, был структурно
валиден (не одни заголовки) и НЕ ОТСТАВАЛ от версии: бамп VERSION без перегенерации краснит тест.

Место паспорта у кита-родителя — слой продуктового контекста рядом с ProductStatus.md
(`.ai/project/context/product/PRODUCT_PASSPORT.md`); у дочки-родителя — `.ai-ops/PRODUCT_PASSPORT.md`.
Перегенерация: `python3 -m ai_ops_kit.planning.passport_generator generate . -o <путь>`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import passport_generator as PG

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
PASSPORT = PKG / ".ai" / "project" / "context" / "product" / "PRODUCT_PASSPORT.md"
REG = AR.load()
REQUIRED = AR.artifact(REG, "product_passport")["structure"]["required_sections"]


@pytest.mark.contract
class TestKitOwnPassport:
    def test_passport_exists(self):
        assert PASSPORT.is_file(), f"кит не держит собственный паспорт: {PASSPORT}"

    def test_template_version_marker_matches_registry(self):
        first = PASSPORT.read_text(encoding="utf-8").splitlines()[0]
        version = (AR.artifact(REG, "product_passport")["template"]).get("version", 1)
        assert first.strip() == f"<!-- template-version: {version} -->", (
            "маркер версии шаблона отсутствует или отстал — паспорт перегенерировать")

    def test_all_required_sections_filled(self):
        filled, empty = PG.is_filled(PASSPORT.read_text(encoding="utf-8"), REQUIRED)
        assert filled, f"пустые (одни заголовки) разделы паспорта: {empty}"

    def test_version_fact_is_fresh(self):
        # Freshness-ратчет: паспорт называет ФАКТ версии из VERSION. Бамп версии без перегенерации
        # паспорта краснит здесь — снимок не должен разойтись с реальностью незаметно.
        version = (PKG / "VERSION").read_text(encoding="utf-8").strip()
        assert version in PASSPORT.read_text(encoding="utf-8"), (
            f"паспорт отстал от VERSION={version} — перегенерировать машинные разделы")
