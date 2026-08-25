"""Гранулярные тесты storybook_query (мигрировано из test_storybook_query_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from storybook_query import (
    Path,
    catalog,
    component_stories,
    json,
    list_components,
    load_stories,
    related_stories,
    story_meta,
)


@pytest.fixture
def storybook_root():
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
        yield root


@pytest.mark.unit
class TestLoadStories:
    def test_story_index_parsed_docs_excluded(self, storybook_root):
        st = load_stories(storybook_root)
        assert len(st) == 3


@pytest.mark.unit
class TestListComponents:
    def test_list_components_sorted(self, storybook_root):
        st = load_stories(storybook_root)
        assert list_components(st) == ["Components/Button", "Components/MetricCard"]


@pytest.mark.unit
class TestComponentStories:
    def test_metriccard_has_two_stories(self, storybook_root):
        st = load_stories(storybook_root)
        assert len(component_stories(st, "Components/MetricCard")) == 2


@pytest.mark.unit
class TestRelatedStories:
    def test_related_by_changed_file(self, storybook_root):
        st = load_stories(storybook_root)
        assert set(related_stories(st, ["src/MetricCard.tsx"])) == {
            "components-metriccard--default", "components-metriccard--loading"
        }

    def test_related_unknown_file_empty(self, storybook_root):
        st = load_stories(storybook_root)
        assert related_stories(st, ["src/Unknown.tsx"]) == []


@pytest.mark.unit
class TestStoryMeta:
    def test_returns_import_path(self, storybook_root):
        st = load_stories(storybook_root)
        assert story_meta(st, "components-button--default")["importPath"] == "./src/Button.tsx"


@pytest.mark.unit
class TestCatalog:
    def test_catalog_read_only_and_story_count(self, storybook_root):
        c = catalog(storybook_root)
        assert c["read_only"] is True
        assert c["story_count"] == 3

    def test_no_storybook_empty_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            assert catalog(td)["story_count"] == 0
