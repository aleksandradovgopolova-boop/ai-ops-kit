# Команда: ai-release-readiness

## Назначение

Проверить готовность изменения к выпуску.

## Порядок выполнения

1. Проверить применимость существующих результатов quality gates (content inputs, а не только SHA).
2. Проверить миграцию и rollback.
3. Проверить monitoring и alerts.
4. Проверить release notes и коммуникацию.
5. Назначить одного владельца до подтверждения опубликованной версии; выполнить безопасный preflight.
6. Использовать coordinator из `workflows/release.md`: lock среды, durable intent, сверка runtime/public.
7. Зафиксировать go/no-go по DeployRecord: FAIL/BLOCKED/SKIP не заменяются словом «успех».

## Результат

Release Checklist с вердиктом готовности; после исполнения — проверяемый DeployRecord.
Готовность не означает, что выпуск уже опубликован. При неопределённом исходе — сначала
reconciliation, без автоматического повтора deploy или rollback.

## Ограничения

- Соблюдать scope, evidence policy и human approvals.
