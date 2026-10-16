# #1183/#611: линт правок native Codex

## Результат
Тонкий адаптер принимает документированный Codex PostToolUse apply_patch с
`tool_input.command`, проверяет существующие изменённые/перемещённые файлы тем же
линтером и baseline, что Claude. Сейчас такой event молча даёт exit0 без проверки.
У явно настроенного Codex установщик сохраняет свою запись в .codex/hooks.json.

## Затрагиваемые пути
installer/lint_hook_setup.py; installer/asset_ops.py; templates/runtime/lint_hook.py;
tests/unit/test_lint_hook.py; tests/unit/test_lint_hook_setup.py;
validation/own_medicine_checks.py; engops/process_spend.py;
tests/unit/test_own_medicine.py; brief/замер/news.

## Инварианты
Существующий линтер, без нового runtime/tool-loop/гейта. Claude-путь совместим.
Только собственная запись, чужое сохранено, malformed JSON не переписывается,
повтор идемпотентен, opt-out снимает своё. Codex нужен только при явно configured/default.
Доверие Codex к точному определению хука не подделываем и автоматически не выдаём.
PostToolUse не отменяет уже сделанную правку; отказ — обратная связь и последующий CI.

## Failure modes
Тихий пропуск apply_patch; пропуск второго файла или Move to; неправильно разобранный
payload назван проверкой; переписаны чужие настройки; установка названа live enforcement.

## Доказательство
Negative до кода: Codex apply_patch с BAD в настоящем fixture-файле даёт0 и не зовёт
линтер; ожидается2 и фактический вызов. Positive/fail-closed/side-effect: multi-file,
move/delete, unreadable payload, реальные команды установленных hooks, preservation.
До исправления7регрессий падали; после91passed14.31s. Независимый AI review: NO FINDINGS.
Свежий независимый AI review, focused, full-current-python, GitHub CI.

## Не входит
Изменения файлов через Bash, автоматическая подмена trust-state, полный runtime
execution/owner acceptance, живой Claude. Установка сама по себе не field proof.

Источник API: https://learn.chatgpt.com/docs/hooks (проверен 16.10.2026):
project-local .codex/hooks.json; canonical apply_patch/tool_input.command;
неуправляемый новый hook пропускается, пока доверие не подтверждено runtime.

## Контролируемая полевая проверка
На изолированном clone реальной ии-среды обычный native Codex получил автоматический
отказ ESLint после apply_patch и исправил имя; следующий hook0. Первый запуск без
code-mode-host не сделал правку; ремонт и дополнительная попытка зарегистрированы.
На реальных JS/Python-репозиториях профиль сохраняет baseline и отказывает на росте
имён/импортов. Точные версии, ограничения, hashes, native receipts и драйверы:
native-lint-field-2026-10-16/. Не owner acceptance и не полевая когорта #1243.

Общий прогон остановлен после1failed/1853passed/28skipped143.29s: AST-ратчет
обнаружил новый шаг доставки без решения self-application. Для Codex переиспользована
проверка Claude с честной заменой Ruff без managed. Correction review NO FINDINGS;
293целевых проверки прошли184.10s. Финальный full-current-python CPython3.14.7/darwin:
9154passed35skipped2warnings853.50s.

Следующий full:1failed/9153passed/35skipped1236.27s — новая .codex/ поставка
считалась кодом продукта. Engops классификатор дополнен рядом с .claude/;
существующий install-тест сохраняет положительную проверку реальной src-правки.
