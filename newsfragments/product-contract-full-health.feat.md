Product Contract, срез 5 — ПОЛНОЕ здоровье в контракте. Раньше грань health несла только
product-измерение; теперь `ai-ops contract`/`ai-ops products` сводят ТРИ измерения —
product + tech + delivery — одним rollup'ом `health_common` (worst-known-band побеждает, unknown
не зеленит, причины — драйверы итога по всем трём). Вокабуляр прежний (green/yellow/red/unknown),
вердикт понимает его без изменений.

Провязка закрыла ещё два модуля «мёртвого острова» аудита: `health_tech` и `health_delivery` были в
`KNOWN_UNREACHABLE` (ехали в поставку, звали только тесты) — теперь достижимы из CLI, список ратчета
сократился фактом проводки. Остаются шесть: risk_register/team_sync/drift_artifacts и governance
(policy_engine/decision_log/human_override) — следующие срезы.

Слой соблюдён: три измерения считает CLI (видит intelligence вниз) и впрыскивает в контракт;
planning intelligence вверх не тянет. Сбор обёрнут — сбой не роняет просмотр контракта.
