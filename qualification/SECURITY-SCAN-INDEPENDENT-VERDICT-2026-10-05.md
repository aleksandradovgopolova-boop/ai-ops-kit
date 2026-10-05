# Независимый security-судья: полевой снимок, 05.10.2026

Объект: `/tmp/ai-ops-ii-sreda-field-20261005`, исходный commit `160d99b5f989faa698ddfdd722f3df398fe0ccdf`. Вход: `/tmp/ai-ops-security-field-20261005.json`, 2696 файлов; 5 product-адресов, 4 harness, 1 vendor. Временный `src/shared/kit-field-probe.ts`, добавленный после скана, не включён. Проверка только чтением; продукт и кит не менялись этим судьёй. Секреты не воспроизводились.

Численные условия текущего замера выполнены: product = 5 ≤ 5, NOISE = 1 ≤ 2. BORDERLINE = 4, RELEVANT = 0 в product. Это оценка замера, а не объявление цели владельца достигнутой и не доказательство отсутствия уязвимостей. `no_injection_surface` остаётся предметом отдельного решения review; без базы зависимости и поставка не сравнены.

NOISE — внимание потрачено впустую; BORDERLINE — читать стоило, по просмотренному пути внедрение не найдено; RELEVANT — действующая опасная поверхность требует отдельной оценки.

| Адрес | Вердикт | Причина и контекст |
|---|---|---|
| `server/files/scanner.mjs:36` | BORDERLINE | `spawn(bin, args)` на реальном пути проверки загрузки. `bin/args` берутся из операторского `FILE_SCAN_CMD` (25–28); shell не включён; пользовательские байты передаются только в stdin (43). Безопасность опирается на доверенное окружение сервера, поэтому адрес полезен. |
| `server/generation/models-catalog.mjs:71` | NOISE | `query` здесь — алиас HTTP `fetch` (68), `${cfg.baseUrl}/models` — URL, SQL не исполняется. Имя `query` заставило SQL-эвристику принять сеть за БД. Возможные отдельные сетевые вопросы не превращают этот флаг в SQL surface. |
| `src/features/artifact-export/useArtifactExport.ts:119` | BORDERLINE | Настоящий `document.write(html)` в окне приложения. HTML строится в `builders/html.ts`: `escapeHtml`, `safeExternalHref/safeMarkdownHref`, строгое `safeImageSrc` только растрового data URL. Проверка выше по потоку необходима; сохранение адреса оправданно. |
| `src/features/note-blocks/BlockEditor.tsx:121` | BORDERLINE | Сток принимает `chartToSvg(block)`; тонкий реэкспорт ведёт в `server/domain/chart-svg.mjs`. Подписи экранируются `esc`, численные координаты нормализуются `num`, тип выбирается из таблицы рендереров. Недоверенная HTML-строка непосредственно не вставляется. |
| `src/features/note-blocks/BlockView.tsx:60` | BORDERLINE | Тот же генератор и тот же анализ. Это второй адрес одного вопроса; даже при счёте его как дополнительного NOISE общий шум = 2 ≤ 2. |

## Harness: все четыре адреса проверены отдельно

| Адрес | Вердикт | Контекст |
|---|---|---|
| `e2e/prepare-database.mjs:46` | BORDERLINE | Реальная SQL-интерполяция имени схемы в разрушительный DROP. Живой CLI использует константу `E2E_SCHEMA = "e2e_app"`; импортируемая `prepareDatabase(base, schema)` допускает произвольный параметр. В текущих тестовых вызовах внешнего ввода нет, но флаг полезен для проверки границы. |
| `e2e/prepare-database.mjs:47` | BORDERLINE | CREATE использует тот же параметр без quoting/проверки; тот же вывод. Не называть универсально безопасным только потому, что файл e2e. |
| `src/shared/lib/pg-stale-locks.test.ts:38` | NOISE | `execFileSync("bash", [script, dir, ...args])` запускает фиксированный локальный скрипт файлом, без `-c`; каталог создаёт тест. Проверяемый shell-скрипт не является внедряемой строкой. |
| `vite.config.ts:13` | NOISE | `execSync('git rev-parse HEAD')` — константная команда определения версии сборки, данных запроса/PR в строке нет. |

## Vendor: не входит в product-счёт

`.ai/managed/ai_ops_kit/engine/tool_broker.py:544` — RELEVANT: настоящее `subprocess.run(action["command"], shell=True)` для осознанной ветки команд с shell-синтаксисом. Код рядом различает argv-путь и NeedsShell; на ветке остаются policy, scrub_env, timeout, скраб вывода и post-factum контроль файлов. Это реальная поверхность, не шум; её адресат — сопровождающий кита. Проверка этих ограничений целиком в этот узкий полевой замер не входит. Версия поставки 4.9.0; базовой ревизии нет, новизна находки неизвестна.

## Проверка потерянных командных поверхностей

`rg` по raw коду включал **scripts/**, server, e2e и src; `.exec` регулярных выражений отделён от child_process. Просмотрены реальные импорты и вызовы child_process: scanner; vite; e2e/run-app; server-wrapper/server-guards/shutdown tests; pg-stale-locks; docs-consistency; scripts/check-status-freshness; scripts/check-test-vacuum. Оболочка с динамической строкой вне отмеченных адресов не обнаружена.

Снятые адреса проверены контекстом: `check-status-freshness.mjs:38` вызывает литеральный git с массивом аргументов; PR_BODY не попадает в команду, BASE_REF идёт в отдельный аргумент diff. `check-test-vacuum.mjs:251` вызывает доверенный process.execPath с фиксированным путём Vitest; распаковка tests — аргументы, распаковка env вложена и shell не включает. e2e/run-app запускает текущий node с argv, три server tests — литеральный node и фиксированный server/index.mjs. docs-consistency — фиксированные git log argv.

Дополнительно raw просмотр scripts/*.sh и scripts/proby/*.py: `health-monitor.sh` передаёт тело через stdin, служебные значения через env, inline JS записан литералом; `ci-runner-preflight.sh` имеет литеральное `python3 -c "import yaml"`; `proba_pamyati_polnaya.py:89–93` строит inline Node-код с f-string, но SREDA объявлен константой `/home/cel3/services/ii-sreda` на строке 36. Текущий детектор снимает такую константу. Прямой вызов `scan_injection` для этих scripts и двух JS-харнессов вернул пустые списки — это сопоставлено с raw-кодом, а не принято на веру.

Реальный false negative command injection в просмотренном снимке не найден. Ограничение сохраняется: литеральный бинарь не доказывает безопасность произвольных аргументов (например git/node могут исполнять код флагами); сам `scan_exec_call.py` это честно объявляет. Здесь доверенное происхождение снятых аргументов просмотрено; весь репозиторий не подвергался полноценному taint-анализу.

## Сопоставление

Файлов `qualification/SECURITY-SCAN-*2026-09-25*` в Kit нет. Есть независимый вердикт 24.09 и перезамер 28.09, последний ссылается на решение владельца 25.09. Сравнение с 28.09: product 4 → 5, добавился ложный SQL-адрес HTTP-каталога; четыре прежних адреса сохраняют BORDERLINE. Шум 0 → 1 (либо 1 → 2 при строгом учёте повторного SVG-стока), численные пределы не превышены. Harness DROP/CREATE в данном отчёте оценены осторожнее прежнего NOISE из-за публичного параметра schema; это изменение суждения, не новая уязвимость. Vendor остался отдельной действующей shell-поверхностью.
