# #1401 — проверка обязательных контекстов защиты main

Результат: рассинхрон декларации, workflow и доступной защиты GitHub виден; недоступная защита получает `unknown`, а не PASS.

Затрагиваемые пути: библиотечный `validate`, извлечение имён CI jobs (включая matrix/name), CLI JSON/текст/exit code, read-only GitHub API через `gh`, воспроизведение по сохранённому JSON API snapshot, контрактные тесты и запуск из изолированной копии в test_validator_runtime_contract.py (explicit unknown/exit 2 вместо прежнего offline 0, при сохранении обнаружимости в общем checklist-контракте).

Инварианты: никакой записи в GitHub; только stdlib + pyyaml; offline-проверка workflow отделена от проверки защиты; старые декларации `workflow / quality (group)` однозначно разрешаются в полное имя matrix job; неоднозначность и недоступность не дают PASS. Общие реестры, CI и декларация не меняются.

Failure modes: 403/timeout/нет gh; отсутствующее или повреждённое свидетельство; потерянный matrix suffix; лишний обязательный контекст без job; декларация без фактической required-проверки.

Доказательство: positive exact match; fail-closed unknown при 403/некорректном JSON; реальная мутация snapshot/declaration перед проверкой drift; subprocess proof только GET-команд; native macOS targeted pytest, ruff и короткий core smoke.

Не входит: изменение branch protection/rulesets, исключений/прав обхода, workflow, CI billing, credentials, реестров и общих планов; commit/push/PR/merge/deploy. Даже при совпадении checks это не аудит исключений/прав обхода или rulesets. API403 блокирует закрытие issue.

Исходная база: origin/main `083bcf3cfbb25b2e526672c0c2be588b992d7213`, сверено с GitHub GET git/ref/heads/main 2026-10-28. `.agents/skills` и `.claude` в этой базе отсутствуют; AGENTS.md, CLAUDE.md и engineering-cycle прочитаны. Открытые PR проверены до начала реализации; дубля #1401 нет.


Дополнение к границам перед публикацией: пользователь через координатора разрешил commit/push/draft PR, переход в ready и merge кода после полного PR-профиля, независимого review и обязательных CI точного head. Для связи используется Refs #1401: issue остаётся открытой. Разрешение не включает настройки безопасности; protection, grants, billing, credentials и formal GitHub APPROVE не меняются. Первоначальная локальная стадия выше сохранена как история.


Доказательства и ограничения: [отчёт #1401](../evidence/1401-required-contexts/report.md).
