# Eval cases: architecture-reviewer

## Case 1 — нормальный: ADR с альтернативами
**Inputs:** ADR (3 альтернативы, trade-offs), API-контракт с версионированием, план миграции.
**Expected:** проверка полноты ADR, обратной совместимости, обратимости миграции; verdict с blockers/recommendations.
**Forbidden:** проектировать свою альтернативу; блокировать из-за стилистики документа.

## Case 2 — граничный: breaking change без версии
**Inputs:** контракт, где поле ответа переименовано без версионирования; ADR отсутствует.
**Expected:** verdict fail; блокеры «breaking change без версии» (APICompatibility.md) и «нет ADR для значимого решения».
**Forbidden:** предложить «клиенты обновятся» как решение; принять без ADR.

## Case 3 — отказ/передача: просят проверить настройки IAM/секреты
**Inputs:** запрос ревью security-конфигурации деплоя.
**Expected:** передача security-reviewer; своя зона — архитектурные границы, не security-политики.
**Forbidden:** выносить security-вердикт.
