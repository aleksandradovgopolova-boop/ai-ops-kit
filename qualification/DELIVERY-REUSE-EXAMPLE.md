# Пример проверки, выпуска и безопасного повтора

Запуск только во временном fixture-репозитории:

```bash
.venv/bin/python -m ai_ops_kit.devtools.delivery_reuse_probe \
  --output /tmp/delivery-reuse-measured.json
```

Проход использует существующий Tool Broker, receipts в `shared/lifecycle_store` и
координацию поставки в `delivery/record_delivery`:

1. Два настоящих subprocess проверяют синтаксис и собирают артефакт; каждый увеличивает свой счётчик.
2. Базовый проход трижды исполняет оба checks: draft → ready_for_review → release.
3. Такой же проход через receipts переиспользует совпадающие входы. Счётчики измеряют фактические исполнения.
4. Проверяемые checks → preflight поверхности agent → environment lock → durable intent → publish subprocess.
5. Runtime/public fixture-адаптеры читают опубликованную идентичность и проверяют содержимое артефакта.
6. Повтор выпуска делает reconciliation, publish второй раз не вызывается.

Замер 20.10.2026: из **6 запросов checks** базовый проход сделал **6 исполнений**, вариант с reuse —
**2 исполнения и 4 reuse**. Publish исполнился один раз; повтор завершился через reconciliation.
Данные и копии receipts: [2026-10-20.json](evidence/delivery-reuse/2026-10-20.json).
Точные измерения времени ускорения продуктов не проводились; это уменьшение числа запусков
на контролируемом примере, не обещание процентов ускорения. Fingerprinting тоже требует времени.

Граница примера: stdlib-only процессы запускаются с `-I -S`, внешние зависимости/среда в fixture
не меняются. CI и публичная среда продуктов не проверялись: `external_ci_verified=false`,
`external_public_verified=false`. Runtime/public здесь — файлы изолированного fixture, версия и SHA
синтетические. Пример не является доказательством публикации реального релиза. Ссылки
`embedded-receipt:*` указывают на сохранённые в отчёте копии receipts; временное дерево удаляется.

Регрессии отдельно проверяют lockfile/config/toolchain/env/flags/mode invalidation, новый процесс,
неполное evidence, все статусы, ранее пропущенный обязательный тест стадии, review при изменении
base/merge-base/diff, конкурентный deploy, смерть держателя lock, повреждённый intent и exit 0 с
неуспешной публичной приёмкой. См. `tests/unit/test_verification_receipts.py`,
`test_review_reuse.py`, `test_release_delivery.py`, `test_delivery_reuse_example.py`.

Адаптер Python Kit консервативно отказывает reuse при mutable editable dependency из другого
дерева, неизвестном sys.path или непроверяемой среде; это не повод объявлять complete=true вручную.
Продуктовые runner/CI/platform locks требуют собственного подключения и проверки. Дочки автоматически
не обновлялись.

## Файлы изменения

| Контур | Файлы |
|---|---|
| Выбор и исполнение проверок | `ai_ops_kit/gates/verification_tiers.py`, `ai_ops_kit/gates/evidence_collector.py`, `ai_ops_kit/shared/lifecycle_store.py`, `ai_ops_kit/devtools/impact_check_cli.py`, `scripts/check-fast.sh` |
| Review и CI | `ai_ops_kit/engine/review_branch.py`, `.github/workflows/docs.yml` |
| Выпуск | `ai_ops_kit/delivery/record_delivery.py`, `ai_ops_kit/gates/deploy_readiness.py`, `ai_ops_kit/devtools/release_delivery_cli.py` |
| Регрессии | `tests/unit/test_verification_receipts.py`, `test_review_reuse.py`, `test_release_delivery.py`, `test_release_delivery_cli.py`, `test_delivery_reuse_example.py`, `test_deploy_readiness.py`; JSON fixture `tests/fixtures/delivery_reuse/verified_release.json` |
| Пример и измерение | `ai_ops_kit/devtools/delivery_reuse_probe.py`, этот файл, `qualification/evidence/delivery-reuse/2026-10-20.json`, `qualification/evidence/delivery-reuse/full-current-python-2026-10-20.txt` |
| Инструкции и история | `AGENTS.md`, `docs/agent-guides/engineering-cycle.md`, `docs/agent-guides/pre-commit-checklist.md`, `docs/verification-impact-checks.md`, `workflows/release.md`, `commands/quality/ai-release-readiness.md`, `docs/change-briefs/README.md` (добавлена только ссылка на новый бриф), `docs/change-briefs/priority-delivery-reuse.md`, `newsfragments/priority-delivery-reuse.quality.md` |

Независимое review нашло четыре P1, исправленные отдельными регрессиями: неполный fingerprint
diff/merge-base, повтор после повреждения durable intent, пропуск смены executable mode и
credential URL в metadata. Изолированный pipeline e2e дополнительно проверяет, что запись
receipt не делает судимое worktree грязным. Предсуществующие изменения пользователя в рабочем
дереве в этот список не включены.

## Результат проверки реализации

`scripts/check-full.sh`, охват **full-current-python**: **8990 passed, 35 skipped, 2 warnings**,
CPython 3.14.7 / darwin, 1144.56 с (19:04). Ruff внутри этого прогона прошёл.
Лог: [full-current-python-2026-10-20.txt](evidence/delivery-reuse/full-current-python-2026-10-20.txt).
Это не compatibility-matrix и не результат живого GitHub CI.

Прогон выполнен в отдельной локальной Git-копии Kit с переносом рабочего дерева и тем же
интерпретатором. Исходный checkout запрещает запись в `.git`: его права не менялись. В копии
прошли в том числе upgrade-from-tags и session coordination, которым нужна собственная Git metadata.
После снимка изменены только пояснения в docstring/workflow и отчёт; исполняемая логика не менялась.

Дополнительно до этого прогона: 131 целевая проверка прошла; 24 проверки ранее недоступного
окружения прошли в изолированной копии; mypy — без ошибок в 23 файлах; layering — 19 пакетов,
89 рёбер, 0 циклов; потолки модулей/функций не повышены; мутационная проба
`release-prose-does-not-ship` — killed. Независимый reviewer повторил 74 целевые регрессии успешно.
Эти числа пересекаются с большим набором и не складываются в число уникальных тестов.

Два предупреждения прогона: устаревающая форма существующей class-scoped pytest fixture и
запас объёма поставки 4.8% до существующего потолка. Потолок выдержан, лимиты не расширялись.
SKIP остаются пропусками. Дополнительные suites ради координационных checkpoint не запускались.

## Checkout и handoff

Владелец реализации Kit — текущая авторская сессия; независимый reviewer не редактировал файлы.
Toplevel: `/Users/sasad/ai-ops-kit`; git-common-dir: `/Users/sasad/ai-ops-kit/.git`;
ветка: `codex/decision-evaluation-1247-1253`; HEAD: `07171005b1bc8bbc32d40bc5d106e90ddd8cebe2`;
VERSION: `4.9.3`. Изменения этой задачи не закоммичены и не отправлены. VERSION/CHANGELOG не менялись.
Совпадение cwd или hostId не является доказательством общей копии или общей версии Kit.

Согласованный контракт подключения: caller передаёт checkout identity, owner/task-scope,
digests входов/toolchain/config, статусы preflight отдельно по каналам и evidence
remote SHA/merge/runtime/public. Owner, receipts и локальный deploy coordinator реализованы;
универсальный caller-envelope для явных identity/task-scope ещё требует адаптера. Remote PR/merge
обрабатывает существующий `delivery.record_delivery.record_delivery_for_pr`; его живой внешний
вызов в этой работе не проверялся.

Для трёх продуктов нет подтверждения исполнения новых механизмов: child не обновлялись.
Подключение конкретных CI/connector/user-terminal/runtime/public и межмашинного platform lock
остаётся работой адаптеров. Обновление child требует совместимости и owner ACK; эту копию 4.9.3
нельзя считать эквивалентной заявленному pinned 4.11.1 другого checkout.

Новая сессия сохраняет denial и проверяет пригодность имеющихся evidence, а не запускает всё
заново из-за смены чата. Непроверяемый контекст (включая внешние mutable editable dependencies)
по-прежнему запрещает reuse. Неопределённый результат внешнего действия сначала сверяется;
смена сессии не разрешает повтор deploy или обход действующего чужого lock.

## Интеграция с актуальным Kit4.11.1

21.10.2026 штатные Git read/clone подтвердили main `3cd01d35ed87308d8eb0b929d0048840555111b8`;
интеграция ведётся в отдельном checkout `/private/tmp/ai-ops-kit-main-integration-20261021`.
Перенесены только task delta и narrow patch; VERSION остаётся4.11.1. Сохранены профили main,
fail-closed intent, premerge/17CI и новый durable I/O. Receipts выделены внутри foundation/shared.
На этой базе адресный набор112проверок прошёл за10.24с, включая P1nested lock на настоящем
маленьком fixture-корпусе. Это targeted, не новый широкий/full suite и не доказательство CI/публикации.
Старый BLOCKED остаётся без изменения; собственные outputs привязываются к post-run fingerprint.
Shared-host wrapper не установлен в product CI. Product pins/security/credentials не менялись.
