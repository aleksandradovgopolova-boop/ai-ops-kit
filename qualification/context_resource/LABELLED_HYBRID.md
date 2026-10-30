# Labelled-hybrid E2E — Change Brief #1403

**Результат.** Реальный локальный pipeline проверяет source-метрики на фактически
поданном hybrid payload: полная разметка даёт `measured`, потеря метки v2-источника —
`incomplete_labels` и три `null`. Прежний сценарий без разметки остаётся `unknown`.

**Пути.** Fixture → заранее записанные source-labels → штатный `ai_ops_run.run` →
compiled v1 + настоящие v2-additions → writer-вход → запись результата →
context-payload/run-report. Код движка и новый механизм сбора не нужны.

**Инварианты.** Labels не выводятся из полученного payload и не меняются после
запуска. Проверяются реальный writer-вход, его сохранённый контекст и запись файла.
Forbidden-файлы существуют; наблюдатель чтений действует только во время pipeline.
Оценка source-токенов и число источников не выдаются за фактический usage провайдера.

**Failure modes.** Разметка составлена задним числом; метрика рассчитана лишь для v1;
неполные labels становятся measured; payload и writer-вход расходятся; forbidden
читается до writer или бюджет не блокирует исполнение.

**Доказательство.** Positive: четыре поданных источника (три relevant, один irrelevant)
и один заранее объявленный missing relevant, precision = 3/4, miss = 1/4, ненулевой
waste. Fail-closed: отсутствие метки `src/hybrid.py` даёт incomplete/null при том же
реальном дополнении. Side-effect: два вызова локального proposer, одна настоящая
запись, исходный HEAD неизменён; полный payload есть в первом writer-входе, метрики
artifact и run-report равны, forbidden имеет ноль наблюдённых чтений. Проверки идут
на native macOS и с `GIT_CONFIG_GLOBAL=/dev/null`; платной модели/сети нет.

**Не входит.** Полевая/семантическая калибровка релевантности, native tool reads,
полный prompt/usage провайдера, Storybook, runtime/схемы/гейты, состав 4.12.
Синтетические source-labels fixture объявлены явно и не закрывают issue целиком.

Повтор: `python3 -m qualification.context_resource.run --labelled-hybrid --output /tmp/new-context-e2e`.
Каталог должен быть новым. Результаты — `evidence.json`, fixture и writer-контексты
внутри каталогов сценариев. `Path.read_text` наблюдается только внутри
`ai_ops_run.run`, не при подготовке fixture и не в самостоятельных native-процессах.
Обычный artifact не сохраняет текст. Harness наблюдает исходный объект, возвращённый
настоящим `build_payload` (возвращает его без замены); после реального добавления v2
сохраняет `compiled-payload.txt` и проверяет его присутствие в writer-входе.
Без флага остаются прежние три сценария. Записанное дополнительное свидетельство —
`labelled_evidence.json`; обычное `evidence.json` относится к baseline, а не к полевой
оценке релевантности. Оба набора используют один существующий harness.
