Статус цели `uiux-standard-as-product` сведён к правде: волна 3 (углубление ролей-ревьюеров и
UI-health содержанием Конституции) была фактически на main (#530/#419) и вшита
(`constitution_coverage` → `ui_readiness` → pipeline/deploy_readiness), но plan/ROADMAP держали её
`false`/«не взято». Исход `reviewers_and_ui_health_deepened_from_constitution` → true, работа уехала
в историю. Волна 4 (`mcp_access_to_ui_system`) честно остаётся `false`: на main лишь минимальный
MCP-адаптер (`storybook-query`, #529), полный сервер отложен ревью владельца.
