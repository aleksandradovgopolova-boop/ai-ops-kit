"""Гранулярные тесты passport_generator (мигрировано из test_passport_generator_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import passport_generator as PG
from ai_ops_kit.planning import product_templates as PT

REG = AR.load()
REQUIRED = AR.artifact(REG, "product_passport")["structure"]["required_sections"]


def _repo(tmp_path):
    """Небольшой, но реальный репозиторий: README, VERSION, тест, CI, манифест."""
    (tmp_path / "README.md").write_text("# Акме\n\nСервис учёта заявок для складов.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("2.3.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    gh = tmp_path / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yml").write_text("name: ci\non: [push]\n", encoding="utf-8")
    return tmp_path


# ── positive ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGeneratedPassport:
    def test_structurally_valid(self, tmp_path):
        r = _repo(tmp_path)
        text = PG.generate(r, reg=REG)
        (r / ".ai-ops").mkdir()
        (r / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(text, encoding="utf-8")
        art = AR.artifact(REG, "product_passport")
        assert PT.state_of(r, art, REG)["state"] == PT.VALID

    def test_content_filled_not_just_headers(self, tmp_path):
        r = _repo(tmp_path)
        text = PG.generate(r, reg=REG)
        filled, empty = PG.is_filled(text, REQUIRED)
        assert filled, f"пустые разделы: {empty}"

    def test_facts_from_real_files(self, tmp_path):
        r = _repo(tmp_path)
        secs = PG.sections(r)
        assert "2.3.0" in secs["Версия и последний релиз"]["value"]
        assert secs["Версия и последний релиз"]["state"] == PG.VERIFIED
        assert "Green" in secs["Здоровье (продукт / технологии / delivery)"]["value"]


# ── fail-closed ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFailClosed:
    def test_headers_only_not_filled(self):
        stub = "<!-- template-version: 1 -->\n# Product Passport\n" + \
               "".join(f"## {s}\n" for s in REQUIRED)
        filled, empty = PG.is_filled(stub, REQUIRED)
        assert not filled
        assert set(empty) == set(REQUIRED)

    def test_empty_repo_honest_unknowns(self, tmp_path):
        secs = PG.sections(tmp_path)
        assert secs["Название и описание"]["state"] == PG.UNKNOWN
        assert secs["Версия и последний релиз"]["state"] == PG.UNKNOWN
        assert "неизвестно" in secs["Версия и последний релиз"]["value"].lower()


# ── side-effect ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSideEffects:
    def test_non_derivable_sections_unknown(self, tmp_path):
        r = _repo(tmp_path)
        secs = PG.sections(r)
        assert secs["Аудитория и проблема"]["state"] == PG.UNKNOWN
        assert secs["Owner и команда"]["state"] == PG.UNKNOWN
        assert secs["Аудитория и проблема"]["value"].strip()

    def test_tech_health_unknown_when_unreadable(self):
        h = PG._tech_health({"tree_readable": False})
        assert h["band"] == "unknown"
