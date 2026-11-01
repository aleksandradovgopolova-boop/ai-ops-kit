# #1411 — локальная read-only трасса одного WorkItem, срез 1

- Результат: `kit_observability <root> --workitem <id> [--json]` связывает существующий lifecycle journal, task usage ledger и последний run-report одной задачи.
- Пути: devtools/kit_observability CLI → devtools/workitem_trace → существующие файлы features/<id>; API-документация и fixture-тесты. Usage writer, runtime и hooks не меняются.
- Инварианты: только чтение явно выбранных локальных файлов, без сети/процессов/моделей; unknown ≠ 0; не выводить prompts, transcripts, команды, пути, ошибки и свободный текст из источников. Идентификаторы источников псевдонимизируются.
- Failure modes: повреждённый/усечённый journal; потерянная привязка задачи/прогона; повтор события против повторного вызова; неполные usage/timestamps; утечка через данные/симлинк/ошибку.
- Доказательство positive: deterministic fixture с несколькими attempts, usage/retry, gate/review; длительность только из пары timezone-aware timestamps. Fail-closed: corrupt/missing/mismatched данные явно диагностируются, итоги не полные. Side-effect/environment: fixtures реально записаны до snapshot; отчёт не меняет дерево и работает при запрете write/network/subprocess.
- Не входит: полное закрытие #1411; tool-call/human-intervention instrumentation, полная OTel span-модель, exporter/SDK/server, новые hooks, реальные transcripts/credentials/permissions, push/PR/merge/релиз. Вне журналов нет полной причинной временной последовательности; последний run-report — snapshot, не история всех gate/review.

Acceptance issue проверены 2026-11-01: WorkItem/Run/Agent invocation/Tool call/Gate/Review; длительности по этапам; cost/tokens/tool-calls/retries/failed-gates/human-interventions локально; default без сети. Этот срез покрывает доступные invocation usage, journal и gate/review snapshot; отсутствующие измерения остаются unknown. Полная привязка invocation к attempt невозможна в старом ledger без attempt_id; не угадывать её по порядку.
