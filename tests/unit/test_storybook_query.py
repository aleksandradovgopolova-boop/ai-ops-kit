"""Гранулярные тесты storybook_query (мигрировано из test_storybook_query_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.ui.storybook_query import (
    Path,
    catalog,
    component_stories,
    has_index,
    json,
    list_components,
    load_stories,
    navigation_context,
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


@pytest.fixture
def grouped_storybook_root():
    """Реальный паттерн ии-среды: компоненты в ds/*.tsx, а их stories СГРУППИРОВАНЫ в один
    ds/foundations.stories.tsx (importPath НЕ совпадает с файлом компонента)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "storybook-static").mkdir()
        fp = "./src/shared/ui/ds/foundations.stories.tsx"
        (root / "storybook-static" / "index.json").write_text(json.dumps({"v": 5, "entries": {
            "компоненты-button--variants": {"type": "story", "id": "компоненты-button--variants",
                "title": "Компоненты/Button", "name": "Variants", "importPath": fp},
            "компоненты-card--static": {"type": "story", "id": "компоненты-card--static",
                "title": "Компоненты/Card", "name": "Static", "importPath": fp},
        }}), encoding="utf-8")
        yield root


@pytest.mark.unit
class TestRelatedStoriesSmart:
    def test_grouped_story_matched_by_component_name(self, grouped_storybook_root):
        """Живой шов #613: правка ds/Button.tsx находит story «Компоненты/Button», хотя она
        описана в отдельном foundations.stories.tsx (строгий суффиксный матч тут дал бы пусто)."""
        st = load_stories(grouped_storybook_root)
        assert related_stories(st, ["src/shared/ui/ds/Button.tsx"]) == ["компоненты-button--variants"]

    def test_grouped_unknown_component_empty(self, grouped_storybook_root):
        st = load_stories(grouped_storybook_root)
        assert related_stories(st, ["src/shared/ui/ds/Zzz.tsx"]) == []

    def test_same_dir_story_stem_matched(self):
        """Классический паттерн: Card.tsx <-> Card.stories.tsx в соседних файлах."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "storybook-static").mkdir()
            (root / "storybook-static" / "index.json").write_text(json.dumps({"v": 5, "entries": {
                "ui-card--default": {"type": "story", "id": "ui-card--default", "title": "UI/Card",
                    "name": "Default", "importPath": "./src/ui/Card.stories.tsx"}}}), encoding="utf-8")
            st = load_stories(root)
            assert related_stories(st, ["src/ui/Card.tsx"]) == ["ui-card--default"]


@pytest.mark.unit
class TestNavigationContext:
    def test_none_when_no_storybook(self):
        with tempfile.TemporaryDirectory() as td:
            assert navigation_context(td) is None
            assert has_index(td) is False

    def test_context_lists_components_and_related(self, grouped_storybook_root):
        assert has_index(grouped_storybook_root) is True
        txt = navigation_context(grouped_storybook_root, changed_files=["src/shared/ui/ds/Button.tsx"])
        assert txt is not None
        assert "Компоненты/Button" in txt        # каталог компонентов дизайн-системы
        assert "компоненты-button--variants" in txt   # связанная story затронутого файла
        assert "переиспольз" in txt.lower()      # призыв переиспользовать дизайн-систему
