# #1401 — локальная реализация и доказательства

## Результат

Валидатор сверяет декларацию с workflow и, при явно предоставленных API-данных, с контекстами классической защиты ветки. Workflow-проверка (`workflow_ok`) отделена от итога (`status`, `ok`). Без данных GitHub и при недоступной полной защите: `status=unknown`, `ok=false`, CLI exit 2. Совпадение подтверждённых контекстов: exit 0; подтверждённый рассинхрон/ошибка workflow: exit 1.

Сохранённое свидетельство main показывает 12 объявленных контекстов и 10 в сводке классической защиты. В сводке отсутствуют `docs / build` и `package-quality / security-scan`. Все 12 имеют соответствующие workflow jobs. Полные matrix-имена включают путь скрипта; исторические сокращения декларации разрешаются только однозначно. Историческое сокращение из самой API-защиты не подменяет полное фактическое имя.

**Дополнение 2026-10-28 11:44 UTC: read-only Chrome.** По новому явному разрешению пользователя выполнен просмотр через её существующую GitHub-сессию. Меню аккаунта подтвердило login `aleksandradovgopolova-boop`; breadcrumb settings подтвердил репозиторий. Настройки открылись без нового запрета сайта. Integration API повторно не вызывался, cookies/tokens не извлекались.

UI подтвердил применимое классическое правило `main`, ID `81759903`, «Currently applies to 1 branch». Флажок required status checks включён; выбранные **10** полных имён совпали с прежней API-сводкой. Для каждого источник — **GitHub Actions**. `security-scan` и `build` действительно не выбраны обязательными в этом правиле. Список repository rulesets показывает **«You haven't created any rulesets»**: в просмотренном списке нет активных, evaluate или disabled правил. Это наблюдение конфигурации с указанным временем, не утверждение о неизменности сервера после чтения.

`Require a pull request before merging` и `Require branches to be up to date before merging` выключены. `Do not allow bypassing the above settings` тоже выключен; подпись UI связывает включение этого флажка с применением защиты к администраторам и custom roles с `bypass branch protections`. Следовательно, видимая конфигурация допускает исключение этих категорий; конкретные именованные обладатели прав не подтверждены (их список в форме не показан, общий access/roles не исследовался). Force pushes и deletions выключены. Runtime-обход/слияние для проверки не предпринимались.

Сверка UI с локальной декларацией воспроизводимо даёт **fail: 12 объявлено, 10 required, отсутствуют ровно два контекста**. Новые доказательства хранятся отдельно: `browser-observation.json`, минимальные AX-выдержки `browser-ui-evidence.txt`, вычисленный `browser-comparison.json` и offline-команда `compare-browser-evidence.py`. UI-наблюдение не замаскировано под API HTTP200: исходные `github-snapshot.json`/`validation-result.json` сохранены, API-результат остаётся unknown. Настройки не менялись, Save не нажимался.

Полное закрытие #1401 остаётся заблокированным: подтверждённое расхождение не исправлено и решение об отклонении не оформлено; API403 сохраняется. Просмотр настроек через явно разрешённую UI-сессию снял прежнюю неопределённость об их видимой конфигурации, но не подтвердил все фактические права акторов/поведение обхода.

## Рабочая копия

- Checkout-источник: `/Users/sasad/ai-ops-kit`; его существующие изменения сохранены.
- Worktree: `/Users/sasad/Documents/Codex/2026-10-28/task-2/p0-1401-required-contexts`.
- Ветка: `codex/p0-1401-required-contexts`.
- База: `083bcf3cfbb25b2e526672c0c2be588b992d7213`, совпадение локального origin/main и GitHub GET git/ref/heads/main проверено перед созданием worktree.
- AGENTS.md, CLAUDE.md и engineering-cycle прочитаны. В базе нет `.agents/skills`/`.claude`; единственный навык в `/Users/sasad/.agents/skills` посвящён презентациям и к задаче не относится.
- Issue открыт; открытые PR проверены до кода, дубля #1401 нет (`preflight.json`).

## Изменения

- `ai_ops_kit/validation/validate_required_contexts.py`: отдельные результаты workflow/защиты; JSON snapshot и явный live-режим через `gh`; только два bounded GET, без fallback при отказе; полные matrix/name, `.yaml` наряду с `.yml`, выявление отсутствующих/лишних/неразрешимых required-контекстов; malformed/missing evidence не становятся PASS.
- `tests/contracts/test_required_contexts_match_jobs.py`: positive, fail-closed, реальные мутации входов, неизменность GET-only команд, 403/timeout/missing-gh/malformed JSON, неоднозначность, native CLI коды 0/1/2 и запуск копии из другого каталога.
- `tests/unit/test_validator_runtime_contract.py`: только отметка покрытия данного валидатора перенесена из общего ожидания offline 0 в существующие специальные контракты. Новый offline exit 2 проверяется отдельными контрактами; проверки остальных валидаторов сохранены.
- Отдельный Change Brief и данный каталог evidence. Общие планы, FILE_INDEX.md, реестры, декларация required contexts и CI не менялись.

## Проверки локальной стадии до разрешения публикации

Интерпретатор `/Users/sasad/ai-ops-kit/.venv/bin/python`: Python 3.14.7, macOS. Без xdist, тяжёлых замеров и полного pytest.

1. `PYTHONDONTWRITEBYTECODE=1 /Users/sasad/ai-ops-kit/.venv/bin/python -m pytest tests/contracts/test_required_contexts_match_jobs.py tests/unit/test_validator_runtime_contract.py -q -m 'not slow' -p no:cacheprovider` — **151 passed, 101 deselected**, 0.77 s (45 контрактов данного валидатора и 106 быстрых контрактов runtime).
2. Короткий core smoke: `tests/unit/test_preflight.py tests/unit/test_gate_executor.py` — **102 passed**, в общем раннем прогоне вместе с 41 контрактом валидатора: 143 passed, 3.36 s. После этого менялись только валидатор/snapshot-контракты, которые повторно проверены п.1.
3. `/Users/sasad/ai-ops-kit/.venv/bin/ruff check ai_ops_kit/validation/validate_required_contexts.py tests/contracts/test_required_contexts_match_jobs.py tests/unit/test_validator_runtime_contract.py` — **PASS**.
4. `git diff --check` — **PASS**.
5. CLI на сохранённом snapshot — **ожидаемый exit 2**, `workflow_ok=true`, `protection.status=unknown`, `drift_detected=true`, `ok=false`. Полный JSON: `validation-result.json`.

В ходе разработки дополнительный тест другого branch обнаружил, что загруженный snapshot оставался в памяти после ValueError. Исправлено сбросом snapshot; регрессия входит в 151 passed.

Не выполнялись: полный локальный PR/nightly/release профиль, Python 3.12/3.13 CI-матрица, проверки CI итогового head и независимый premerge review. Commit/push/PR/merge/deploy и формальные PR approvals не выполнялись. Ни одного живого вызова `gh` к отказавшему endpoint после 403 не было: live reader проверен через subprocess doubles, воспроизведение — offline.

## Блокеры и их уточнение после Chrome

1. **DENIED, API403.** Действие: GET `https://api.github.com/repos/aleksandradovgopolova-boop/ai-ops-kit/branches/main/protection`. Причина: `Resource not accessible by integration`. Завершены независимые чтения issue/PR/main и branch summary, локальная реализация/тесты. API-доступ остаётся denied. Видимая конфигурация дополнительно подтверждена разрешённым браузерным просмотром (см. выше), но именованные фактические bypass grants и runtime enforcement остаются unknown. Отказавший API не повторялся; права/credentials не менялись.
2. **DENIED by connector allowlist, HTTP400.** Действие: GET `https://api.github.com/repos/aleksandradovgopolova-boop/ai-ops-kit/rules/branches/main`. Причина: `GitHub Fetch URL is not an allowed public GitHub repository or search endpoint`. Этот API endpoint не повторялся. После нового явного разрешения пользователя repository rulesets просмотрены в Chrome UI: список пуст; активных/evaluate/disabled rows нет. Иные административные policy-системы не исследовались. Точный ответ сохранён в `preflight.json`.
3. UI подтвердил отсутствие required security-scan/build. Владелец/координатор должен либо включить их в отдельной разрешённой работе, либо оформить явное решение об отклонении. В рамках этой задачи изменение защиты запрещено. Полное закрытие #1401 заблокировано.

## Воспроизведение

Новая offline-сверка UI-наблюдения, без обращения к сети или браузерному хранилищу:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/sasad/ai-ops-kit/.venv/bin/python \
  docs/evidence/1401-required-contexts/compare-browser-evidence.py
# comparison_status=fail, missing_required=[docs / build, package-quality / security-scan]
```

Исторический API snapshot сохраняет прежний unknown:

```bash
cd /Users/sasad/Documents/Codex/2026-10-28/task-2/p0-1401-required-contexts
PYTHONDONTWRITEBYTECODE=1 /Users/sasad/ai-ops-kit/.venv/bin/python \
  ai_ops_kit/validation/validate_required_contexts.py \
  --github-snapshot docs/evidence/1401-required-contexts/github-snapshot.json --json
# Ожидается exit 2 (unknown), два missing_required; это исторический snapshot, не live-проверка.
```

Тесты воспроизводятся командой п.1. Live-режим реализован (`--github-repo OWNER/REPO --branch main`), но повторять отказавшие чтения в этой сессии без новых разрешённых оснований не следует.

Diff с новыми evidence-файлами передан отдельным `/Users/sasad/Documents/Codex/2026-10-28/task-2/p0-1401-required-contexts.patch`; он применим к указанной базе. Общие индексы/план и eventual release fragment остаются координатору.


## Проверка дополнения Chrome

Product-код и тесты после 151 passed не менялись: добавлены только task evidence и обновлён этот отчёт. Offline-сверка новых UI-фактов выполнена и воспроизводит два missing_required. Ruff для evidence-скрипта и git diff --check пройдены. Chrome browser-provider отсутствовал в inventory, но native Chrome был доступен; один координатный вызов дал noWindowsAvailable, дальнейшая штатная accessibility/keyboard-навигация сработала. Permission/grant/settings изменения для доступа не выполнялись. Финальная вкладка оставлена на не редактирующем списке rulesets.


## Переход к публикации

После завершения локальной стадии получено явное разрешение пользователя через координатора на commit/push/draft PR, ready и merge кода после полного штатного PR-профиля, независимого review и CI точного head. Ветку связываем через Refs #1401, issue остаётся открытой; изменение защиты и формальный GitHub APPROVE не разрешены. Перед стартом публикации remote main повторно сверено: `083bcf3cfbb25b2e526672c0c2be588b992d7213`, дубля открытого PR для #1401 нет. Добавлен отдельный newsfragment `1401-required-contexts-protection.fix.md`. Перечисленные выше «не выполнялись» относятся к предшествующей локальной стадии; результаты новой проверки/публикации фиксируются отдельно от review-входов во внешнем task-каталоге, чтобы квитанция могла быть привязана к неизменному итоговому diff.


Независимое review перед публикацией выявило P1: внутренние qualified aliases декларации ошибочно принимались за реальные API status names. Исправлено отдельным индексом точных emitted job names, включая буквальные имена с ` / `; добавлены fail-closed регрессии. Первый полный PR-прогон автора корректно остановлен после находки (4128 passed, 29 skipped; interrupted, НЕ полный PASS). Для исправленной версии требуется новый полный PR-профиль и повторное независимое review. Исторические snapshot/UI-выводы остаются прежними.


Полный PR-профиль исправленной версии завершён: 10019 passed, 35 skipped, 2 failed за 923.89s. Выявлены два интеграционных шва: общий checklist-контракт не учитывает BESPOKE mapping; новые Markdown-документы недостижимы из docs/index.md. Контракт запуска валидатора скорректирован: он остаётся в STANDALONE для обнаружимости, а изолированный subprocess для этого конкретного валидатора обязан дать explicit unknown/exit 2 без API evidence (остальные standalone по-прежнему обязаны дать 0). Из Brief добавлена task-only ссылка на отчёт; общая индексная ссылка запрошена у координатора. Требуются повторное независимое review изменённой delta и новый полный PR-профиль; предыдущие full результаты не объявляются PASS.
