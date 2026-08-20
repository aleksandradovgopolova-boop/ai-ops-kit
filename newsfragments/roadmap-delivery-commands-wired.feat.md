Команды `ai-ops roadmap` и `ai-ops delivery` подключены — Фаза 3 (лента 4) теперь достижима в дочке.
`ai-ops roadmap` строит Now/Next/Later из плана (цели + исходы) и называет отклонения от авторского
`ROADMAP.md`; `ai-ops delivery [--backlog F] [--milestone M]` собирает из backlog по контракту ленты 3
исполнимый план (порядок по зависимостям, прогноз-ОЦЕНКУ, риски) и ранние блокеры. Четыре модуля
(`roadmap_manager`, `roadmap_milestones`, `delivery_planning`, `delivery_planning_blockers`) убраны
из `installer.UNWIRED_MODULES` — они больше не «построено, но недостижимо», а едут в дочку и зовутся
командами. Исходы цели `roadmap-and-delivery` переведены в достигнутые ЖИВЫМ ПРОГОНОМ, не декларацией;
отсутствие источника backlog остаётся честным третьим состоянием. Интенты объявлены `experimental`
в `docs/api/public-surface.md`: работают, но форма ещё устаканивается вместе с контрактом ленты 3.
