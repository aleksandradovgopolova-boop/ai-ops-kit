"""Генерация Product Passport из фактического состояния репозитория (PR-6).

Инвариант — паспорт из одних заголовков НЕ «Valid» (F-018/F-027), и кит НЕ выдумывает то, чего в
коде нет. Способ подделать — заполнить недоказуемое (аудиторию, владельца) правдоподобным текстом.
Три теста на capability:

  * positive     — сгенерированный паспорт структурно валиден (product_templates.state_of=VALID),
                   версия актуальна, и он СОДЕРЖАТЕЛЬНО заполнен (is_filled);
  * fail-closed  — паспорт из одних заголовков is_filled=False; пустой репозиторий даёт честные
                   «неизвестно», а не выдумку;
  * side-effect  — недоказуемые из кода разделы (Аудитория, Owner) выходят UNKNOWN, а версия и стек
                   берутся из РЕАЛЬНЫХ файлов (VERSION, манифест), а не сочиняются.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import passport_generator as PG
from ai_ops_kit.planning import product_templates as PT

REG = AR.load()
REQUIRED = AR.artifact(REG, "product_passport")["structure"]["required_sections"]


def _repo(tmp_path):
    """Небольшой, но реальный репозиторий: README, VERSION, тест, CI, манифест, git-тег."""
    (tmp_path / "README.md").write_text("# Акме\n\nСервис учёта заявок для складов.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("2.3.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    gh = tmp_path / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yml").write_text("name: ci\non: [push]\n", encoding="utf-8")
    return tmp_path


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_generated_passport_is_structurally_valid(tmp_path):
    r = _repo(tmp_path)
    text = PG.generate(r, reg=REG)
    (r / ".ai-ops").mkdir()
    (r / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(text, encoding="utf-8")
    art = AR.artifact(REG, "product_passport")
    assert PT.state_of(r, art, REG)["state"] == PT.VALID


def test_generated_passport_is_content_filled_not_just_headers(tmp_path):
    r = _repo(tmp_path)
    text = PG.generate(r, reg=REG)
    filled, empty = PG.is_filled(text, REQUIRED)
    assert filled, f"пустые разделы: {empty}"


def test_facts_from_real_files(tmp_path):
    r = _repo(tmp_path)
    secs = PG.sections(r)
    # версия — из VERSION, а не выдумана
    assert "2.3.0" in secs["Версия и последний релиз"]["value"]
    assert secs["Версия и последний релиз"]["state"] == PG.VERIFIED
    # tech-здоровье Green: есть CI и тесты
    assert "Green" in secs["Здоровье (продукт / технологии / delivery)"]["value"]


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

def test_headers_only_passport_is_not_filled():
    """Паспорт из одних заголовков (as-is шаблон) НЕ заполнен — это Invalid, не Valid."""
    stub = "<!-- template-version: 1 -->\n# Product Passport\n" + \
           "".join(f"## {s}\n" for s in REQUIRED)
    filled, empty = PG.is_filled(stub, REQUIRED)
    assert not filled
    assert set(empty) == set(REQUIRED)


def test_empty_repo_yields_honest_unknowns_not_fabrication(tmp_path):
    """Пустой репозиторий: разделы, которые нечем заполнить, — честное «неизвестно», а не выдумка."""
    secs = PG.sections(tmp_path)
    assert secs["Название и описание"]["state"] == PG.UNKNOWN
    assert secs["Версия и последний релиз"]["state"] == PG.UNKNOWN
    assert "неизвестно" in secs["Версия и последний релиз"]["value"].lower()


# ── side-effect ──────────────────────────────────────────────────────────────────────────────────

def test_non_derivable_sections_are_unknown_not_invented(tmp_path):
    """Аудитория/Problem/JTBD и владелец из кода НЕ выводятся -> UNKNOWN, а не правдоподобный текст.

    Это доказательство, что генератор не подменяет незнание утверждением: даже на насыщенном репо
    эти разделы честно пусты, потому что их источник — владелец, а не код."""
    r = _repo(tmp_path)
    secs = PG.sections(r)
    assert secs["Аудитория и проблема"]["state"] == PG.UNKNOWN
    assert secs["Owner и команда"]["state"] == PG.UNKNOWN
    # но они всё равно СОДЕРЖАТ строку (заполнены как «неизвестно»), а не пусты
    assert secs["Аудитория и проблема"]["value"].strip()


def test_tech_health_unknown_when_tree_unreadable():
    """Дерево нечитаемо -> tech-здоровье unknown, НЕ Green: неизвестность не красится нулём."""
    h = PG._tech_health({"tree_readable": False})
    assert h["band"] == "unknown"
