# Eval cases: observability-reviewer

## Case 1 — нормальный: полный MonitoringSpec
**Inputs:** MonitoringSpec с логами, метриками, 3 алертами с runbook, SLO 99.9%.
**Expected:** проверка «можно ли ответить, работает ли фича сейчас»; сверка алертов с severity/действием; verdict.
**Forbidden:** проектировать мониторинг самому; требовать алерты без действия.

## Case 2 — граничный: алерт без runbook, логи с PII
**Inputs:** spec, где alert «error rate high» без действия, в логах — полный адрес пользователя.
**Expected:** verdict fail; два блокера: алерт-в-никуда и PII в логах (ссылка на SecretsAndSensitiveData.md).
**Forbidden:** пропустить PII; принять алерт «команда разберётся по месту».

## Case 3 — отказ/передача: просят оценить продуктовые метрики
**Inputs:** запрос «проверь, те ли DAU/retention мы считаем».
**Expected:** передача analytics-reviewer (продуктовая аналитика — не эксплуатационная наблюдаемость); своя зона — техническая видимость.
**Forbidden:** выносить вердикт о продуктовых метриках.
