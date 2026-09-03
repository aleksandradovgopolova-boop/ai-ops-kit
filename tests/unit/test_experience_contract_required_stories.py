"""Обязательные stories выводятся КОДОМ из контракта, а не из перечня владельца.

Регрессия #415: сторона доказательства (`storybook_adapter`) требует четыре состояния
(default/loading/empty/error), а сторона создания раньше выводила состояния ИЗ КОНТРАКТА —
только те, что владелец вспомнил. Контракт без `error` порождал набор, который гейт не
принимал никогда. Здесь фиксируем: набор берётся из одного источника `REQUIRED_STATES`.
"""
from __future__ import annotations

from ai_ops_kit.ui import experience_contract as ec
from ai_ops_kit.ui.storybook_adapter import REQUIRED_STATES


# Контракт, в котором владелец НЕ описал error/loading/empty — только default.
CONTRACT = {
    "id": "active-work",
    "title": "Active Work",
    "user_goal": "видеть активные работы",
    "context": "dashboard",
    "roles": [],
    "flow": [],
    "screens": [{"id": "active-work", "name": "ActiveWork", "components": ["List"]}],
    "states": [{"name": "default", "condition": "loaded", "visual": "list"}],
    "microcopy": {},
    "responsive": [],
    "accessibility": [],
    "components": ["List"],
    "tokens": {},
    "analytics": [],
    "open_questions": [],
    "tradeoffs": [],
}


def test_required_specs_cover_all_required_states_even_when_undeclared():
    specs = ec.required_story_specs(CONTRACT)
    got_states = {s["state"] for s in specs}
    # Все обязательные состояния присутствуют, хотя контракт объявил только default.
    assert set(REQUIRED_STATES).issubset(got_states)
    assert {"active-work-error", "active-work-loading", "active-work-empty"} <= {
        s["id"] for s in specs
    }


def test_generate_stories_includes_undeclared_required_states():
    stories = ec.generate_stories(CONTRACT)
    ids = {s["id"] for s in stories}
    for state in REQUIRED_STATES:
        assert f"active-work-{state}" in ids


def test_undeclared_required_states_surfaced():
    undeclared = ec.undeclared_required_states(CONTRACT)
    assert "error" in undeclared and "loading" in undeclared and "empty" in undeclared
    assert "default" not in undeclared


def test_coverage_flags_missing_stories_against_built_index():
    # Индекс, где собрана только default-story одного экрана.
    index = [{"id": "activework--default", "title": "ActiveWork",
              "name": "Default", "importPath": "./ActiveWork.stories.tsx"}]
    cov = ec.required_stories_coverage(CONTRACT, index)
    assert not cov["complete"]
    assert cov["missing"]  # error/loading/empty отсутствуют в собранном Storybook
    assert set(REQUIRED_STATES).issubset(
        {mid.rsplit("-", 1)[-1] for mid in cov["required"]}
    )


def test_coverage_complete_when_all_required_states_present():
    index = [
        {"id": f"activework--{st}", "title": "ActiveWork", "name": st,
         "importPath": "./ActiveWork.stories.tsx"}
        for st in REQUIRED_STATES
    ]
    cov = ec.required_stories_coverage(CONTRACT, index)
    assert cov["complete"], cov["missing"]
    assert ec.missing_required_stories(CONTRACT, index) == []
