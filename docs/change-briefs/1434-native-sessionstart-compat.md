# #1434 — совместимость native SessionStart до модельного turn

## Актуализация 2026-11-06 перед завершением PR #1468

База проверки — `cdc8934090b16e09c75d053ec98181ff78472ee2`, включая #1493, #1494,
#1499, #1502 и #1503. Обычный `project-session run` теперь готовит исполнение
открытым агентом (`current-session`) и не запускает вложенный native provider.
Описанный ниже lifecycle blocker относится к явно выбранному `--autonomous`
и прямому вызову `codex-app-server`; он не запрещает обычную работу в Codex.

До изменения тестов: новый тест сохранения native blocker использует прежний
default `run` и потому проверяет другой режим. Исправление явно выбирает
`--autonomous`; существующая положительная проверка текущей сессии дополнительно
запрещает вызов native readiness. Это проверяет, что диагностика вложенного
provider не блокирует основной путь, а отказ вложенного запуска сохраняет
постановку и не создаёт process/claim. Runtime trust, разрешения и барьер до turn
не меняются. Исторические результаты ниже относятся к прежней базе; новые
результаты и CI проверяются отдельно перед слиянием.

- Результат: исправить подтверждённый handshake gap либо честно сохранить runtime blocker до модели.
- Источник: реальная активация II #1243/44981f32 с parent c4be2ba4, CLI0.147.0; оба exact hooks trusted, PreToolUse component deny, SessionStart ack отсутствует после thread/start и 3 секунд; 0 model calls.
- Пути: providers/codex_native.py, при необходимости bounded transport observation, native subprocess tests, актуальные runtime/provider ограничения. II checkout не изменяется.
- Инварианты: реальный native SessionStart ack текущей session/nonce/policy до turn; никакой симуляции, обхода trust/gates, моделей, credentials или разрешений. Код пока только локальный, без push/PR/merge/delivery.
- Гипотеза: локальная 0.147.0 schema содержит sessionStartSource startup/clear, adapter это поле не передаёт; отсутствие ack не доказывает сломанное trust. Проверить только metadata на прежнем разрешённом workspace, сохраняя определения hooks и settings.
- Failure modes: неверный source; async ack после ответа thread/start; чужой/старый ack; runtime откладывает hook до turn; hook/stream error. Ни один не разрешает модель без настоящего подтверждения.
- Доказательство: positive subprocess выполняет точную hook command только по реальному контракту запроса; fail-closed deferred/missing/foreign ack; side-effect trace доказывает порядок thread/start → native handler → accepted ack без turn; real metadata отдельно от fixtures.
- Не входит: смена runtime/trust paths, правки II checkout, живое исследование/квалификация и обещание всех сред. Если нет supported no-model lifecycle, следующий шаг отдельно согласовывается; не отправлять turn для диагностики.

## Подтверждённая причина и границы исправления

В #1462 неверно предполагалось, что `thread/start` исполнит SessionStart до ответа. Официальный tag `rust-v0.147.0` разрешён в immutable commit `be6e8eac029b183056b7e4402879f15d2c85f61b`:

- [thread_processor.rs:1282](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/app-server/src/request_processors/thread_processor.rs#L1282): `startup` — уже default; явное поле не меняет создание новой сессии.
- [session.rs:1300](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/session/session.rs#L1300): инициализация только ставит источник SessionStart в очередь.
- [turn.rs:150](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/session/turn.rs#L150): очередь исполняется в `run_turn` (строка233), после `run_pre_sampling_compact` (строка163). `turn/start` → ожидание ack → interrupt не гарантирует отсутствие модельного вызова.
- [hook_runtime.rs:103](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/hook_runtime.rs#L103): dispatch требует текущий TurnContext. В сгенерированной локальной ClientRequest schema0.147.0 из hook-методов есть только `hooks/list`, отдельного dispatch/dry-run нет.

[Документация app-server](https://learn.chatgpt.com/docs/app-server) определяет thread/start как создание thread, а turn/start — как запуск генерации; наличие доверенных определений не подтверждает вызов hook. [Контракт hooks](https://learn.chatgpt.com/docs/hooks) тоже не обещает SessionStart до возврата thread/start.

Повторная настоящая metadata-проба на ТОМ ЖЕ уже разрешённом workspace с `sessionStartSource: startup` дала no ack сразу/после3с, 0turn. SHA256 definitions `9b8f0d23eef021bc0e9daa9326e5047983972637a1fdb9128714e821f125a4f3`, wrapper `1f7ca66a313dd4c0edbc9cf4d272d37228839b168d6ed0df2d8dbc29db6f094b` до/после совпали. Выполнены только initialize/initialized/account-read/config-read/hooks-list/thread-start; no-turn guard стоит перед отправкой RPC. Context nonce диагностики обновлён в прежнем native workspace; ack автором не создавался, II checkout/trust/settings/credentials не менялись.

Полный trace и driver сохранены в `/tmp/ai-ops-1434-startup-source-probe-20261101.{json,py}`; прежняя проверка владельца — `/tmp/ii-sreda-kit-sessionstart-probe-20261101.json`. Они не переименованы в успешную живую приёмку. Source snapshot/tag и hashes — `/tmp/ai-ops-1434-codex-0147-source/`.

Локальный код исправляет ДИАГНОСТИКУ: после реально проверенного trust отсутствие ack получает `native-lifecycle-unconfirmed` и `hook_trust: confirmed`; сохраняются NOT_READY/pending/request/signals и отсутствие claim/turn/usage. Неподтверждённое trust не получает эту отметку. Регрессии используют явно синтетический pre-turn-capable subprocess для positive path и deferred-startup subprocess для отказа; ни один не выдаётся за CLI0.147.0. Определения/код native hooks, workspace identity и разрешения не меняются.

**Остаток:** безопасного запуска обязательного pipeline на0.147.0 в прежнем контракте нет. Нужен официальный runtime/API, подтверждающий lifecycle до модельного turn, либо отдельное согласованное решение о другом preflight-контракте с доказательством границы модельных вызовов. Простое разрешение ещё одного model trial не исправит этот handshake. Обновление CLI, изменение hooks/trust, turn/start и доставка не выполняются автоматически. #1434 остаётся OPEN.

## Локальная проверка

Python3.14.7: 99 targeted native/session PASS (32.64с), 142 provider/usage/response/pipeline/public-surface/architecture smoke PASS (14.09с), Ruff и семь применимых registry/layering/package/module/print/swallowed validators PASS. Прогоны последовательны через общий resource gate. Это локальная проверка диагностического патча, не CI/merge admission, не working compatibility и не живая командная приёмка.

## Коррекция после CI 06.11.2026

На head `66a213b1` pipeline-e2e Python 3.12/3.13 обнаружил превышение
потолка тестового файла: `test_project_session.py` вырос с 850 до 878 строк.
До изменения: две проверки границы current-session/native переносятся без
изменения assertions в отдельный `test_project_session_native_boundaries.py`.
Общие существующие fixtures/helpers переиспользуются по уже принятому в соседних
session-тестах способу; новые runtime-модули и зависимости не появляются.
Лимит не повышается, проверки не удаляются. После переноса требуется новый CI
и независимая проверка применимости review к итоговому head.
