"""Селфтест storybook_query, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from storybook_query import (  # noqa: F401 — имена, которые использует тело
    Path,
    catalog,
    component_stories,
    json,
    list_components,
    load_stories,
    related_stories,
    story_meta,
)


@pytest.mark.slow
def test_storybook_query_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "storybook-static").mkdir()
        (root / "storybook-static" / "index.json").write_text(json.dumps({"v": 5, "entries": {
            "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
            "components-metriccard--loading": {"type": "story", "id": "components-metriccard--loading",
                "title": "Components/MetricCard", "name": "Loading", "importPath": "./src/MetricCard.tsx"},
            "components-button--default": {"type": "story", "id": "components-button--default",
                "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"},
            "docs-intro": {"type": "docs", "id": "docs-intro", "title": "Intro"}}}), encoding="utf-8")
        st = load_stories(root)
        expect("story-index распарсен, docs-entry не история (3 story)", len(st) == 3)
        expect("list_components -> MetricCard, Button",
               list_components(st) == ["Components/Button", "Components/MetricCard"])
        expect("component_stories(MetricCard) -> 2 story",
               len(component_stories(st, "Components/MetricCard")) == 2)
        expect("related_stories по изменённому MetricCard.tsx -> его stories, без Button",
               set(related_stories(st, ["src/MetricCard.tsx"]))
               == {"components-metriccard--default", "components-metriccard--loading"})
        expect("related_stories по чужому файлу -> пусто",
               related_stories(st, ["src/Unknown.tsx"]) == [])
        expect("story_meta возвращает importPath",
               story_meta(st, "components-button--default")["importPath"] == "./src/Button.tsx")
        c = catalog(root)
        expect("catalog read_only=True + story_count=3", c["read_only"] is True and c["story_count"] == 3)

    # нет Storybook -> пустой каталог, без падения
    with tempfile.TemporaryDirectory() as td2:
        expect("нет Storybook -> пустой каталог (без ошибки)", catalog(td2)["story_count"] == 0)

    assert ok, "перенесённый селфтест storybook_query: см. строки FAIL в выводе"
