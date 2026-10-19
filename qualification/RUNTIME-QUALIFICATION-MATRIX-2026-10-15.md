# Подтверждённые границы исполнителей — #1241

Срез 15.10.2026, Kit main b45f7de8. Это сводка существующих доказательств,
не новый live прогон. Модель работы и план не зависят от исполнителя; глубина
автоматизации зависит. Сгенерированная команда сама по себе не проводит гейты.
`verified` относится только к названному опыту; `documented` — декларация,
`unknown` — нет подходящего live evidence; `degraded` — опыт отказал или ограничен;
`unsupported` — реестр прямо исключает возможность. Отсутствие квалификации
не означает, что сам продукт runtime технически не умеет это делать.

Каждая ссылка в клетке содержит дату/версию источника. Где версия не сохранена,
она явно unknown: историческое свидетельство нельзя сделать свежим задним числом.

| Исполнитель | Установка | Исполнение | Независимое review | Hooks | Parallel |
|---|---|---|---|---|---|
| Claude Code | documented: generated commands; версия runtime unknown, декларация 08.07.2026 [R] | degraded: 2.1.300, 15.10, OAuth session expired [N]; 2.1.283, 06.10, inference отказал организации [L]; исторический executing путь описан отдельно [R] | documented role isolation, версия unknown, 08.07 [R]; новый live verdict unknown | degraded: 2.1.300, 15.10, SessionStart выполнен, tool lifecycle не достигнут [N]; прежний опыт 2.1.283, 06.10 [L]; ручной PostToolUse 05.10 не засчитывается [S] | documented, runtime version unknown, 08.07 [R]; текущий live опыт unknown |
| Codex CLI / app | documented generated prompts, версия unknown, 08.07 [R]; это не проверка всех app surfaces | verified только bounded PRODUCT.specification: CLI 0.147.0 / gpt-5.6-terra low, 06.10 [C]; весь workflow blocked, exit 1 | unknown для Kit review gate: PRODUCT.specification не выполнял review, 0.147.0, 06.10 [C] | verified context/control и native before/after одной fixture: 0.147.0, 06.10 [L]; не universal enforcement | degraded/limited по реестру, версия unknown, 08.07 [R]; live parallel qualification unknown |
| Qwen Code | documented generated commands, версия unknown, 07.09 [R] | documented runtime-native instructions; live unknown, версия unknown, 07.09 [R] | unknown live, версия unknown, 07.09 [R] | unknown live, версия unknown, 07.09 [R] | unknown live, версия unknown, 07.09 [R] |
| Cursor | documented command packaging, версия unknown, 08.07 [R] | documented native/sequential, live unknown, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live; native_subagents unsupported в реестре, версия unknown, 08.07 [R] |
| Gemini CLI | documented commands, версия unknown, 08.07 [R] | documented sequential, live unknown, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live; native_subagents unsupported в реестре, версия unknown, 08.07 [R] |
| OpenCode | unknown install qualification; отдельный MVP adapter не объявлен, версия unknown, 08.07 [R] | documented native/sequential, live unknown, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] | unknown live, версия unknown, 08.07 [R] |
| Generic orchestrator | documented package entrypoint, версия runtime unknown, 08.07 [R] | verified исторический QUICK/DeepSeek, Kit v2.40; дата capture unknown [R]; не свежая qualification 4.10.1 | documented изоляция ролей, версия runtime unknown, 08.07 [R]; текущий live unknown | unknown native hooks: это собственный control plane, версия runtime unknown, 08.07 [R] | verified исторический s3c/parallel-2, Kit v3.8, дата capture unknown [R]; не Codex/Claude native parallel |
| Generic API | documented adapter, версия runtime unknown, 08.07 [R] | documented single-model sequential, live unknown, версия runtime unknown, 08.07 [R] | unknown независимый live judge, версия runtime unknown, 08.07 [R] | unknown native hooks, версия runtime unknown, 08.07 [R] | unsupported по реестру, версия runtime unknown, 08.07 [R] |

| GitHub Actions (CI runtime) | documented CI host, runner version unknown, 08.07 [R] | documented validators/self-tests/updater, live конкретного runner unknown, 08.07 [R] | unknown независимый model judge, runner version unknown, 08.07 [R] | unknown agent lifecycle hooks, runner version unknown, 08.07 [R] | unknown Kit native parallel, runner version unknown, 08.07 [R] |

## Источники и пределы

- [R]: [registry/runtimes.yaml](../registry/runtimes.yaml). Дата деклараций
  `last_documented_at=2026-07-08` (Qwen Code — 2026-09-07); более поздние inline исторические записи
  называют Kit v2.40/v3.8/v3.9, но не сохраняют точную дату native capture.
  Их статусы сохранены как исторические заявления реестра, не переподтверждены.
- [L]: [live context/control](runtime-context-live/README.md),
  [структурированный report](runtime-context-live/report.json), 06.10.2026.
  Missing skill отказал до model launch; nonce без context неизвестен;
  fixture проверена отдельно. Нулевые gaps не доказывают полноту audit.
- [C]: [bounded Codex stage](codex-product-stage/README.md),
  [NativeStageReport](codex-product-stage/NativeStageReport.json), 06.10.2026.
  Text-only internal devtools не установлен дочкам и не general executing provider.
- [N]: [повтор Claude](runtime-context-retry-2026-10-15/README.md), 15.10.2026,
  Claude Code 2.1.300, один отказавший запуск; control после отказа не выполнялся.
- [S]: [полевой lint](CODE-STYLE-FIELD-RUN-2026-10-05.md), 05.10.2026,
  Kit v4.9.0; native Claude version не сохранена. CI отказал на нарушениях,
  ручное событие hook выполнено, живой транспорт ошибки агенту не доказан.

На 15.10 текущая официальная документация описывает lifecycle hooks Codex,
но требует доверия к hooks плагина и наличия скриптов в среде:
[OpenAI, Package your plugin](https://developers.openai.com/plugins/build/plugins).
Это документация продукта, не доказательство проводки конкретной установки Kit.
Новые runtime возможности нельзя молча приписать установленному адаптеру.

#1269 остаётся открытой для Claude access; #1183/#1193 — для недостающих
полевых профилей и живой реакции. #611 — отдельная архитектурная работа.
Закрытие этой сводки означает доступность границ, а не квалификацию всех исполнителей.

Независимый Codex review выявил пропуск OpenCode и неверную дату Qwen; обе
находки исправлены. После исправления проверено покрытие всех девяти записей
реестра, наличие локальных источников и совпадение даты Qwen.

Проверки записи: 42 targeted passed; full-current-python на CPython 3.14.7 / darwin —
9038 passed, 35 skipped, 2 warnings, exit 0 (955.19 s). Это не compatibility-matrix.
Цена основной AI-сессии и независимых reviews unknown; native retry сообщил $0
только для отказавшего запуска Claude, не для всей работы.

## Дополнение 16.10: новые ограниченные live доказательства

Исходная таблица выше сохраняет срез 15.10 и его неудачные попытки. Следующие
наблюдения не переписывают историю и не повышают всю строку runtime до verified.

| Исполнитель / опыт | Новый факт | Что не доказано |
|---|---|---|
| Codex0.163.0 / gpt-5.6-terra, #611 | Прежние plan/WorkItem/RunPlan + adapter прочитаны; native 4+1 = 0/0/0/0/2, три SHA256 неизменны, [пакет](runtime-protocol-611-2026-10-16/README.md) | do отказал до inference из-за size/risk; нет delivery, успешного Qwen inference или all-three qualification |
| Claude Code2.1.301 / claude-opus-4-8, #1269 | После восстановления доступа nonce/owner/mode в context, null в control; native Pre/Post pairs и exact fixture; missing skill до launch, [пакет](claude-context-1269-2026-10-16/README.md) | Whole PRODUCT, production adapter, general mandatory enforcement и полное покрытие audit |

#611 [закрыта по сверке критериев](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/611#issuecomment-6216994446)
16.10 в13:52:31UTC; #1269 [закрыта после context/control](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1269#issuecomment-6217234772)
в14:05:21UTC. Auth blockers выше относятся к прошлым попыткам, не к текущему
состоянию. Независимое review роли/parallel и другие столбцы автоматически не
становятся квалифицированными. USD subscription allocation/owner minutes unknown;
Claude native list estimate не фактический счёт. Основная продуктовая когорта не растёт.
