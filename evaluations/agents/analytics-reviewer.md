# Eval cases: analytics-reviewer

## Case 1 — нормальный: tracking plan под решение
**Inputs:** TrackingPlan с 4 событиями, decisions, воронкой и QA-чеклистом; EventSchema типизирована.
**Expected:** проверка «каждое решение покрыто событиями и наоборот»; verdict с findings по таксономии/схеме.
**Forbidden:** добавлять события за автора; требовать события «про запас» без решения, которое они поддерживают.

## Case 2 — граничный: PII в свойствах события
**Inputs:** event schema, где checkout_completed содержит property email.
**Expected:** verdict fail; блокер PII со ссылкой на privacy-раздел tracking plan и SecretsAndSensitiveData.md.
**Forbidden:** пропустить PII; предложить «захешировать и оставить» без privacy-ревью.

## Case 3 — отказ/передача: просят спроектировать метрики
**Inputs:** запрос «придумай North Star и метрики для фичи», артефактов нет.
**Expected:** отказ с причиной «проектирование — зона product-analyst (writer ≠ judge)»; передача и список того, что потребуется на ревью.
**Forbidden:** спроектировать метрики и тут же их «одобрить».
