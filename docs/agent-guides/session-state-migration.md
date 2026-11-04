# Перенос ожидающих проектных сессий (experimental)

[Change Brief и failure modes](../change-briefs/1434-session-state-migration.md).

Локальный CLI переносит binding доказанно неисполненного pending-запроса после обновления
managed-кода. Он не запускает задачу/модель, не меняет UUID, active pointer, signals, claims,
результаты и статусы. Snapshot и migration receipt не являются acceptance или независимым review.

Поддерживается standalone Git checkout на POSIX, schema_version=1, переход внутри major.
Root/branch/HEAD остаются прежними; исходная binding должна совпадать с контекстом capture.
Preparation/provider_preparation, execution, verification, claim, spec/review/results, неизвестные
поля или уже устаревшая binding означают сохранение записи без изменений с причиной в
`plan.preserved`. Неактивная история также сохраняется. Suggested-message marker не подтверждает
происхождение запроса и не разрешает skip/close. Повторный перенос уже мигрированной записи пока
не поддержан автоматически; неизвестное состояние требует отдельного решения.

## Предусловия и границы снимка

Нужны installation owner, согласованное окно без старых writers и освобождение живых importers.
Idle/notLoaded этого не доказывают. Shared/exclusive lock нового кода не защищает от старого,
не знающего lock; `--quiescent-window` подтверждает внешнее согласование, а не устанавливает его.
Занятые locks вызывают немедленный отказ. Порядок: migration barrier → preparation → requests.

Отдельно сохраните полный приватный backup проекта, dirty Git state, установки и истории.
Capture — ограниченный снимок, не полный backup. Он включает `.ai/runtime`, `features`,
`.ai/runplan`, `openspec/changes`, `.git/ai-ops/claims`, managed и config/hooks. Исключены
служебные migration/lock/pycache файлы и installer-owned runtime backups, last-update-report,
ci-templates, skill-prints: штатный update меняет их самостоятельно. Прежний version-keyed
installer backup нужно сохранить отдельно до update, который может заменить этот каталог.
Installer rollback здесь не реализуется.

Лимиты снимка: 128 MiB/50 000 файлов; symlinks, внешние hardlinks и special files отклоняются.
Snapshot/plan создаются вне child с mode 0600 без перезаписи имени. Храните их в приватном каталоге;
не публикуйте содержимое пользовательских запросов или результатов в PR.

## Согласованная последовательность

Запускайте migration-команды из проверенного checkout **нового** кита с PyYAML.
Пример ниже относится к disposable/согласованному child, не к активной primary:

```sh
python3 -m ai_ops_kit.cli.project_session migrate capture \
  --project /private/session-copy --snapshot /private/evidence/snapshot.json --quiescent-window
```

Сохраните SHA256. Затем отдельно выполните штатный update из проверенного source:
`python3 /path/to/reviewed-kit/installer/ai_ops.py update --in-place` из cwd child.
До переноса не коммитьте, не переключайте ветку, не запускайте задачи/hooks и не меняйте продукт.

```sh
python3 -m ai_ops_kit.cli.project_session migrate preview \
  --project /private/session-copy --snapshot /private/evidence/snapshot.json \
  --snapshot-sha256 SNAPSHOT_SHA --plan /private/evidence/plan.json --quiescent-window
```

Изучите приватный plan: `changes` содержит точные before/after bytes/modes, `preserved` — причины
отказа для остальных записей. Manifest/checksums проверяются. Допускается только изменение config
`parent.installed_version`, равное VERSION, и наблюдаемое штатное удаление ровно двух пустых строк
между соседними маркерами `AI-OPS-COMMUNICATION-POLICY:END` и `AI-OPS-PROJECT-SESSION:BEGIN`
в CLAUDE.md. Остальной текст/mode сравнивается. После preview контекст проверяется уже точно,
включая raw source digest, поэтому последующие правки этого разделителя также блокируют apply.

```sh
python3 -m ai_ops_kit.cli.project_session migrate apply \
  --project /private/session-copy --snapshot /private/evidence/snapshot.json \
  --snapshot-sha256 SNAPSHOT_SHA --plan /private/evidence/plan.json \
  --plan-sha256 PLAN_SHA --quiescent-window
```

Apply повторно строит план под lock, сверяет защищённый состав и CAS каждой записи. Durable WAL
предшествует первой замене. Повтор того же apply идемпотентен лишь при неизменном after-state.
Выход 0 подтверждает операцию, а не accepted задач; 2 — отказ. stdout содержит только счётчики,
phase, transaction ID и digests, без пользовательских текстов.

## Прерывание и rollback

Незавершённая транзакция блокирует session writers. Не удаляйте journal/claim и не создавайте
повтор запроса. Изучите приватные plan/journal в `.ai/runtime/sessions/.migrations/<transaction>/`:

```sh
python3 -m ai_ops_kit.cli.project_session migrate rollback \
  --project /private/session-copy --transaction TRANSACTION_ID \
  --plan /private/evidence/plan.json --plan-sha256 PLAN_SHA --quiescent-window
```

Оригинальный plan нужен и после прерывания создания внутреннего WAL. Rollback сначала сверяет
весь состав; собственные before/after допустимы, concurrent input/claim/result или drift вызывают
отказ без стирания новых данных. Прерванный rollback продолжается с теми же ID/digest. Остатки
staging остаются приватными вне защищённого состояния. Автоматического merge/skip/close нет.

Rollback возвращает bytes/modes состояния, не старую установку. Managed/config/hooks восстанавливаются
отдельно согласованным способом. Копия в другом root не доказывает resume исходной сессии.
Reload hooks/importers и live trust требуют отдельной проверки; недоступный cloud claim не восстанавливается.
После committed migration новый turn сохраняется как immutable input того же pending. После нового
ввода rollback отказывает. Старые review/results не становятся действительными для нового кода;
штатные gates и независимые проверки остаются обязательными.
