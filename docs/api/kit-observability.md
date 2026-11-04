# Kit Observability

`ai_ops_kit/devtools/kit_observability.py` — метрики эффективности самого кита.

## CLI

```bash
# Человекочитаемый отчёт
python3 ai_ops_kit/devtools/kit_observability.py <child_root>

# JSON-формат
python3 ai_ops_kit/devtools/kit_observability.py <child_root> --json
```

## Метрики

### Cost

- `total_cost_usd` — общая стоимость всех вызовов
- `total_calls` — число вызовов моделей
- `avg_cost_per_call` — средняя стоимость вызова
- `avg_cost_per_workitem` — средняя стоимость на задачу
- `by_task_type` — разбивка по типу задачи (QUICK/ENGINEERING/PRODUCT)
- `by_provider` — разбивка по провайдеру
- `by_role` — разбивка по роли (implementation/review/fix_loop)
- `cost_complete` — True если все вызовы имеют известную стоимость

### Workitems

- `total` — число задач
- `by_status` — разбивка по статусу (draft/done/blocked)
- `by_lifecycle` — разбивка по стадии жизненного цикла
- `by_workflow` — разбивка по workflow

### Delivery

- `total` — число попыток доставки
- `sha_verified` — доставлено с верифицированным SHA
- `merged` — PR смержены
- `success_rate` — доля успешных доставок

### Models

- `by_provider` — число вызовов по провайдеру
- `by_model` — число вызовов по модели
- `measured_calls` — вызовы с известным usage
- `unavailable_calls` — вызовы без usage data

## Честность

- `unavailable` cost НЕ считается как $0 — показывается отдельно
- Пустой репозиторий → "Нет данных", не нулевые метрики
- Все метрики вычисляются детерминированно из файлов

## Локальная трасса одного WorkItem (экспериментальный срез #1411)

```bash
python3 -m ai_ops_kit.devtools.kit_observability /path/to/child --workitem wid-1
python3 -m ai_ops_kit.devtools.kit_observability /path/to/child --workitem wid-1 --json
```

Внутренний API: `ai_ops_kit.devtools.workitem_trace.compute(root, workitem_id)` и
`format_text(report)`. Это devtools самого Kit; в child пакет не устанавливается.
Предыдущий агрегат без `--workitem` сохраняется. Небезопасный id отвергается argparse
(code 2). Корректный read-only запрос возвращает code 0 даже для `partial`/`no-data`:
это результат диагностики, а не допуск к доставке.

Источники ограничены тремя файлами `features/<id>/`: `lifecycle-journal.jsonl`
(вместе с существующим `.head`), `usage-ledger.jsonl`, `run-report.json`.
Продуктовый ledger не складывается с task ledger, чтобы не удваивать вызовы.
Journal проверяется существующим `lifecycle_store.journal_read`; повреждённая цепочка
не используется даже частично. Пропуски/повреждения usage явно видны в diagnostics.
Новые receipts, lock-файлы, каталоги, процессы и сетевые запросы не создаются.
Symlink внутри путей источников отвергается; выбранный root разрешается явно.

Трасса связывает WorkItem → Run → Attempt и записи вызовов по явным id.
Идентификаторы псевдонимизируются SHA256 (24 hex); это не обещание анонимности от
словарного перебора, а защита от случайного вывода сырого содержимого id.
Связь invocation с attempt без `attempt_id` остаётся `null`. Gates/reviews из
последнего `run-report.json` помечены `latest-snapshot`: они связаны с WorkItem,
но их принадлежность конкретному attempt/run не угадывается. `unmet` подтверждает
непройденный gate, отсутствие в нём само по себе не объявляет pass.
Порядок `source_order` определён внутри каждого файла. Порядок между journal,
ledger и snapshot не является временем/причинностью. Один `event_id` journal
повторно не считается; конфликтующие payload отмечаются и весь journal исключается.
Сохранившийся `.head` при удалённом journal и неверные типы секций snapshot
дают `partial`; повреждённый `.head` не подтверждает целостность журнала. Одинаковые строки
ledger сохраняются: без invocation id нельзя отличить повторный вызов от копии.

Длительность Attempt вычисляется только из единственной пары `run_start/run_end`
с одинаковыми run/attempt id и timezone-aware `timestamp`; отрицательная, неполная,
повторная и невалидная пара даёт `unknown`. Поля `started_at`/`ended_at` события
обрабатываются по тому же правилу. `latency`, mtime и порядковый номер не заменяют
timestamps; старые записи обычно не имеют временных границ.

В метриках `known` — наблюдаемая сумма, `total` — сумма только при полноте данных
читаемого task ledger, иначе `null`/`status: unknown`. Это не подтверждение полноты
всех реальных вызовов WorkItem. Измеренные и оценочные значения сохраняют числа;
недоступные, отрицательные, bool, нечисловые и бесконечные значения не становятся
нулём. Потеря точности/переполнение суммы стоимости проверяется существующим
`usage_ledger.aggregate` и делает полный итог unknown. Для retries нужен известный `trigger` каждого вызова. `failed_gates.known`
считает только непройденные gates последнего snapshot; полный итог истории unknown.
Tool calls и human interventions пока unknown. Имена известных token-атрибутов
`gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` взяты из
[OTel GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/).
Отчёт не объявляется полным OTel trace/span-контрактом; SDK/exporter отсутствуют.

Redaction реализована разрешённым набором выходных полей: prompts/transcripts,
команды, stdout/stderr, evidence, blockers, task, пути, произвольные status/kind,
provider/model/role и тексты ошибок не копируются. Только фиксированные категории,
псевдонимы связей и числовые измерения. Реальные transcripts для работы не нужны.

Остаётся в #1411: полная WorkItem/Run/Agent invocation/Tool call/Gate/Review история
с достоверными связями и timestamps этапов; полная локальная статистика retries,
failed gates, tool calls и human interventions; полный согласованный словарь OTel
GenAI. Опциональный экспорт не реализован. Первый срез не закрывает issue.

### История package receipts (срез 2)

Тот же CLI дополнительно читает `features/<id>/work-packages/<package>/report.json`
и `attempts/attempt-N/report.json` внутри каждого пакета. Это существующие snapshots:
`workpackage_executor._persist_package_report` сохраняет отчёт, а `retry_package`
переносит предыдущую попытку в архив. Reader ничего не архивирует и не создаёт.
При разработке используются только синтетические fixtures, реальные transcripts не нужны.

`events[].package_id` — псевдоним существующего package_id journal/ledger, если поле
заполнено. Package snapshot получает package_id из канонического пути хранения;
`snapshot_id` связывает только observations одного сохранённого отчёта. Архивы
идут по числовому N (`attempt-2` перед `attempt-10`), затем текущий snapshot.
Число N называется `storage_attempt`: это **не** attempt_id прогона. Пропущенные
номера не заполняются; текущему snapshot номер не присваивается. Одинаковое
содержание разных архивов сохраняется раздельно, идентификаторы событий уникальны.

Snapshot проецирует существующие gates/reviews, а также до40 сохранённых элементов
метаданных `loop.transcript`: только `step`, `op` (read/write/shell/git), булевы
`allowed`/`ok`. `reason`, команды, пути, содержимое и свободный текст не выводятся.
Эти элементы названы `tool_attempt`, потому что среди них есть запрещённые и ещё
не исполненные предложения; `done` не является инструментом. Повторный номер шага
делает инструментальную секцию неоднозначной — она исключается с diagnostics.
Отсутствующий `ok`, связь с конкретным invocation/run/attempt и длительность
остаются unknown. Новый сбор или запись transcripts не вводится.

Нужны `kind: execution-pipeline` и совпадающий workitem_id. Повреждённый/чужой отчёт,
нечитаемый каталог, symlink и отсутствующий отчёт архивной попытки диагностируются;
они не превращаются в pass. В частности, инфраструктурные error envelopes без
workitem_id не объявляются привязанной историей. Последовательность подтверждена
только внутри snapshot и архива одного пакета; общий временной порядок не выводится.
Исторические observations не прибавляются к метрикам первого среза: latest snapshot
может дублировать текущий package report, а tool metadata producer усекает до40.
`tool_calls.total` и полный исторический failed-gates остаются unknown.

Граница дальнейшей корреляции установлена по producer-коду: поле package_id есть
в UsageRecord, но обычный `_build_run_proposers._uctx` и `_record_cost_and_clear`
его не заполняют. Reader сохраняет такой invocation без package_id даже при одном
пакете. `run-history/run-*.yaml` содержит настройки, а `branch-review.yaml` и
`review/verdict.yaml` перезаписываются; из них полную историю не восстановить.
Native thread/turn живут в call stats, но normalize ledger их не сохраняет.

Для следующего отдельного решения потребуется минимальная запись связующих полей
в существующие receipts: package_id из work_package_id, run/attempt/invocation id
для вызова и ссылка на invocation для tool/gate/review, плюс timestamps границ
этапа. Для истории непакетных gate/review нужно сохранять привязанные результаты
вместо одного перезаписываемого snapshot. Ни одной такой правки producer этот срез
не делает; полное OTel и закрытие #1411 в него не входят.
