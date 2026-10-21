# Workflow: release

```text
Release readiness
→ dependency check
→ migration readiness
→ communication
→ deployment
→ smoke checks
→ product/technical monitoring
→ go/no-go confirmation
→ release notes
```

## Исполнение без повторной работы

Один владелец ведёт конкретный выпуск до наблюдаемой опубликованной версии. Независимые
части разработки могут выполняться параллельно. `delivery/record_delivery.deliver` и CLI
`python3 -m ai_ops_kit.devtools.release_delivery_cli --contract <contract.json> --owner <id>`
исполняют контракт через текущий Tool Broker. Команды доступа/приёмки задаёт доверенный адаптер,
а не эвристика кита. Секреты в контракт не записываются; берутся из разрешённой среды адаптера.

Порядок: environment lock → безопасные read preflight → проверка пригодности имеющихся receipts
и обязательного CI → durable intent → deploy → независимые runtime/public observations → DeployRecord.
Lock охватывает preflight, проверки и действие одного владельца.
CLI не подтверждает доступ connector/user_terminal по доступу agent: эти поверхности здесь
BLOCKED. Ошибка 404 фиксируется кодом наблюдения, без вывода о настройках организации.

`expected` содержит version, полный sha, artifact_digest (`sha256:…`) и environment; CLI сверяет
digest с файлом `artifact`, SHA с чистым исходником и версию с VERSION, если он есть.
`checks` — актуальные результаты обязательных checks с source и
inputs_digest. Локальный receipt проверяется через content context; observer CI сверяет SHA
и должен читать требуемые статусы платформы. `runtime_command` / `public_command` возвращают
JSON с `status`, `source` и всеми четырьмя полями идентичности. Public PASS означает, что адаптер
проверил обязательные сценарии; простого HTTP 200 недостаточно. Kit не угадывает эти сценарии.

`preflight` — список `{surface, operation, command, required}`; команда возвращает JSON
`{status, code}`. В CLI только agent доступен. `checks` содержит `{name, receipt, command}`
для локального evidence либо `{name, command}` для read-only observer внешнего CI. Команда
CI-observer возвращает `{name, status, source, inputs_digest, sha}`. Для Kit обязательный набор
читается из существующего `quality/required-contexts.yaml`: каждый контекст требует CI PASS
для точного SHA, local receipt и CI SKIP его не заменяют. `deploy_command` исполняется
через тот же broker; переопределения approvals/запретов для него нет.

Запись `.ai/runtime/deploy/*.json` содержит владельца, точную ожидаемую и наблюдаемую идентичность,
результаты checks и preflight, время, код deploy и `recovery: {procedure, automatic_rollback: false}`.
Exit 0 не определяет успех: несовпадение идентичности/обязательный FAIL → FAIL, недоступная
приёмка → BLOCKED. Источники очищаются от URL credentials и query; сырой stdout не сохраняется.
`deploy_readiness` повышает зрелость только по записи, прошедшей `deploy_readiness.confirmation`.

POSIX lock общий для checkout и его worktree. Он не удаляется и не снимается по TTL; после смерти
процесса освобождается ОС. Pending intent сохраняет владельца: другой владелец/артефакт блокируется.
После таймаута/crash повтор сначала наблюдает runtime/public, никогда не повторяет deploy
автоматически. Повреждённый intent блокирует действие до ручного восстановления достоверного
состояния. Автоматического rollback нет; описание recovery не является проверенным контрактом отката.

Граница: это локальный coordinator и интерфейс адаптеров. Он не сериализует разные машины/клоны;
для них требуется lock целевой платформы. Реальные CI/deploy/приёмка продуктов в этой работе не
подключались и не проверялись. Контракт должен явно требовать необходимый CI и platform lock;
неизвестный внешний результат нельзя заменять локальным PASS. Изменения в Kit не означают
внедрения в дочках. Воспроизводимый fixture-пример и замер: `qualification/DELIVERY-REUSE-EXAMPLE.md`.

Контур Kit4.11.1 сохраняет штатный `devtools.premerge` с `quality/premerge-checks.json`
(17 exact-head/base checks и независимый review) и stock release.yml с actual mutation gate.
Generic release_delivery_cli не подменяет этот маршрут и не является обходом публикационных ворот.
Host-slot `/tmp/ai-ops-kit-heavy.lock` относится к тяжёлым cooperating local/CI процессам,
не заменяет environment/platform deploy lock. Product self-hosted CI требует явного подключения.
Потерянный inherited fd даёт быстрый BLOCKED; передача действительного fd через subprocess
сохраняет текущий lock. Collection-only не исполняет тесты и не объявляет широкий PASS.
