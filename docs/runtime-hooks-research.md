# Runtime hooks / Mods — исследование #1255

Проверено 2026-10-06. **Research verdict (REASONING): prototype** для небольшого адаптера
передачи контекста и аудита, **watch** для Mods и обязательного enforcement через hooks.
Это рекомендация AI, не HUMAN_DECISION владельца и не разрешение production-проводки.

Кит уже передаёт объявленные skills в generic orchestrator и сам проверяет обязательные gates.
Полезная следующая гипотеза — получать подтверждаемый контекст и события из native runtime,
где сегодня адаптер преимущественно генерирует команды. Выгода от нового адаптера ещё не
измерена. Собственный tool loop и Claude-specific core не нужны.

## Что проверено, а что только описано

- Прочитаны первичные документы Anthropic, OpenAI и Gemini CLI. Опубликованные Mods types
  и пример aitmpl привязаны к commit SHA; метаданные — в qualification/runtime-hooks.
- Локально: `codex-cli 0.147.0`, feature `hooks` имеет stable/true. Без inference сгенерирована
  обычная app-server schema; сохранены хеши, имена методов и поля, не весь upstream исходник.
- Локально: Claude Code **2.1.283**. В актуальной документации Mods включены по умолчанию с
  **2.1.287** в терминале и **2.1.286** в Desktop. Здесь Mods не загружались, Claude не обновлялся.
  Успешных live hooks/SDK/Mods прогонов этот отчёт не заявляет.
- Никакие hooks пользователя не включались, SDK/моды не устанавливались; model turns — 0.

## Поверхности и зрелость

**Classic Claude hooks** — отдельный settings/plugin механизм: JSON stdin/stdout для внешних
обработчиков, event-specific control. `PreToolUse` может отказать; `PostToolUse` уже после
эффекта. У command/http/mcp_tool timeout на PreToolUse обычно не останавливает инструмент;
невалидный ответ или несуществующий скрипт тоже могут оставить действие разрешённым.
Unix exit 1 нельзя переносить как block; для command PreToolUse блокирующий код — 2.
Другие события имеют другие правила. Это документированная поверхность с версионными
оговорками, не обещание общего fail-closed. [Claude hooks reference](https://code.claude.com/docs/en/hooks).

**Agent SDK callbacks** — ещё одна поверхность, не Mods: Python/TypeScript callback hooks,
с разным набором событий. Документация отдельно описывает блокировку PreToolUse при timeout
SDK callback. Этот результат нельзя приписывать command hooks. Подключение SDK потребовало бы
отдельного решения о зависимости; в этой работе его нет.
[SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks).

**Claude function hooks / Mods** — теперь официально документированы. Это plugin с
`register(on, options)`, обработчиками внутри процесса и цепочкой `next`; нельзя считать всю
поверхность прежним недокументированным экспериментом. Минимальная версия и выключатели
имеют значение. [Mods overview](https://code.claude.com/docs/en/plugins/mods/overview).

Названия событий, layout, модель/effort в `turn.step` и `agent.spawn`, а также prompt API
даны в [Mods reference](https://code.claude.com/docs/en/plugins/mods/reference).
Runtime-specific `.claude-plugin`, `$`, tiers, UI и async-generator stream не входят в
нейтральный контракт кита. Public documentation не означает бессрочную SemVer гарантию.
Опубликованные types могут отставать от binary: перед prototype нужен `/plugin-types` для
именно используемой версии.

Mod без `.catch` при ошибке/timeout может быть пропущен; событие продолжится. Обработчик
`.catch` может вернуть deny, но сам ограничен временем. Managed и user hooks стоят на
разных местах цепочки; нельзя переносить user mod как обязательную административную policy.
[Events/failures](https://code.claude.com/docs/en/plugins/mods/events).
Опубликованный [sec-default](https://github.com/anthropics/claude-code/blob/8e60c4cac989c0e0cc6d2c49407a5c67f5a4a8e6/mods/sec-default/README.md)
сохраняет управляемые policy поверх user tier; это Claude-specific композиция, а не универсальная
защита любой установки. Она не доказывает безопасность нашего ещё не написанного адаптера.

**Codex hooks** — документированная, локально включённая stable feature; поддержка различается
по orchestration/execution surface. Есть context/lifecycle и pre/post-tool события, review/trust
hooks. Hosted tools и некоторые специальные пути не имеют общего tool hook; `write_stdin`
не повторяет PreToolUse для уже разрешённой сессии. Некоторые ошибки/timeout/malformed и
неподдерживаемые decision поля приводят к hook failure при продолжении инструмента.
Поэтому coverage частичный, hooks не полная граница enforcement или аудит всех эффектов.
[Official OpenAI documentation: Hooks](https://learn.chatgpt.com/docs/hooks).

**Codex app-server** — транспорт управления внешним runtime, не mod API: JSON-RPC, turn/item
события, context/skill inputs, model/effort при старте turn и отдельные approval requests.
Документация отделяет stable subset от experimental opt-in: например, dynamic tools требуют
experimentalApi. Сам локальный генератор помечен experimental в CLI help; обычная schema
без `--experimental` — свидетельство формы сообщений этой сборки, не end-to-end enforcement.
Approval request зависит от native policy и не появляется для каждого возможного действия.
[Official OpenAI documentation: App Server](https://learn.chatgpt.com/docs/app-server).

**Gemini CLI** — публичные command hooks BeforeTool/AfterTool и BeforeModel/AfterModel.
Они показывают переносимость понятий, но не общую семантику. Timeout в settings задаётся
в миллисекундах, в отличие от секунд classic Claude/Codex; JSON pollution может дать Allow,
а обычная ошибка остаётся warning. Локальный binary и interception не квалифицированы.
[Gemini hooks](https://geminicli.com/docs/hooks/),
[reference](https://geminicli.com/docs/hooks/reference/).

**aitmpl** — каталог и пример plugin layout, не runtime-neutral policy substrate. Проверен
[исходник мода](https://github.com/davila7/claude-code-templates/blob/375af9018a40e330e81542f59054daaa088c21aa/cli-tool/components/mods/productivity/aitmpl/hooks/register.tsx):
session/command/UI/turn handlers; UI-инсталляция вызывает внешний процесс. Его установка
не нужна киту. В [старых release notes](https://github.com/davila7/claude-code-templates/releases)
сохранились experimental flag/описания прежних версий; приоритет для текущего статуса —
актуальные документы Anthropic и types используемого binary, не историческая запись каталога.

## Сопоставление lifecycle points

Это документированный mapping, не таблица verified capabilities кита. Названия Claude Mods
проверены также по pinned types; остальное — по ссылкам выше. Различия смысла сохраняются.

| Понятие кита | Claude classic / SDK | Claude Mods | Codex hooks / app-server | Gemini |
|---|---|---|---|---|
| Граница turn/step | prompt/stop, tool batch; не общий per-model step | turn.start/step/complete | turn/item stream; не паритет turn.step | BeforeModel/AfterModel |
| Subagent lifecycle | SubagentStart/Stop; Start не общий запрет spawn | agent.spawn/offer | SubagentStart/Stop, collaboration items; граница запрета отдельно | В этом исследовании не подтверждено |
| До/после действия | PreToolUse/PostToolUse | tool.call, tool.check, next result | Pre/PostToolUse и item events, partial coverage | BeforeTool/AfterTool |
| Передача контекста | SessionStart/UserPromptSubmit, skills отдельно | prompt.submit/context/compose, skill.prompt | context hooks или skill input на turn/start | hook context, BeforeAgent |
| Модель/effort | ModelSwitch; без общего per-step effort | turn.step, model при spawn | model/effort при turn/start; только поддержанное моделью | BeforeModel; effort не подтверждён |
| Policy interception | Event-specific deny; timeout зависит от family | deny/check, tiers, catch | supported deny; errors могут fail open | deny/exit 2; errors могут fail open |
| Аудит | Hook payload и result | События и результаты цепочки | Items/IDs и callbacks; не все эффекты | События и result |

## Минимальный адаптер: проект, не новая capability

Ниже — внутренний проект протокола. Исполняемые классы, stable schema или runtime capabilities
не добавляются; сначала нужен измеренный prototype в существующем домене.

1. **describe**: runtime/version/surface, transport, event schema version, список поддержанных
   event/action kinds, фазу before/after, coverage и failure behavior для каждого вида.
   Разделять documented/observed/verified. Unknown не становится supported. Stable feature
   не даёт права объявить весь adapter verified.
2. **deliver_context**: stage/owner/review_mode, ID и хеши объявленных skills, scope/context hash.
   ACK связывать с фактически отправленным runtime input. Сам ACK не доказывает, что модель
   выполнила инструкцию. Missing required skill блокирует стадию; внешнее разрешение навыка
   сохраняет текущие правила #1251, не заменяется каталогом mod.
3. **observe**: envelope с run/stage и native session/turn/call/parent IDs, event kind,
   before/after phase, локальным sequence и временем получения, original payload hash,
   runtime version и redacted artifact reference. Не выдумывать отсутствующий call ID или
   общий порядок разных потоков. Разрыв/неизвестная schema дают degraded и явный gap.
4. **authorize**: только для отдельно qualified before-action path. Exact action + arguments
   hash + scope/revision + lease/deadline; allow/deny/defer_to_native. Native deny нельзя
   ослабить. Human approval привязано к этому действию, не к AI explanation.
   Для обязательной policy unknown/error/timeout не дают разрешение. Если transport не
   способен обеспечить это, sensitive действия остаются у broker либо недоступны.
5. **receipt**: correlation к запросу, native outcome/exit/result hash и отдельная проверка
   side effect. Событие «получен runtime result» можно записать как факт получения; объявленный
   tool success не доказывает изменение файла, прохождение тестов или HUMAN_DECISION.

Общее budget/correlation/context понятие переносимо; exit codes, callback signatures,
regex matcher, native role names, trust sources, tiers и UI остаются в конкретном adapter.
Это не DecisionProvider #1248: тот предлагает ограниченный выбор, а разрешение действия
и доказательства принадлежат policy/исполнению. Semantic decision не снимает mandatory floor.

## Почему не перенести mandatory checks в hooks

В текущем коде `ai_ops_kit/engine/tool_broker.py` и `ai_ops_kit/gates/gate_executor.py` уже владеют соответствующими
проверками; `ai_ops_kit/shared/generate_runtime.py` генерирует команды, а не устанавливает interception.
Наблюдение или модификация prompt не добавляет нового доказанного enforcement. Gap coverage,
отключённый/недоверенный hook, продолжение после error и ввод через уже разрешённый процесс
нельзя исправить одним общим переводом event names.

**Вывод исследования:** prototype контекста и аудита может дополнить существующий native
runtime adapter. Требование mandatory fail-closed пока исполняется существующим broker/gates,
а native ограничения доступа и approval сохраняют свою роль. Hooks не авторизуют обход, не заменяют writer≠judge,
не добавляют tool loop и не становятся evidence сами по себе.

## Что должно доказать будущее prototype

Один declared-skill stage и одно простое локальное действие в изолированном репозитории,
с одинаковым контрактом для двух runtime adapters. Сначала offline replay, затем отдельный
live прогон после выбора версии и подтверждённого доступа. Здесь prototype не реализован.

- Positive: фактический runtime input содержит выбранного owner, обязательные skills и их
  хеши; native события связываются с одной стадией без пропусков/дублированных receipt.
- Fail-closed: missing skill, unknown schema, отключённый/untrusted hook, timeout/error,
  смена аргументов после approval и gap в protected before-action path не дают разрешение.
  Если native runtime продолжил действие, это failure квалификации, не зелёный fallback.
- Side-effect proof: инструмент действительно попытался изменить fixture; отказ подтверждается
  отсутствием эффекта, успешное действие — реальным diff/файлом, сопоставленным с receipt.
- Измерить context footprint, задержку, полноту событий и downstream качество относительно
  generated-commands/generic пути. Порог ship заранее выбирает владелец; экономию не обещать.

Для старого local Claude first-party Mods demo сейчас остаётся watch: обновление/включение
в этой задаче не выполняется. Для core enforcement hooks-only вариант сейчас отвергнут.
Research verdict prototype относится к ограниченному context/audit эксперименту, не к delivery
production изменений. Решение владельца ship/park/reject по всему #1246 остаётся отдельным.
