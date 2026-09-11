UI-система дочки доступна агенту как MCP-инструмент `storybook-query`: объявлена в
`registry/tools.yaml` (protocol mcp, permission read-only) и в `registry/capability-index.yaml`
(tool/mcp). Доступ = существующий минимальный read-only адаптер `ai_ops_kit/ui/storybook_query.py`
через MCP-декларацию (компоненты, stories, related-stories, метаданные story); MCP-runtime
оборачивает детерминированный вход `--json` как tool. Полноценный MCP-сервер/SaaS сознательно
ОТЛОЖЕН (ревью владельца: минимальный адаптер, а не центр). Честно: реестровая декларация не
создаёт Python-импортёра, поэтому модуль остаётся в инвентаре built-not-wired до проводки живым
потребителем — исход `mcp_access_to_ui_system` закрыт на уровне «доступен как инструмент по
проверяемой декларации», без фабрикации сервера.
