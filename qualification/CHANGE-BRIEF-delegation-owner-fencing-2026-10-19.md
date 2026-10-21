# Change Brief — позднее завершение после переназначения (2026-10-19)

- Результат: прежний автоматический запуск после takeover сохраняет работу нового держателя и сообщает отказ до старой доставки/перезаписи отчёта.
- Пути: automatic saved admission → canonical active claim → bounded package dispatch → владение перед delivery/report → условный finish под существующим lock; legacy explicit finish сохраняется.
- Инварианты: одна попытка — одна durable generation; прежняя generation не меняет новую заявку, runtime projection и carrier; Budget/policy/auth/isolation/Intent reconciliation не ослабляются.
- Failure modes: takeover во время пакетов; новый запуск с той же session identity; отсутствующая/повреждённая заявка; поздний finally; ошибка записи/проверки состояния.
- Доказательство: actual RED на base 2cda991a, настоящий Git/реестр/takeover + frozen byte proof; positive own finish; stale same-identity fail-closed; targeted/core/ruff/guards и exact-head CI после независимого review.
- Границы: fencing на проверяемой границе завершения; не остановка уже начатого внешнего запроса и не полное recovery/resume/checkpoint всех пакетов.
- Не входит: новый scheduler/runtime, зависимости, durable budget/physical/USD ceilings, native/provider calls, security settings, release/adoption, полевые claims/owner acceptance и shared planning.
- Источник: #1316/#1314; исторические #669/#745/#403/#406; #1278 остаётся отдельной полевой приёмкой.

Refs #1322: только первый технический срез полного продуктового контракта, не закрытие направления. На неизменённом base три новые регрессии упали до production-правок; после первой реализации три прошли. Дополнительно проверяются отсутствие/повреждение/закрытие заявки и takeover во время уже допущенной доставки: факт выполненного callback сохраняется, чужой отчёт не перезаписывается.

Точные production-файлы: `engine/parallel_live_dispatch.py`, `lifecycle/active_work.py`, существующий `lifecycle/work_claims.py` (проверка generation и короткий lock для записи отчёта, без сетевого вызова под общим lock). Файлы под `ai_ops_kit/`; новых модулей/слоёв нет.
