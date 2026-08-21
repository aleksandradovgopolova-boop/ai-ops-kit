Backlog Intelligence теперь под рукой прямо в дочке: `ai-ops backlog classify | dedup | prioritize |
graph` разбирают GitHub Issues репозитория, в котором запущены. Раньше это были только модули
(`python3 -m ai_ops_kit.planning.backlog_*`) — теперь это команда движка, как `next` или `health`.
Без доступа к GitHub команда честно отвечает «не проверено» с причиной и кодом 2 (блокировано), а не
пустым backlog с кодом 0.
