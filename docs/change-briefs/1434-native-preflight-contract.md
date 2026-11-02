# #1434 — проект двухфазного native preflight (НЕ АКТИВЕН)

- Результат: reviewable контракт конфигурации, runtime attestation и запрета инструментов; выбор варианта до реализации и согласия на live.
- Источник: локальный diagnostic commit dca2fe0e, официальные0.147.0 schemas/source и реальные metadata-only noack traces; новый проект не меняет этот commit.
- Пути: только этот документ, сценарии fixtures/1434-native-preflight-scenarios.yaml и append-only индексы/фрагмент; runtime код/реестры/security policy не меняются.
- Инварианты: configuration-ready не равно runtime-confirmed; нет разрешения инструментов при unknown/failed attestation; отказ handler/timeout/cancel не превращается вallow; модельная попытка учитывается с отправкиturn независимо от исхода.
- Failure modes: hook до/после turn response; чужой/устаревший/частичный ack; hook crash/timeout/missing handler; cancel/EOF/process death; нарушение запрета инструмента/унаследованный MCP/plugin/approval.
- Доказательство: pinned source/API trace, матрица сценариев с запретами side effects и независимый review проекта; fixtures не являются native runtime квалификацией.
- Не входит: изменение runtime security contract, turn/model/paid вызовы, trust/credentials, публикация, доставка или правки II checkout.

## Решение для согласования

Разделить **«настройки проверены»**, **«runtime действительно вызвал hook»** и **«результат принят»**. Разрешение отправить один модельный turn не означает разрешения инструментов. Внутренняя роль остаётся только текстовой НА ВСЁМ протяжении; после attestation инструменты ей тоже не выдаются. Файлы и действия продукта применяет существующий control plane кита по своим gates.

Выбран минимальный безопасный контракт: два этапа preflight с **независимым запретом исполнения всех native tools на стороне runtime**. Он должен действовать до первого turn, до handler и независимо от работоспособности hooks. Если такого запрета нет или его состояние нельзя проверить, второй этап не начинается. Это требование к будущей реализации, а не существующая настройка Codex0.147.0.

**На проверенном public API0.147.0 гарантию блокировки tools при crash/timeout hook дать нельзя.** Поэтому для этой версии проект имеет NO-GO на исполнение. Новый документ не разрешает удалить старый guard, заменить его trust-флагом или начать live. Два статуса preflight без независимого барьера сами по себе проблему не решают.

Нужно согласовать именно этот контракт и инженерный поиск/выбор официального runtime с таким барьером. Если остаёмся на0.147.0, требуется upstream изменение перед dispatcher; собственный fork и его сопровождение — отдельное архитектурное решение, здесь не предлагается как готовое исправление. Согласие лишь на ещё один модельный запуск техническую границу не устраняет.

## Что установлено об официальном API

Опорная версия: tag `rust-v0.147.0`, immutable source `be6e8eac029b183056b7e4402879f15d2c85f61b`; локальная schema получена от CLI0.147.0. Текущая документация может описывать более новые поля, поэтому ей не приписываются отсутствующие поля этой schema.

| Факт | Последствие |
|---|---|
| [SessionStart ставится в очередь](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/session/session.rs#L1300), dispatch — в [run_turn:233](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/session/turn.rs#L233), после pre-sampling compaction | thread/start и hooks/list не подтверждают исполнение. Ожидание после thread/start не запускает очередь. |
| hooks/list сообщает определения/trust; [hook/started и hook/completed](https://learn.chatgpt.com/docs/app-server) — notifications | Их надо связать с текущим thread/turn/run; это наблюдение, а не клиентское разрешение handler. В ClientRequest0.147 есть hooks/list, нет отдельного hook dispatch/dry-run. |
| [pre_tool_use.rs:202–214](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/hooks/src/events/pre_tool_use.rs#L202): при run_result.error статус Failed, should_block остаётся false; аналогично [serialization failure:313](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/hooks/src/events/pre_tool_use.rs#L313) | Ошибка запуска Python, kill/timeout до обработчика и ошибка сериализации не покрыты его try/except. Рабочий deny handler недостаточен как единственная защита. |
| [hook_runtime:196](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/hook_runtime.rs#L196) допускает Continue; [registry:546](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/tools/registry.rs#L546) затем вызывает handler | Отмена по notification может опоздать: до side effect нет обязательного ожидания ответа клиента. Не каждый handler обязан иметь pre_tool_use_payload. |
| В [ToolsToml/ToolRegistryConfigToml](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/config.schema.json) нет общего deny-all; exposure и registry различаются, [legacy shell остаётся Hidden](https://github.com/openai/codex/blob/be6e8eac029b183056b7e4402879f15d2c85f61b/codex-rs/core/src/tools/spec_plan.rs#L909) | Отключение shell/MCP/web и пустой видимый список tools не доказывают отказ всех handler, включая скрытые и новые. |
| [PreToolUse deny/exit2](https://learn.chatgpt.com/docs/hooks), sandbox readOnly и approvals — разные механизмы | Deny — дополнительная защита, когда handler отработал. Граница readOnly — ограничение записи по native policy, а не запрет всех чтений/tools. On-request не создаёт обязательный запрос на каждую операцию. |

Startup websocket prewarm может отправить `generate=false` и native base instructions до обычного turn. Ноль turn/start не означает ноль сети. Более позднее «успешно отменили» не доказывает ноль генераций или ноль действий.

## Сравнение вариантов

| Вариант | Реализуемость / изменение | Решение |
|---|---|---|
| Прежний pre-turn ack, explicit startup или более долгий wait | В0.147 очередь всё равно ждёт run_turn; API dispatch не найден | Не восстанавливает работу. Текущий guard сохраняется до замены. |
| Configuration-ready → turn → ack; один PreToolUse deny | Небольшая правка adapter, но crash/timeout handler оставляет непокрытое исполнение | Отвергнут: требуемой гарантии нет. |
| SessionStart/UserPromptSubmit делает stop; клиент ждёт и отменяет | Новый hook/trust; событие внутри turn, до него возможна compaction; failure и гонка cancel остаются | Не считается no-model preflight и не заменяет независимый запрет tools. |
| ReadOnly, untrusted/on-request, выключенные features; либо новый контейнер | Уменьшает последствия, не запрещает все native invocations; новый контейнер/auth потребуют иной scope | Дополнительные ограничения, не самостоятельное решение. |
| Два этапа + проверенный runtime deny-all перед handler | Минимальный сохраняющий границу контракт; нужен supported механизм/версия, которых у проверенного0.147 API нет | **Выбран условно**: специфицируем сейчас, внедрение и live только после доказательства барьера. |
| Собственный tool loop / API-key provider / подмена ack | Другой движок, новые доступы/расходы либо ложное доказательство | Вне scope; не предлагается как обход. |

## Этап A — проверка конфигурации без содержательного turn

**A0, строго offline:** читать только проектные файлы, version/source/policy hashes, разрешённые определения и сохранённую trust-конфигурацию; не исполнять handlers, не запускать app-server и не считать сохранённый trust доказательством фактического dispatch. Отсутствующие/неоднозначные данные дают unknown/blocked, а не ready.

**A1, native metadata:** account/config/hooks readback выполняется только в уже разрешённой среде и не называется offline или гарантией нулевой сети. Не создавать thread до проверки источников startup context и разрешения его передачи: thread/start способен вызвать prewarm. Перед любым turn нужен актуальный native fence receipt; его начальная policy должна быть установлена до подготовки thread либо атомарно при его создании, до возможного handler. Проект не утверждает, что такой API существует в0.147.0.

1. Проверить фактический project root/source/policy, CLI/protocol revision и frozen payload. Восстановленная/сменившая проект сессия проходит сверку binding заново, а не наследует PASS другой ветки.
2. Подтвердить существующий ChatGPT account без refresh/login, forced ChatGPT/provider, каталог и точную модель. Неизвестная модель/подмена — отказ, без fallback.
3. Прочитать effective config. Выключение MCP должно быть проверено по каждому фактическому server после перезапуска; пустая таблица не удаляет inherited entries. Проверить apps/plugins/skills/memory/browser/code-mode и все источники инструкций; неизвестная поверхность/контекст — отказ до отправки данных.
4. Проверить точный project trust и ровно разрешённые синхронные command hooks: sourcePath, definitions/handler code/command hash, matcher, enabled, trust, timeout. Другие user/plugin/managed hooks не игнорируются: должны быть отдельно разрешены и проверены либо выключены scoped механизмом. Не менять глобальные settings автоматически.
5. Получить проверяемый **runtime tool fence receipt**, связанный с текущим process/thread/config digest и полным registry: все native/local/hosted/MCP/app/dynamic/code-mode/unknown tools запрещены перед handler, в том числе при hook failure/cancel. Одного поля, которое выставил сам kit, недостаточно. Отсутствует receipt или supported enforcement — `blocked/tool-fence-unavailable`, **0 turn**.
6. Сохранить configuration receipt в существующем lifecycle evidence. Это не runtime attestation, не успешный WorkItem и не новое значение старого ready=true. Текущий compatibility режим продолжает NOT_READY.

Порт `runtime_tool_fence` — требование этой спецификации, **не реальный RPC/флаг0.147.0**. Ни `toolPolicy=deny-all`, ни другой выдуманный параметр в API не отправляется. Кандидат должен доказать и отсутствие model-visible tools, и запрет dispatch зарегистрированных/скрытых/неизвестных tools. Планируемая реализация не подменяет это изменением только prompts.

## Этап B — подтверждение реального runtime

Допуск: configuration receipt актуален, native hard fence уже действует, payload/model и лимит отдельно согласованы. Это начало модельной попытки; «runtime не подтвердился» не возвращает израсходованный бюджет в ноль.

| Состояние | Разрешено | Запрещено |
|---|---|---|
| saved / config_unknown | Сохранить запрос, прочитать metadata | turn, tools, успешный результат |
| config_validated / fence_missing | Показать конкретный blocker | turn, tools, декларация полного ready |
| config_validated / fence_verified / consent_missing | Сохранить подготовку | turn, tools |
| attempt_reserved / awaiting_attestation | Единственная отправка turn, наблюдение событий, cancel | любые tools; принятие текста; повторный turn |
| runtime_attested | Получить текст роли и usage при неизменном fence | любые tools, product actions самой роли |
| completed_unverified | Контрактная проверка результата/evidence/gates | accepted без проверки |
| accepted | Отдать проверенный результат; control plane применяет лишь разрешённые своим процессом действия | передача native tools роли задним числом |
| failed / cancelled / unknown | Сохранить исход/trace/usage-unknown, завершить свой process group | принятие результата, автоматический retry |

Перед отправкой: exclusive workspace/attempt lock; повторная проверка task/request binding и source/config; очистка старого ack только в собственном isolated workspace, новый nonce и hashes; атомарная запись attempt/бюджетного резерва в существующий журнал. Timeout metadata≤15с, attestation≤5с внутри общего turn deadline≤30с. Нельзя сначала проверить старую задачу, а после долгой подготовки исполнить новый prompt под прежним receipt.

С отправки turn/start попытка считается attempted, даже если response/turn id потерялся. Если события пришли раньше ответа RPC, ограниченно буферизовать и затем связать их с его actual turn id; неизвестность/переполнение — отказ. `hook/started` не является PASS. Нужны matching `hook/completed` с успешным статусом, разрешённый sourcePath/run identity и настоящий ack из неизменного handler с текущими nonce/policy/prompt/session; все доказательства должны относиться к одному fresh thread/turn. Поддельный файл/прямой запуск handler без native event не подходит. При отсутствии у выбранного runtime достаточной связи событий — блокировка, а не догадка.

Ack и completion проверяются вместе; partial write/невалидный JSON/чужой nonce/run/session, второй неоднозначный вызов, failed/blocked/timeout hook — отказ. Канал ack не считается криптографически защищённым от злонамеренного владельца того же UID: область гарантии — корректный доверенный runtime/host и отказы, stale/foreign evidence и гонки; компрометация владельца/OS вне этого локального контракта.

Клиент не разблокирует tools после ack. Native hard fence остаётся deny-all до завершения; PreToolUse deny служит дополнительной диагностикой. Любая попытка инструмента/approval/неожиданный item — failed, даже если native fence действительно предотвратил side effect. Инструментальный отказ не выдаётся за успешную текстовую стадию.

## Ошибки и доказательства отсутствия действий

- **Hook crash, отсутствующий executable, timeout, malformed output, broken pipe:** native fence продолжает запрещать handler независимо от callback. Adapter прекращает стадию, запрашивает interrupt и закрывает собственный process group. Успех interrupt — только lifecycle evidence, не доказательство отсутствия side effect.
- **Cancel:** до отправки turn — попытка не начата; после — attempted/cancelled или unknown с сохранённым ledger. Поздний ack/ответ уже отменённой попытки не принимается. Disconnect/EOF не запускают повтор автоматически.
- **Потеря fence/config drift:** результат отвергается; нельзя считать доказанным предотвращение уже возможных действий. Для такого runtime/прогона safety qualification FAIL. Внедрение блокируется до устранения причины.
- **Side-effect proof:** в отдельной fixture-среде заранее создать безопасный marker target и инструмент, который записал бы marker при настоящем handler execution. Положительный контроль вне deny-профиля доказывает, что handler реально способен записать marker; под fence при missing/crashed/timed-out hook marker отсутствует, а native dispatch receipt фиксирует deny ДО handler. Один несуществующий marker без положительного контроля недостаточен. Никаких продуктовых файлов.
- **Acceptance:** ledger попытки, metadata/fence receipts, actual hook event+ack binding, role text, usage/outcome, cleanup и штатные gates. Потерянное/чужое/старое evidence — не PASS. Fixtures/формальная модель не заменяют real native proof.

## Объём будущей реализации и проверок

Нужны: (1) supported native deny-all enforcement и readback/provenance; (2) раздельные configuration/runtime/result receipts в существующем lifecycle; (3) phase-aware adapter, bounded event buffering/timeout/cancel и учёт attempted; (4) точная привязка hook ack к native event; (5) scoped validation inherited hooks/instructions/tools. WorkItem/run-report/gates не переписываются, новый top-level пакет и собственный agent tool loop не нужны. Воздействие на public/installer поверхности оценивается по готовому diff; версия/доставка/новый trust не обещаются заранее.

Тестовые сценарии — [fixtures/1434-native-preflight-scenarios.yaml](fixtures/1434-native-preflight-scenarios.yaml). Это данные проекта контракта, не реализация dispatcher и не исполняемые инструкции. Отдельно требуются deterministic provider/session/process regressions, независимый review кода, CI точного head/base, затем живой native контроль. До этого registry status не повышается, current guard не снимается, #1434 остаётся OPEN.

## Отдельный live scope для последующего согласия

**Сейчас NO-GO:** hard fence0.147.0 не подтверждён. Этот раздел не является разрешением или готовой командой запуска.

После реализации и review: один fresh ephemeral thread, максимум **1 turn/start**, без retry/continuation; один синтетический ответ `KIT_NATIVE_OK`. Ожидается одна завершённая генерация; **жёсткий предел внутренних model/HTTP/prewarm/retry/compaction requests не подтверждён**. Если лимит человека — строго1 model request, сначала нужен native limiter/доказательство; согласие на1turn не переименовывается в1call. Если согласованный предел бюджета нельзя обеспечить, первая попытка не начинается.

Provider — официальный local codex app-server/openai, auth — уже существующий ChatGPT account Саши, forced ChatGPT login; каталог и явно выбранная модель сверяются до consent, без подмены и API-key/Claude fallback. API env-переменные не передаются; никаких новых auth, ключей, account или paid API. Подписочные лимиты не объявляются без проверки.

Пользовательский текст: `Синтетическая проверка. Ответь ровно KIT_NATIVE_OK. Не используй инструменты и не читай файлы.` Плюс заранее замороженные base/role instructions и native protocol metadata. Архив Марка/исходники ИИ-Среды не отправляются. Native startup prewarm способен отправить base instructions/tools metadata до обычного turn: необходим полный allowlist источников контекста; неизвестный inherited context — остановка, а не обещание «ушла только одна строка».

Workspace — только прежний разрешённый `/private/var/folders/h1/3_z8zfj15yggh5pnq51gdk8w0000gn/T/ai-ops-codex-text-eaab66d1f81508e00b43ea71`, если path/definitions/wrapper/code hashes действительно прежние и новая реализация совместима. Исходные SHA256 definitions `9b8f0d23eef021bc0e9daa9326e5047983972637a1fdb9128714e821f125a4f3`, wrapper `1f7ca66a313dd4c0edbc9cf4d272d37228839b168d6ed0df2d8dbc29db6f094b`. Нельзя использовать старое согласие для нового пути/handler. Если меняется hook/identity/права — подготовить конкретный diff и отдельное разрешение; без него NO-GO. Product checkout не cwd и не write target. Native controls/logs в isolated workspace и личные штатные cache/logs runtime допустимы по согласованному описанию; никаких продуктовых действий.

Действия роли — только текст, native tools **0** до и после attestation; sandbox readOnly/networkAccess=false, обычные approvals без авторазрешений — дополнительные ограничения. Общий deadline30с, attestation5с, metadata15с; stop на первом hook error/timeout/cancel, foreign event/ack, tool/approval, drift или неизвестном outcome. Записать фактические attempts/usage и очистку; unavailable/unknown не заменять нулём.

Deadline ограничивает локальное ожидание и процесс; сам по себе он не доказывает мгновенную остановку удалённой генерации или жёсткий предел расходов. Это отдельное ограничение бюджета, которое надо согласовать честно, а не скрыть словом «одна попытка».

Эта одиночная проверка не закрывает #1434. Нужен отдельный положительный/отрицательный командный опыт Саши/Codex и Марка/Claude на одной итоговой ревизии, без повторного исследования Марку. RESEARCH содержит8 стадий, и его бюджет/provider routing не равен бюджету одного native turn.

## Проверка самого проекта

Первоначальный локальный срез a9628982 на базе отдельного dca2fe0e: 22 синтетических сценария разобраны и проверены на целостность/непротиворечивость ожидаемых статусов; это не исполнение native guards. При потере fence отсутствие side effects помечено unknown/not_proven, а не недоказанным нулём. Короткий public-surface smoke:20 PASS/2.08с на Python3.14.7. Изменения runtime/security/config/registry/installer относительно той базы отсутствовали. Native startup, turn, модели, trust и запись II checkout для этого проекта не выполнялись. На том этапе CI/публикация не запускались.

При draft-публикации main-based проекции aa06d2ce на базе c4be2ba4 CI обеих версий Python обнаружил неназванную границу слова sandbox в таблице. Уточнено ограничение readOnly рядом с термином; сам safety-валидатор, policy и runtime не менялись. Исходные локальные проверки выше сохранены как исторический срез; результаты публикационного CI учитываются отдельно по точному head.
