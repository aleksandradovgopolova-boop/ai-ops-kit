Product Contract, срез 6 — риски в контракте. `ai-ops contract` теперь показывает грань `risks`:
реестр рисков продукта (`intelligence.risk_register`) — риски, выведенные из здоровья и дрейфа
артефактов, с разбивкой по severity (high/medium) и «слепыми зонами» (что померить не удалось).
Как и здоровье, риски ВПРЫСКИВАЮТСЯ сверху (risk_register живёт в intelligence, выше planning);
нет данных -> `not_computed` (честно), а не пустота.

Провязка закрыла ещё два модуля «мёртвого острова» аудита: `risk_register` и `drift_artifacts`
(risk_register строит риски через build_reports — здоровье×3 + дрейф — поэтому оба стали достижимы
из CLI). `KNOWN_UNREACHABLE` сократился фактом проводки. Из восьми модулей острова закрыто ШЕСТЬ;
остаются `team_sync` и governance-тройка (policy_engine/decision_log/human_override).

Вживую: на реальной дочке contract показывает `риски: high=1, medium=0; слепых зон: 10`.
