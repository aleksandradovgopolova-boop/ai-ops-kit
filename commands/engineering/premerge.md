# Допуск к штатному merge AI Ops Kit

Поддерживаемый локальный маршрут разработки Kit. Требует установленного `gh` с уже существующим доступом к репозиторию. Не меняет права, branch protection, runners и deploy gates.

Запуск из доверенной версии Kit (политика `quality/premerge-checks.json`):

```bash
python3 -m ai_ops_kit.devtools.premerge --repo owner/repo --pr 123 \
  --head EXACT_40_HEX_SHA --review /path/to/review.json \
  --review-sha256 TRUSTED_64_HEX_SHA256
```

По умолчанию — только чтение. `--merge` повторяет полный допуск и вызывает исключительно `gh pr merge ... --squash --match-head-commit EXACT_SHA`. Никаких `--admin`, обхода защиты и пропуска gates. Исход успешной команды — `merge-command-succeeded`, а не обещание фактического merge: после действия проверьте статус PR в GitHub. При timeout/ошибке сначала проверьте исход, затем решайте о повторе.

## Review-квитанция

Оператор проверяет происхождение независимого review всей итоговой delta и получает SHA256 квитанции из доверенного канала. Авторский JSON, переименованный reviewer и вычисление hash недоверенного файла не доказывают независимость. Helper проверяет структуру и привязку, не подлинность review. Передавайте идентичность автора из GitHub PR; reviewer — отдельная read-only сессия/человек. После новых правок или смены base требуется новый review соответствующей delta.

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "pr": 123,
  "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "base": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "author": "github-author-login",
  "reviewer": "independent-review-session-id",
  "scope": "entire-delta",
  "status": "pass",
  "findings": [],
  "blockers": [],
  "evidence": "path or URL to independently produced review report"
}
```

Неразрешённые findings/blockers запрещают merge. Исправления требуют review нового head; не редактируйте старый verdict для получения допуска.

## CI и границы

Все 17 проверок текущего маршрута обязательны, включая quality-группы, обе версии pipeline-e2e, clean-install, upgrade-path и macOS. Они берутся из последней PR workflow run точного head, затем из jobs её конкретной последней attempt, с полной пагинацией. API обязан явно связывать run с этим PR, head и текущим base; пустая связь не трактуется как подтверждение. Успех старого запуска, skipped/neutral/cancelled, отсутствие job, draft и неизвестная mergeability не дают допуска. Одинаковые имена другого workflow не заменяют требуемые. Legacy `quality/required-contexts.yaml` остаётся декларацией защиты ветки; он не заменяет этот маршрут. Fixture-тест сверяет политику с матрицами трёх текущих PR workflows; при изменении их состава обновляйте политику в том же PR.

Helper предназначен для этого маршрута Kit: нельзя объявлять его универсальным набором применимых CI дочернего проекта. Исполняйте доверенную версию helper и политики, а не непроверенный код PR. Локальный допуск не обеспечивает глобальную server-side protection. `--match-head-commit` защищает гонку head; изменения base/CI после финального чтения не атомарны, штатные правила GitHub продолжают действовать. Helper не выключает проверки и не меняет настройки при отказе GitHub/403.
