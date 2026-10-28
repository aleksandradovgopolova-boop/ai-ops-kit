# #1408 — локальный JS/TS AST-пилот

Ограниченный opt-in пилот реализован и функционально проверен. Время анализа **не измерено**.
Прямое согласие пользователя на 7 пар после успешной проверки ресурса получено.
Ранее отклонённая команда повторена один раз с новой авторизацией и разрешена проверкой
доступа. Штатный noise gate остановил её до warmup: CPU **26,84% / 21,06%** при пороге 15%.
Текущее состояние — **WAITING_FOR_QUIET_RESOURCE**, 0 измеренных отсчётов.
Benchmark-серии и warmup не запускались; повторное согласие не требуется.
Issue целиком закрытым не считается. Коммитов, push, PR, merge, deploy и rollout нет.

## Исходники и границы

- Ветка: `codex/p0-1408-jsts-ast-pilot`.
- Worktree: `/Users/sasad/Documents/Codex/2026-10-28/task-4/p0-1408-jsts-ast-pilot`.
- База: `083bcf3cfbb25b2e526672c0c2be588b992d7213`; актуальный remote main проверен через
  `git ls-remote origin refs/heads/main` до создания worktree, 2026-10-28.
- [Issue #1408](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1408) открыт.
  Перед стартом проверены открытые PR: #1419, #1395, #1394, #1371, #1361, #1352, #1274; дубля AST-пилота нет.
- Прочитаны корневые `AGENTS.md`, `CLAUDE.md`, инженерный цикл и шаблон Change Brief.
  `.agents/skills` в checkout и его worktree отсутствует; в `/Users/sasad/.agents/skills`
  найден только нерелевантный `magazine-web-ppt`. Change Brief сохранён до реализации.
- Изменение движка ограничено `ai_ops_kit/context/repo_graph.py`. Отдельные тесты и evidence
  находятся рядом с этим отчётом и в `tests/unit/test_repo_graph_jsts_ast.py`.
- Общие planning/plan.yaml, FILE_INDEX.md, реестры, CI и обязательные зависимости не менялись.
  Основной checkout с чужими изменениями не переключался и не очищался.

## Поведение

Включение только программное и явное:

```python
from ai_ops_kit.context.repo_graph import build_graph

graph = build_graph('/path/to/project', subdirs=None, js_analyzer='tree-sitter')
```

`regex` остаётся default; default-путь не импортирует optional packages. Парсеры JS/JSX,
TS и TSX загружаются по необходимости, максимум один раз на grammar в одной сборке графа.
Между сборками parser/cache не сохраняется. Установки пакетов из runtime-кода нет.

AST извлекает literal import/re-export, прямой `require`, literal dynamic `import()`,
TS import-require и распознаваемые type imports. Комментарии и строки не считаются кодом.
Символы ограничены именованными декларациями верхнего уровня; это не полный symbol table.
Диагностика каждого JS-файла доступна в `graph['js_analysis']`: backend, specifiers,
признак неразрешённых выражений или причина fallback.

Отсутствующая/несовместимая grammar и ожидаемая ошибка parser дают прежний regex и видимую
причину. Ошибки syntax recovery дают regex плюс `unreadable`; непрочитанный UTF-8 исходник
даёт backend `none` и `source-unreadable`. Успешный AST-файл всё равно `unbounded`:
существующий resolver по stem не является Node/tsconfig resolution. Успех парсинга не даёт
оснований сужать проверки потребительского проекта.

## Закреплённый read-only срез

Источник: локальные git objects `/Users/sasad/ii-sreda`, revision
`7b14b251acc65cdf50de4439ef3013c5f83858c1`. Рабочие файлы consumer не читаются и не меняются:
используются только `git ls-tree` и `git cat-file blob`. Репозиторий consumer не исполняется.

Из 1019 подходящих файлов в `src`, `server`, `e2e`, `scripts`, `eslint-rules` выбраны 160.
Выборка детерминированная: группы (корневой каталог, расширение, test/other), round-robin
по группам, порядок внутри группы — SHA256 имени файла. Она намеренно покрывает разные
формы кода, **не пропорциональна всему проекту** и не является статистической оценкой.
В срезе: 36 TS, 36 TSX, 86 MJS, 2 JS; реальных JSX/CJS в этой выборке нет — они проверены
только синтетическими fixtures. Файлы копии имеют режим 0444.

[comparison.json](comparison.json) содержит revision, выборку, blob id и SHA256 каждого
файла, исходные specifiers обоих извлекателей, изменённые stem-рёбра, fallback и координаты
ошибок грамматики. SHA256 полного среза до/после совпадает:
`d35f724e61a198b35c2fd4ec2a1e75b871934919caa24a37136e8dfe73c8fd80`.

| Показатель | Результат |
| --- | ---: |
| Файлов в выборке | 160 |
| Успешных AST-разборов | 152 |
| Fallback из-за syntax recovery | 8 |
| Regex file–specifier пар во всех 160 файлах | 590 |
| Regex пар в сопоставимых 152 файлах | 546 |
| AST пар в тех же 152 файлах | 537 |
| Только AST | 7 |
| Только regex | 16 |
| AST-файлов с вычисляемыми импортами | 2 |

8 fallback-файлов содержат 44 regex-пары. Эти файлы не включены в сравнение расхождений;
сопоставление 590 и 537 без этой оговорки было бы некорректным.

Это **не precision/recall**: независимого полного oracle проекта нет. Ручная проверка
охватывает 23 расходящиеся пары и причины 8 отказов грамматики, не все импорты проекта.

## Разбор расхождений и ошибок

7 пар, которые пропускал regex, проверены по закреплённым исходникам:

| Файл | Specifier | Форма |
| --- | --- | --- |
| `e2e/export.e2e.mjs:72` | `fs` | `await import(...)` |
| `e2e/stability.e2e.mjs:69` | `jszip` | `await import(...)` |
| `scripts/eval-corporate-agents.mjs:58` | `../server/generate-core.mjs` | `await import(...)` |
| `server/generation/normative-tool.mjs:558,591` | `./memory-tools.mjs` | два вызова, одна уникальная пара |
| `src/features/artifact-export/builders/pptxBuilder.test.ts:219` | `../../../entities/presentation/build` | `await import(...)` |
| `src/shared/api/dev-wiring.test.ts:111` | `../../../e2e/_browser.mjs` | `await import(...)` |
| `src/shared/api/domainClient.ts:2087` | `./client` | type-position `import(...).UpdateAdminCatalogInput` |

16 regex-only пар находятся в строках/шаблонах кода и комментариях:
8 в `eslint-rules/rules.test.mjs`, 6 в `scripts/check-prod-deps.test.mjs`, 1 (`x`) в
комментарии `scripts/check-prod-deps.mjs`, 1 (`node:module`) в генерируемом `policyHook`
в `scripts/eval-corporate-agents.mjs`. Последний шаблон используется для запуска другого
кода: отсутствие AST-импорта в текущем файле **не доказывает отсутствие runtime-зависимости**.
Поэтому все JS-файлы AST-пилота сохраняют консервативную uncertainty.

На выбранном подграфе добавились два внутренних stem-ребра:
`dev-wiring.test.ts → e2e/_browser.mjs`, `domainClient.ts → shared/api/client.ts`.
У `eslint-rules/rules.test.mjs` снялись три ребра к разным `model.ts`, возникшие из строк
с примером `../baz/model`. Остальные новые imports ведут во внешние пакеты или файлы
за пределами выборки. Количество найденных specifiers не равно полноте внутренних рёбер.

8 файлов grammar 0.23.2 отвергает: 6 TSX-тестов с `orig<typeof import(...)>()` /
`importOriginal<typeof import(...)>()`, `printPdf.test.ts` с
`Parameters<import("playwright").Page["pdf"]>` и `src/shared/api/client.ts` с
`Promise<import("./types").Scenario[]>`/`AdminGroup[]`. Это **отказ выбранной grammar**,
а не доказательство невалидности TS. Пути/координаты всех ошибок сохранены в JSON.
Regex fallback используется на всём таком файле; recovered partial AST не принимается.

Два файла `eval-content-grounding.mjs` и `eval-note-cutoff.mjs` используют вычисляемые
`import(new URL(...))` / `import(root + ...)`; статически они здесь не разрешаются.

## Ограничения

- Одна выборка одного revision не доказывает точность на произвольном JS/TS-проекте.
- Нет tsconfig aliases, package exports, Node resolution, точного разрешения одинаковых stem,
  различения типов и runtime-рёбер, анализа shadowing `require` или generated code.
- Не поддерживаются вычисляемые specifiers, JS escape-последовательности внутри specifier,
  template literals, `module.require`/`require.resolve`, AMD, импорт по данным конфигурации.
- `.mts`/`.cts` не добавлялись в прежний список расширений. Destructuring/ambient declarations
  и полная структура символов не заявляются.
- ABI/версии проверены только на указанных ниже Python/macOS и трёх pinned wheels.
- TypeScript Compiler API не добавлялся; runtime-потребители Kit сами в пилот не переводятся.

## Проверки

Экспериментальная среда: Python 3.14.7, macOS arm64;
Tree-sitter 0.25.2, JavaScript grammar 0.25.0, TypeScript grammar 0.23.2.
Использован API [официальных Python bindings](https://github.com/tree-sitter/py-tree-sitter).
Wheels получены из официального PyPI в отдельную `task-4/ast-pilot-env`, URL и hashes —
[optional-install.json](optional-install.json). Обязательные зависимости Kit не изменены.

- 135 passed: AST-тесты, существующий repo_graph, исключение области Kit и три набора
  регрессий безопасного impact/test selection.
- 40 passed / 9 skipped: repo_graph + AST-пилот в существующей среде **без Tree-sitter**.
  Пропущены только проверки с реальными grammar; замоканные отказы/fallback исполнены.
- Реальный `ModuleNotFoundError` проверен отдельно в среде без пакетов:
  [fallback-without-tree-sitter.json](fallback-without-tree-sitter.json), ребро сохранено.
- 4 passed: fail-closed проверки нового timing harness — preflight-only, шум, занятый
  процесс и занятый slot не доходят до build_graph/таймера. Эти тесты НЕ являются benchmark.
- 34 passed: короткий core smoke `tests/contracts/test_critical_path.py -m critical_path`.
- Ruff на изменённых Python-файлах и `git diff --check`: PASS.
- `validate_layering.py`: PASS (89 межпакетных рёбер, 19 пакетов, циклов нет).
- НЕ ЗАПУСКАЛИСЬ: широкие/nightly/compatibility CI, тяжёлые performance-прогоны,
  независимый review перед merge (merge вне scope), полный recall относительно oracle.

Время анализа остаётся **NOT_RUN / WAITING_FOR_QUIET_RESOURCE**. Текущий blocker — CPU-шум.
Прежний отказ доступа снят новой прямой авторизацией пользователя и успешным допуском
однократного повтора команды; обходов не было. Обычные sandbox DNS-ограничения GitHub/PyPI
ранее сняты штатным approval.
Для интеграции координатору отдельно останутся общие index/planning и release-fragment,
если он будет готовить PR; эти поверхности здесь намеренно не изменены.

## Воспроизведение

Из корня worktree (новый snapshot-каталог должен отсутствовать):

```bash
python3 -m venv /tmp/ast1408-env
/tmp/ast1408-env/bin/python -m pip install --index-url https://pypi.org/simple --only-binary=:all: \
  -r docs/evidence/1408-jsts-ast-pilot/requirements-experiment.txt
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 /tmp/ast1408-env/bin/python \
  docs/evidence/1408-jsts-ast-pilot/compare_snapshot.py \
  --repo /Users/sasad/ii-sreda --snapshot /tmp/ast1408-snapshot \
  --output /tmp/ast1408-comparison.json
PYTHONDONTWRITEBYTECODE=1 /tmp/ast1408-env/bin/python -m pytest -q \
  tests/unit/test_repo_graph_jsts_ast.py tests/unit/test_repo_graph.py \
  tests/unit/test_repo_graph_excludes_kit_area.py tests/unit/test_bounded_impact_selection.py \
  tests/unit/test_impact_incomplete_traversal.py tests/unit/test_verification_impact_safety.py
PYTHONDONTWRITEBYTECODE=1 /tmp/ast1408-env/bin/python -m pytest -q \
  tests/contracts/test_critical_path.py -m critical_path
/tmp/ast1408-env/bin/python -m ruff check ai_ops_kit/context/repo_graph.py \
  tests/unit/test_repo_graph_jsts_ast.py docs/evidence/1408-jsts-ast-pilot/compare_snapshot.py
```

Команда сравнения не содержит часов/таймера и не исполняет consumer. Нужен локальный git object
указанного consumer revision; произвольный HEAD автоматически не подставляется.
Локальный патч всех изменений сохранён вне дерева в `task-4/p0-1408-jsts-ast-pilot.patch`.


## Дополнение: допуск времени после #1409

Реальные измерения **NOT_RUN**; speedup, медиан и процентов ускорения нет.
[Отказ доступа](timing-approval-block.json) фиксирует точное действие, target и причину:
7 последовательных пар на закреплённом срезе отклонены **до исполнения**. Причина —
подтверждение окна пришло от другой сессии, а проверка требует подтверждения человека.
Это историческая запись первоначального отказа. После прямого согласия пользователя
выполнен ровно один повтор команды; новый отказ доступа не получен. До измерений повтор
не дошёл из-за CPU-шумa — текущий статус в [timing-state.json](timing-state.json).

Отдельно разрешённый [preflight-only receipt](timing-preflight.json) содержит команды,
окружение, raw `top` и сведения о штатном резерве. Проверка не строит граф даже для warmup:
это закреплено четырьмя тестами `test_jsts_ast_timing_admission.py`.

- Штатный `/tmp/ai-ops-kit-heavy.lock` получен и освобождён штатным `host_slot`; inode не удалялся.
- Совпавших тяжёлых процессов: 0; чужие процессы не останавливались.
- CPU (последние два интервала): 23,70% / 32,57%; допуск пилота требует <=15% в обоих.
- Load1 2,352 при 10 logical CPU; memory-pressure free 42%; swap used 4457,75 MB,
  swap I/O в отсчётах 0/0; свободно 22 872 023 040 байт. Эти условия допуск не блокировали.
- Срез до/после совпал по тому же SHA256. Consumer не изменён, измеренных samples: 0.
- CPU-порог 15% — заранее записанное консервативное условие этого короткого сравнения;
  это не изменение общей политики Kit. Условия допуска не ослаблялись ради чисел.

### Точный план будущего запуска

Прямое подтверждение человека уже получено; команда ниже остаётся ожидающей чистого окна. Сначала harness
проверит SHA256 всех 160 файлов, получит штатный slot, применит штатный busy-process probe,
затем три коротких `top`-отсчёта (первый отбрасывается). Требования: aggregate CPU <=15%,
load1/logicalcpu <=0,5, memory-pressure free >=20%, swap I/O 0, диск >=10 GiB.
При отказе ресурса записывается NOT_RUN; ничего не ждёт бесконечно и не останавливает процессы.

При допуске: одна warmup-пара, затем 7 пар с порядком AB, BA попеременно; A=regex,
B=tree-sitter. Все вызовы последовательные, один процесс и тот же read-only срез. `perf_counter_ns`
и `process_time_ns` охватывают `build_graph`: чтение файлов, извлечение, построение графа,
инициализацию parser для каждой сборки. Первичный import модулей исключён warmup; OS cache
прогрет. Хеширование, проверка результатов и probes вне timed region. Это не cold-start тест.
Рёбра/диагностика сверяются с functional comparison и полным digest каждого backend.

Перед каждой парой и после всей серии проверяется шум; нарушение делает серию INVALID_PARTIAL,
сырые отсчёты сохраняются, итоговые медианы не публикуются. Семантика regex и AST различается,
поэтому даже чистое время не является доказательством точности или оптимизации общего Kit.

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../ast-pilot-env/bin/python \
  docs/evidence/1408-jsts-ast-pilot/time_snapshot.py \
  --snapshot /Users/sasad/Documents/Codex/2026-10-28/task-4/jsts-snapshot-7b14b251 \
  --comparison docs/evidence/1408-jsts-ast-pilot/comparison.json \
  --output /tmp/ast1408-timing-approved.json --pairs 7
```

Для безопасной проверки допуска без benchmark добавить `--preflight-only`.
Выход 2 означает NOT_RUN/INVALID_PARTIAL, не успех измерения. Нужны обычные read-only
разрешения ОС для `top`, `ps`, `sysctl`; отказ доступа не обходить. Существующий `comparison.json`
сохраняет историческую timing-пометку первоначального функционального этапа; текущий статус
смотрится в [timing-state.json](timing-state.json) и последнем receipt ниже.


### Обновление после прямого согласия пользователя

Пользователь подтвердил запрос на 7 парных измерений после успешной проверки ресурса.
До однократного повтора проверено: первоначальная операция отклонена до исполнения,
benchmark output отсутствовал, прежний preflight содержал 0 samples. Ровно один повтор
той же timing-команды допущен штатной проверкой доступа. Нового denial нет.

[Последний receipt](timing-resource-attempt.json) фиксирует **NOT_RUN** до warmup:
CPU 26,84% / 21,06%; load1 3,748 при 10 logical CPU; memory-pressure free 51%;
swap used 4979,75 MB, swap I/O 0/0; диск 21 480 607 744 байт. Блокирующая причина —
только aggregate CPU выше заранее заданных 15%. Штатный slot получен/освобождён;
matched/busy heavy processes — пустые списки. Срез до/после имеет прежний SHA256.

Состояние сохранено как **WAITING_FOR_QUIET_RESOURCE**. Отсчётов по-прежнему 0;
загрязнённого baseline, warmup, изменения порогов, остановки чужих процессов и фонового
автоповтора нет. Прямая авторизация сохраняется; новый запрос согласия не нужен.
Код движка, harness и результаты функциональных проверок не изменялись.
