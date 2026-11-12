# Claude provider: read-only контракт и граница доказательства (#1476)

**Состояние: live read-only BLOCKED.** Для `claude-cli` и `claude-code-local` нет
квалифицированного runtime-профиля. При наличии бинаря вызов возвращает
`ProviderRefusal(reason=readonly_runtime_unqualified)` до запуска любого подпроцесса,
writer-lock, retry и записи usage. При отсутствии бинаря сохраняется диагностика поиска.
Выбор провайдера не меняется автоматически: отказ не превращается в mock или успешный ответ.

Офлайн `mock`, явно выбранные API-провайдеры и доверенная тестовая инъекция `runner` сохраняются.
Инъекция — обычный Python callable: адаптер не ограничивает её права и не предназначает её
для обхода live-отказа. Она проверяет сборку argv, parse/usage/retry; это не доказательство
безопасности установленного Claude. Реальные model/API calls в этом изменении не выполнялись.

## Что установлено

Исследован локальный **Claude Code 2.1.314**, macOS: `package.json`, `--version`, `--help`.
SHA256 исследованного бинаря:
`21d6e7b9a6f07b4cfcb7df13760b3b72aa25e084e13a5354413382987ba832ed`.
Help/version запущены из временного каталога с отдельным `CLAUDE_CONFIG_DIR` и отключённым
nonessential traffic. Пользовательские settings/trust/credentials не редактировались.
Версия и help подтверждают наличие флагов, но не эффективную конфигурацию model turn.
**Ни эта версия, ни другие здесь не квалифицированы для live read-only.**

| Граница | Подтверждённый смысл | Чего это не доказывает |
|---|---|---|
| Builtin tools | `--tools Read,Grep,Glob` явно выбирает встроенные инструменты; `--allowedTools` задаёт autoapproval | Отсутствие MCP или произвольного кода из конфигурации |
| MCP | `--strict-mcp-config` ограничивает источники MCP; MCP — отдельная поверхность | Отсутствие всех MCP по одному builtin allowlist |
| Settings/plugins/hooks | `--setting-sources` выбирает user/project/local; restricted/safe mode сохраняют managed policy | Отсутствие policy hooks и startup effects |
| OS | CLI работает с правами своего процесса | OS sandbox, запрет сети, отсутствие служебных записей CLI |

Источники на 02.11.2026: [CLI reference](https://code.claude.com/docs/en/cli-reference),
[settings и precedence](https://code.claude.com/docs/en/settings).

MCP может происходить из user/local/project config, плагинов и claude.ai connectors;
plugin MCP не является builtin tool. Managed MCP имеет отдельные правила, которые нужно
проверять для выбранного режима запуска. Settings могут добавлять hooks; command hook
исполняется отдельно от предложенного модели builtin tool set. Это основания для отказа
от обещания «нет Write/Edit/Bash ⇒ нет mutation», а не утверждение об эксплуатации каждой установки.
Источники: [MCP](https://code.claude.com/docs/en/mcp),
[managed MCP](https://code.claude.com/docs/en/managed-mcp),
[hooks](https://code.claude.com/docs/en/hooks).

## Проверяемая гарантия этого среза

В `tests/unit/test_orchestrator_providers.py` temp fixture с permissive parent config реально
создаёт четыре файла в control subprocess (условные builtin/MCP/plugin/hook эффекты).
После удаления только этих тестовых файлов вызов адаптера с тем же fixture-бинарём и
конфигурацией даёт отказ: попыток запуска нет, файлы не созданы, конфигурация неизменна.
Тесты также проверяют оба provider alias, отсутствие retry и новых usage entries.

Это **proof блокировки запуска**, а не воспроизведение permission resolver Claude.
Прежняя проверка отсутствия строк Write/Edit/Bash в argv больше не называется read-only proof.
`--tools` добавлен в офлайн argv; сам по себе этот список не разрешает live-путь.
Итоговая квалификация эффективного read-only tool set с permissive parent остаётся BLOCKED.
Первичная декларация `registry/runtimes.yaml → claude-code.kit_driven_executing` также
помечена `unsupported`; прежний live end-to-end сохранён как историческое evidence.

После checkpoint `773594b3` исправлен найденный независимым review writer lifecycle-шов:
`orchestrator.run_workflow` сохраняет `blocked` и `provider_refusal` (stage/reason/detail),
пишет `stage-<sid>.refusal.json` и останавливается, сохраняя `next_action` и выполненные стадии.
Отказ не публикуется как успешный stage output/handoff; полное gate evidence не даёт `done`.
Обработка ограничена `readonly_runtime_unqualified` от `claude-cli`, включая его alias.
API/mock и остальные причины отказа новым guard не ограничиваются.
Controller report переносит сохранённые `provider_refusal` и `next_action`; человеческий
вывод показывает причину, варианты выхода и путь состояния для продолжения.

Явное продолжение с безопасным провайдером исполняет ту же незавершённую стадию. После её
успеха текущий отказ переносится в `stage-<sid>.refusal.previous.json`, а `provider_refusal`
удаляется из текущего TaskState; выполненный префикс сохраняется. Исторический отказ не
подменяет новый результат в collect-evidence. Budget `model_calls` по существующему контракту
считает logical admissions, а не реальные subprocess/model calls; новых provider usage entries
при заблокированном запуске нет. Регрессии используют настоящий guard и temp workflow.

## Профиль и стенд квалификации (11–12.11.2026)

Адаптер собирает запуск из одного профиля `CLAUDE_READONLY_PROFILE`
(`ai_ops_kit/providers/provider_calls.py`): `--restricted` (без инструментов, исполняющих код, и без
user/project/local settings), `--safe-mode` (без плагинов, хуков, MCP, CLAUDE.md и skills),
`--strict-mcp-config` без `--mcp-config` (ни одного MCP-сервера), `--tools Read,Grep,Glob` с их
автоодобрением, `--permission-mode dontAsk` и `--permission-prompts none` (всё, что спросило бы
разрешение, отклонено), `--disable-slash-commands`. **Профиль live-путь не открывает:** отказ
`readonly_runtime_unqualified` остаётся, пока профиль не квалифицирован на конкретном бинаре.

Стенд квалификации судит по эффекту:

```bash
python3 -m ai_ops_kit.devtools.claude_readonly_qualification          # фикстура + контроль, без модели
python3 -m ai_ops_kit.devtools.claude_readonly_qualification --live   # 4 настоящих вызова модели
```

Одноразовый git-проект с разрешительной ПРОЕКТНОЙ конфигурацией (`bypassPermissions`, allow
Write/Edit/Bash, хук SessionStart и stdio MCP-сервер, пишущие канарейки). Контроль сначала запускает
хук и MCP-сервер напрямую — они обязаны оставить следы, иначе пробы ничего не доказывают. Затем
профилем: записать файл, выполнить команду, вызвать MCP, прочитать README. Вердикт `qualified` —
проект побайтно прежний и метка прочитана; `failed` — проба изменила проект или не прочитала;
`not_measured` — ход модели не состоялся (отказ входа, ошибка флагов, конверт `is_error`). Последнее
закреплено тестом: тишина без ответа модели не засчитывается как защита.

**Первый живой прогон (11.11.2026, Claude Code 2.1.314, SHA256 выше): `not_measured`.** CLI не был
авторизован (`OAuth session expired`), модель не ответила ни разу. Найдено попутно: процесс,
запущенный из приложения Claude, наследует `CLAUDE_CODE_SIMPLE=1` (упрощённый режим без чтения
входа из связки ключей) — адаптер в такой среде получит отказ входа, а не read-only сессию. Копия
CLI внутри приложения (2.1.317) вход приложения дочернему процессу не передаёт (`api_error`, 0 токенов).
Пользовательские `~/.claude` и managed-настройки стенд не меняет; их игнорирование профилем этим
стендом не доказывается — только проектный уровень.

## Узкий следующий шаг

Отдельно подготовить профиль точного runtime/artifact и режима запуска в одноразовой среде:
явный builtin set; отключённые user/project/local sources; отдельные правила для installed
и managed plugins, hooks, MCP и connectors; проверка environment/config precedence и startup.
Использовать штатный способ получить effective tool/config inventory без model turn, если
он доступен и подтверждён для этой версии. В изученном help такого доказательства не получено.
При отсутствии такого способа согласовать отдельную квалификацию в изолированной disposable
среде с отрицательными пробами и положительным чтением; до неё live-путь остаётся закрытым.
Простой version match, env opt-in, mock permission resolver или argv assertion не подходят.

Не удалять и не переписывать настройки пользователя, не ослаблять managed policy.
Для OS-гарантий нужен отдельно проверенный процессный/контейнерный boundary; CLI-флаги его
не заменяют. #1407, #1434 и общая архитектура провайдеров этим срезом не закрываются.
