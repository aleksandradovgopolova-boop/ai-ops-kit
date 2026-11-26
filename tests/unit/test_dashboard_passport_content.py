"""Паспорт пульта соединяет авторские разделы и результаты проверок текущей сборки."""
from pathlib import Path

import pytest

from ai_ops_kit.planning import passport_generator
from dashboard import build_data


ROOT = Path(__file__).resolve().parents[2]
OWNER = "Owner и команда"
MILESTONE = "Текущий milestone и прогресс"
HEALTH = "Здоровье (продукт / технологии / delivery)"
RELEASE = "Версия и последний релиз"


def by_name(sections):
    return {section["name"]: section for section in sections}


def test_real_owner_fields_match_the_authored_passport_and_survive_audit_failure(monkeypatch):
    def fail(_):
        raise OSError("audit unavailable")

    monkeypatch.setattr(passport_generator, "sections", fail)
    rows = by_name(build_data.passport(ROOT))
    assert rows[OWNER]["source"] == build_data.PASSPORT_PATH
    assert "product-team" in rows[OWNER]["value"]
    assert "основателю" in rows["Аудитория и проблема"]["value"]
    assert "AI Ops Kit" in rows["Название и описание"]["value"]
    assert all(row["state"] == "authored" and "<!--" not in row["value"] for row in rows.values())


@pytest.mark.parametrize("body", [None, "", "<!-- владелец -->", "_неизвестно — нужен ответ_"])
def test_missing_or_unfilled_owner_is_visible(tmp_path, monkeypatch, body):
    monkeypatch.setattr(passport_generator, "sections", lambda root: {})
    path = tmp_path / build_data.PASSPORT_PATH
    if body is not None:
        path.parent.mkdir(parents=True)
        path.write_text(f"## {OWNER}\n{body}\n", encoding="utf-8")
    sections = build_data.passport(tmp_path)
    owner = by_name(sections)[OWNER]
    assert owner["state"] == "unknown"
    assert owner["value"] == ("Файл паспорта недоступен." if body is None else "Раздел не заполнен в паспорте.")
    card = next(s for s in build_data.build_spine(tmp_path, False, sections) if s["key"] == "passport")
    assert card["path"] == build_data.PASSPORT_PATH
    assert card["state"] == ("missing" if body is None else "template")


def test_build_uses_published_release_and_ci_and_leaves_canonical_passport_untouched(tmp_path, monkeypatch):
    path = tmp_path / build_data.PASSPORT_PATH
    path.parent.mkdir(parents=True)
    old = f"## {OWNER}\nНаша команда\n## {RELEASE}\nУстаревший снимок\n"
    path.write_text(old, encoding="utf-8")
    (tmp_path / "VERSION").write_text("2.1.0\n", encoding="utf-8")
    monkeypatch.setattr(passport_generator, "sections", lambda root: {
        RELEASE: {"value": "Локальный тег v9", "state": "verified"},
        HEALTH: {"value": "Delivery: есть история релизов.", "state": "unknown"},
    })
    monkeypatch.setattr(build_data, "next_action", lambda root: {"source": None})
    monkeypatch.setattr(build_data, "open_issues", lambda root: [])
    monkeypatch.setattr(build_data, "delivery_evidence", lambda root: {
        "release": {"tag": "v2.0.0", "published_at": "2026-11-01T00:00:00Z"},
        "tech": {"state": "red", "head": "a" * 40, "detail": "Сбой проверки совместимости."},
    })
    data = build_data.build(tmp_path)
    rows = by_name(data["passport_sections"])
    assert rows[OWNER]["value"] == "Наша команда"
    assert "v2.0.0 (2026-11-01)" in rows[RELEASE]["value"] and "2.1.0" in rows[RELEASE]["value"]
    assert "v9" not in rows[RELEASE]["value"] and "Устаревший снимок" not in rows[RELEASE]["value"]
    assert rows[HEALTH]["state"] == "partial" and "Сбой проверки совместимости" in rows[HEALTH]["value"]
    assert data["metrics"]["health"]["tech"] == "red"
    assert data["metrics"]["health"]["delivery"] == "unknown"
    assert path.read_text(encoding="utf-8") == old


def test_tags_and_green_looking_text_do_not_substitute_for_unavailable_evidence(tmp_path):
    base = [{"name": RELEASE, "value": "Последний тег v9", "state": "verified"},
            {"name": HEALTH, "value": "Продукт: **Green**.", "state": "verified"}]
    rows = by_name(build_data.passport_snapshot(tmp_path, base, delivery={}, observations=None, field=None, plan=None))
    assert rows[HEALTH]["state"] == rows[RELEASE]["state"] == "unknown"
    assert "выпуске недоступны" in rows[RELEASE]["value"] and "v9" not in rows[RELEASE]["value"]
    assert "Green" not in rows[HEALTH]["value"]


def test_progress_counts_only_declared_outcomes_of_linked_goals(tmp_path):
    base = [{"name": MILESTONE, "value": "Описание машинной вехи", "state": "verified"}]
    plan = {"current_milestone": {"name": "Понятная цель", "linked_goals": ["a"]},
            "goals": [{"id": "a", "outcome": {"review": True, "field": False}},
                      {"id": "b", "outcome": {"another": True}}]}
    rows = by_name(build_data.passport_snapshot(tmp_path, base, delivery={}, observations=None, field=None, plan=plan))
    assert rows[MILESTONE]["state"] == "documented"
    assert "1 из 2" in rows[MILESTONE]["display_value"]
