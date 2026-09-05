"""Исход `mcp_access_to_ui_system` (цель uiux-standard-as-product, issue #420).

UI-система ДОСТУПНА агенту как MCP-инструмент через СУЩЕСТВУЮЩИЙ read-only адаптер
`ai_ops_kit/ui/storybook_query.py` — не отдельный MCP-сервер/SaaS. Ревью владельца явно отложил
полноценный MCP-сервер («не сейчас»), поэтому исход закрывается на уровне «UI-система доступна как
MCP-инструмент через минимальный read-only адаптер по декларации реестра», а не сервером.

Проверяемо:
  (а) `storybook-query` объявлен MCP-доступным инструментом в registry/tools.yaml и tool/mcp — в
      registry/capability-index.yaml; валидатор реестра (validate_ai_first_providers) зелёный;
  (б) объявленный инструмент РЕЗОЛВИТСЯ в реальные read-only запросы (компоненты/stories) на
      синтетическом Storybook — через модуль, указанный в `source` декларации;
  (в) fail-closed: инструмент read-only (не даёт записи) — permission_level и поведение адаптера;
  (г) честная граница: реестровая декларация НЕ фабрикует проводку — модуль честно остаётся в
      KNOWN_DORMANT (объявлен, но не проведён живым импортёром), а полный MCP-сервер отложен.

Тест ПОВЕДЕНЧЕСКИЙ: импортирует продуктовый код кита (storybook_query + валидатор) И зовёт его.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.ui import storybook_query as sq
from ai_ops_kit.validation import validate_ai_first_providers as vfp
from tests.contracts.test_dormant_inventory import KNOWN_DORMANT

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_YAML = REPO_ROOT / "registry" / "tools.yaml"
CAP_INDEX = REPO_ROOT / "registry" / "capability-index.yaml"
TOOL_ID = "storybook-query"


def _tools():
    return yaml.safe_load(TOOLS_YAML.read_text(encoding="utf-8"))


def _tool_entry():
    return next((t for t in _tools().get("tools", []) if t.get("id") == TOOL_ID), None)


@pytest.fixture
def storybook_root():
    """Синтетический Storybook-каталог дочки (тот же формат story-index, что парсит адаптер)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "storybook-static").mkdir()
        (root / "storybook-static" / "index.json").write_text(json.dumps({"v": 5, "entries": {
            "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
            "components-button--default": {"type": "story", "id": "components-button--default",
                "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"}}}),
            encoding="utf-8")
        yield root


@pytest.mark.unit
class TestDeclaredInRegistry:
    def test_tool_declared_as_mcp_read_only(self):
        """(а) storybook-query объявлен MCP-инструментом, read-only, минимальный адаптер (не сервер)."""
        e = _tool_entry()
        assert e is not None, "storybook-query не объявлен в registry/tools.yaml"
        assert e.get("protocol") == "mcp", "инструмент обязан быть протокола mcp"
        assert e.get("permission_level") == "read-only", "MCP-доступ к UI обязан быть read-only"
        # Честная граница зафиксирована в самой декларации: минимальный адаптер, сервер отложен.
        assert e.get("minimal_adapter") is True
        assert e.get("full_mcp_server") == "deferred"
        assert e.get("source", "").endswith(("storybook_query.py", "--json")) or \
            "storybook_query.py" in e.get("source", "")

    def test_capability_index_links_tool_to_mcp(self):
        """(а) capability-index связывает tool storybook-query с возможностью mcp."""
        cap = yaml.safe_load(CAP_INDEX.read_text(encoding="utf-8"))
        entry = next((c for c in cap.get("entries", [])
                      if c.get("entity_kind") == "tool" and c.get("entity_id") == TOOL_ID
                      and c.get("capability") == "mcp"), None)
        assert entry is not None, "нет tool/mcp записи storybook-query в capability-index.yaml"
        assert entry.get("value") is True
        assert entry.get("status") in set(cap.get("status_vocabulary", []))

    def test_registry_validator_is_green(self, monkeypatch):
        """(а) валидатор реестров (читает tools.yaml + capability-index) зелёный на этой декларации."""
        monkeypatch.chdir(REPO_ROOT)
        vfp.errors.clear()
        rc = vfp.main()
        assert rc == 0, f"валидатор реестра не зелёный: {vfp.errors}"


@pytest.mark.unit
class TestDeclaredToolResolvesToReadOnlyQueries:
    def test_declared_source_module_resolves(self):
        """(б) `source` декларации указывает на реальный модуль адаптера, который мы и зовём."""
        src = _tool_entry().get("source", "")
        m = re.search(r"[\w/]+storybook_query\.py", src)
        assert m, f"source не указывает на storybook_query.py: {src!r}"
        assert (REPO_ROOT / m.group(0)).is_file(), "модуль из source-декларации не существует"

    def test_tool_resolves_to_real_component_and_story_queries(self, storybook_root):
        """(б) объявленный инструмент резолвится в РЕАЛЬНЫЕ read-only запросы на синтетике."""
        stories = sq.load_stories(storybook_root)
        assert sq.list_components(stories) == ["Components/Button", "Components/MetricCard"]
        assert sq.list_stories(stories) == [
            "components-button--default", "components-metriccard--default"]
        assert sq.component_stories(stories, "Components/Button") == ["components-button--default"]
        assert sq.related_stories(stories, ["src/Button.tsx"]) == ["components-button--default"]
        assert sq.story_meta(stories, "components-button--default")["importPath"] == "./src/Button.tsx"


@pytest.mark.unit
class TestFailClosedReadOnly:
    def test_catalog_declares_read_only(self, storybook_root):
        """(в) выдача инструмента самоописывается read-only."""
        assert sq.catalog(storybook_root)["read_only"] is True

    def test_tool_offers_no_write_path(self):
        """(в) fail-closed: модуль-адаптер не экспонирует ни одной мутирующей операции."""
        write_verbs = ("write", "save", "delete", "update", "create", "mkdir", "set_", "put")
        public = [n for n in vars(sq) if not n.startswith("_") and callable(getattr(sq, n))
                  and getattr(getattr(sq, n), "__module__", "") == sq.__name__]
        offenders = [n for n in public if any(v in n.lower() for v in write_verbs)]
        assert not offenders, f"адаптер обязан быть read-only, найдены пишущие имена: {offenders}"

    def test_read_only_query_does_not_mutate_storybook_dir(self, storybook_root):
        """(в) запрос через инструмент не меняет содержимое каталога дочки (нет побочной записи)."""
        before = sorted(p.name for p in (storybook_root / "storybook-static").iterdir())
        sq.catalog(storybook_root)
        sq.related_stories(sq.load_stories(storybook_root), ["src/Button.tsx"])
        after = sorted(p.name for p in (storybook_root / "storybook-static").iterdir())
        assert before == after, "read-only инструмент не должен менять каталог Storybook"


@pytest.mark.unit
class TestHonestBoundary:
    def test_declaration_does_not_fabricate_wiring(self):
        """(г) честно: декларация в реестре НЕ = проводка в контур; модуль остаётся в KNOWN_DORMANT."""
        assert "ai_ops_kit.ui.storybook_query" in KNOWN_DORMANT, (
            "реестровая декларация MCP-доступа не создаёт Python-импортёра — модуль честно остаётся "
            "дормантным до проводки живым потребителем; убирать его из KNOWN_DORMANT нельзя, пока "
            "нет не-тестового импортёра")
        reason = KNOWN_DORMANT["ai_ops_kit.ui.storybook_query"].lower()
        assert "mcp" in reason and "деклар" in reason, "причина обязана называть MCP-декларацию честно"

    def test_full_mcp_server_is_deferred_not_claimed(self):
        """(г) полноценный MCP-сервер сознательно отложен — декларация его НЕ заявляет построенным."""
        e = _tool_entry()
        assert e.get("full_mcp_server") == "deferred"
        # status инструмента — declared (объявлен), а не documented/verified: живого сервера нет.
        assert e.get("status") == "declared"
