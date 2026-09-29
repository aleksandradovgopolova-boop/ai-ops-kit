# -*- coding: utf-8 -*-
"""Единый формат issue: заголовок `<slug>: <исход>` и четыре секции тела по порядку шаблона.

Формат держат три пути заведения issue (сверка роадмапа, сверка кандидатов, шаблоны для людей и
агентов). Тесты проверяют сам рендерер, что оба генератора отдают соответствующий ему вывод, и что
секции в коде не разошлись с шаблонами `.github/ISSUE_TEMPLATE/task.md` и `epic.md`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import candidate_issue_sync as cand   # noqa: E402
from ai_ops_kit.planning import issue_format as f   # noqa: E402
from ai_ops_kit.planning import roadmap_issue_sync as road   # noqa: E402

pytestmark = pytest.mark.unit

TEMPLATES = KIT / ".github" / "ISSUE_TEMPLATE"


def _positions(body: str) -> list[int]:
    return [body.index(f"**{h}**") for h in f.SECTION_HEADINGS]


# ── рендерер ──

def test_title_is_slug_colon_outcome():
    assert f.render_title("first-hour", "человек доходит до результата") == \
        "first-hour: человек доходит до результата"


def test_long_title_truncates_outcome_not_slug():
    t = f.render_title("some-slug", "слово " * 60, limit=50)
    assert t.startswith("some-slug: ")
    assert len(t) <= 50 and t.endswith("…")


def test_title_rejects_slug_with_spaces_and_empty_outcome():
    with pytest.raises(ValueError):
        f.render_title("two words", "исход")
    with pytest.raises(ValueError):
        f.render_title("slug", "   ")


def test_body_has_four_sections_in_order():
    body = f.render_body("что", "зачем", "проверяемо", "границы")
    pos = _positions(body)
    assert pos == sorted(pos)
    assert f.problems("slug: исход", body) == []


def test_body_marker_first_and_extra_after_bounds():
    body = f.render_body("что", "зачем", "проверяемо", "границы",
                         marker="<!-- sync: k -->", extra="### Подзадачи\n- [ ] #1")
    assert body.startswith("<!-- sync: k -->\n")
    assert body.index("### Подзадачи") > body.index("**Границы/Источник.**")


def test_empty_section_is_refused():
    with pytest.raises(ValueError, match="Проверяемо"):
        f.render_body("что", "зачем", "", "границы")


def test_problems_names_bracket_title_and_missing_sections():
    probs = f.problems("[roadmap:x] старый заголовок", "**Что.** только одна секция")
    assert len(probs) == 2


# ── генераторы issue отдают формат ──

def test_roadmap_epic_conforms():
    title = road.epic_title("checks-that-run")
    body = road.epic_body("checks-that-run", "now", 1, 2, ["b"], [12])
    assert title == "checks-that-run: Каждая объявленная проверка реально исполняется"
    assert f.problems(title, body) == []
    assert body.startswith("<!-- roadmap-sync: dir:checks-that-run -->")
    assert body.index("#12") > body.index("**Границы/Источник.**")   # подзадачи — после секций


def test_roadmap_epic_without_human_title_still_has_outcome():
    title = road.epic_title("some-new-goal", "some-new-goal")
    assert title.startswith("some-new-goal: ")
    assert "some-new-goal" not in title.split(": ", 1)[1]


def test_roadmap_work_conforms():
    work = {"id": "w-types", "title": "Проверка типов исполняется", "status": "todo",
            "rationale": "без неё зелёное не значит проверенное"}
    title, body = road.work_title("checks-that-run", work), road.work_body("checks-that-run", work)
    assert title == "w-types: Проверка типов исполняется"
    assert f.problems(title, body) == []
    assert "без неё зелёное не значит проверенное" in body
    assert road.parse_key(road.Issue(1, title, body, "open")) == "work:checks-that-run:w-types"


def test_candidate_conforms():
    c = {"id": "cand-obs-1", "title": "Разобрать наблюдение: флак в CI",
         "source": "child-finding", "rationale": "тест мигает"}
    title, body = cand.candidate_title(c), cand.candidate_body(c)
    assert title == "obs-1: Разобрать наблюдение: флак в CI"
    assert f.problems(title, body) == []
    assert body.index("candidates accept cand-obs-1") > body.index("**Границы/Источник.**")


def test_candidate_direction_slug_is_its_goal():
    c = {"id": "cand-dir-checks-that-run", "title": "Декомпозировать направление",
         "source": "roadmap-direction", "source_goal": "checks-that-run"}
    assert cand.candidate_title(c).startswith("checks-that-run: ")


# ── дрейф: шаблоны для людей и константа в коде — одна правда ──

@pytest.mark.parametrize("name", ["task.md", "epic.md"])
def test_template_sections_match_constant(name):
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    assert f.section_headings(text) == list(f.SECTION_HEADINGS)
    assert "<slug>: " in text


def test_epic_template_has_subtasks_block_after_sections():
    text = (TEMPLATES / "epic.md").read_text(encoding="utf-8")
    assert text.index("Подзадачи") > text.index("**Границы/Источник.**")


def test_blank_issues_are_disabled():
    cfg = yaml.safe_load((TEMPLATES / "config.yml").read_text(encoding="utf-8"))
    assert cfg["blank_issues_enabled"] is False
