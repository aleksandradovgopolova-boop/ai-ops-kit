# #1409: воспроизводимая база скорости и памяти

**Статус: NOT_RUN.** Готовы harness, suite и лёгкие регрессии. Чистая база не снята:
первое окно координатор выделил, но проверка реальной нагрузки Mac не подтвердила
его чистоту. Подробности — в `RESOURCE_WINDOW.json`. Замеры из unit-тестов
проверяют инструмент и не являются baseline продукта. Общие CI/план/реестры не изменены.

## Что измеряется

Тот же `python -m ai_ops_kit.devtools.bench_performance`, дополнительный `--suite`.
`suite.json` содержит реальные argv (без shell), домен и timeout каждого этапа:
запуск человеческого CLI, запуск mock-provider, preflight, lint и critical contracts. Отдельный `suite-pr.json` содержит существующий полный
локальный PR-профиль с одним worker и требует другого, более длинного окна. Один и тот же интерпретатор
подставляется вместо `{python}`. Это исходники checkout, не установленный wheel.

Каждый этап выполняется последовательно: 1 прогрев + 3 измерения. Все 4 попытки,
их exit code/ошибки, stdout/stderr, wall time, CPU и пик RSS остаются в receipt/logs.
`repeat_count` — число повторных запусков после первого, включая прогрев;
`iterations` — число измеряемых запусков. Это **не** количество провалившихся CI retry:
ручные rerun различаются `GITHUB_RUN_ID`/`GITHUB_RUN_ATTEMPT`, если серия исполняется в Actions.

Время включает создание и ожидание процесса команды, исключает загрузку измерителя,
Git/сбор сведений о среде и запись receipt. Отдельный свежий worker на попытку исключает
накопление `RUSAGE_CHILDREN` между этапами. `ru_maxrss` нормализован в bytes
(macOS: bytes, Linux: KiB × 1024). Это максимум RSS дочернего процесса по учёту ОС,
**не** сумма памяти одновременно живущего дерева. Для параллельного CI требуется
отдельная методика суммарной памяти; текущая серия намеренно использует один worker.

В receipt: точный HEAD SHA, dirty-флаг и SHA256 diff + untracked, argv/cwd/timeout,
ОС/хост/архитектура/CPU count, версия и путь Python, версии установленных зависимостей,
allowlist переменных среды, время начала и load average. Исходники во время серии
должны быть заморожены. `dirty_sha256` отличает незакоммиченную реализацию от чистого HEAD;
сам receipt не содержит diff/содержимое untracked. Результаты хранить вне checkout.

## Очередь и ресурсное окно

1. Координатор согласует очередь с AST-пилотом/ИИ/МШХ и резервирует отдельный интервал.
   В ограниченной серии 5 команд; верхняя граница по timeout:
   (1+3) × (60+60+60+120+300) секунд,
   фактическое время должно быть намного меньше timeout. Тяжёлый PR-профиль не запускать
   для проверки самого harness; для него есть короткие subprocess-тесты.
2. Проверить отсутствие параллельной сборки, симулятора, тестов или другой реальной
   нагрузки. Существующий wrapper `host_resource_cli` проверяет общую блокировку
   `/tmp/ai-ops-kit-heavy.lock` и наблюдаемые тяжёлые процессы; load average одного
   снимка сам по себе не доказывает чистое окно. Другие процессы/lock не удалять.
3. Выполнить серию ниже. Отказ wrapper означает BLOCKED; не менять lock path, права,
   не подменять переменные lease. При обычном sandbox-ограничении нужен штатный approval.
4. Удерживать окно до завершения сравнения. При возникшей нагрузке сохранить серию
   как contaminated и не назначать её baseline. Wrapper проверяет допуск в начале,
   не обещает, что неуправляемая сторонняя нагрузка не появится позднее.

## Команды после выделения окна (не исполнены)

Из этого worktree на Mac, с уже существующим окружением:

```bash
KIT_PY=/Users/sasad/ai-ops-kit/.venv/bin/python
export PYTHON="$KIT_PY" PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0
RUN_DIR=$(mktemp -d /tmp/kit-baseline-1409.XXXXXX)
SUITE=qualification/evidence/performance-baseline-1409/suite.json
"$KIT_PY" -m ai_ops_kit.devtools.host_resource_cli --owner p0-1409-baseline -- \
  "$KIT_PY" -m ai_ops_kit.devtools.bench_performance \
  --suite "$SUITE" --iterations 3 --warmup 1 --output "$RUN_DIR/base.json"
"$KIT_PY" -m ai_ops_kit.devtools.host_resource_cli --owner p0-1409-repeat -- \
  "$KIT_PY" -m ai_ops_kit.devtools.bench_performance \
  --suite "$SUITE" --iterations 3 --warmup 1 --baseline "$RUN_DIR/base.json" \
  --regression-threshold 1.2 --output "$RUN_DIR/repeat.json"
```

Первая успешная серия: `NO_BASELINE` (exit 0), не «регрессий нет». После проверки
чистоты оператор явно назначает её базой через `--baseline`; автоматической записи
в старую `.bench-baseline.json` нет. `OK`/exit 0 возможен только для сопоставимых
успешных серий, время и RSS каждого этапа ≤ выбранного отношения к базе.
`REGRESSION`/exit 1 — превышен порог времени **или** памяти; `ERROR`/`INVALID`/
`INCOMPARABLE` также дают ненулевой exit. Порог 1.2 — начальное исследовательское
значение, не статистическая гарантия; после нескольких чистых серий оценить шум.
Baseline и output различны; существующий output и logs не перезаписываются.

## CI, повторы и границы выводов

Домен `ci` на этом Mac — **локальная реплика этапов**, не GitHub Actions: она не
включает provisioning, checkout/setup, очередь runner, сетевую установку, все matrix
jobs, coverage или nightly. Нельзя складывать её время и объявлять общей стеной CI.
На реальном CI нужны серии на том же runner/toolchain и точном SHA, с сохранением
run ID, attempt, jobs/steps и их длительностей. Сквозную стену и job-time следует
показывать отдельно; пропущенная job не является нулём. В обычных Actions logs нет
данных о пике памяти — это unknown, пока этот harness не исполнен на runner.
Внешние CI rerun и их причины не выводятся из локальных повторов; нужны API-данные
всех attempts. Создание/перезапуск Actions и изменение workflow здесь не выполнялись.

Полный критерий issue остаётся открытым до чистого runtime baseline, повторной
сопоставимой серии и измерений настоящего CI. Код не создаёт обязательный CI-гейт.

## Лёгкое воспроизведение проверки механизма

```bash
/Users/sasad/ai-ops-kit/.venv/bin/python -m pytest tests/unit/test_bench_performance.py -q
/Users/sasad/ai-ops-kit/.venv/bin/python -m pytest tests/contracts/ -q -m critical_path
/Users/sasad/ai-ops-kit/.venv/bin/ruff check ai_ops_kit/devtools/bench_performance.py tests/unit/test_bench_performance.py
```

Контролируемая деградация: один и тот же argv читает тестовую задержку, исполняется
без задержки, затем с 250 ms. Сначала проверяется факт исполнения и реальная разница
времени, затем красный результат сравнения. Дополнительно проверяется удвоение RSS,
ошибка команды, timeout, ошибка прогрева, несовместимость среды/планов/повторов,
JSON roundtrip, отсутствие lease и сохранность байтов базы. Этот тест не доказывает
производительность продукта и не устанавливает базу.
