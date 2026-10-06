# Одна specification через Codex

Внутренний opt-in путь исполняет только `PRODUCT.specification` из registry. На входе — задача
и уже опубликованные intake/requirements; на выходе кит создаёт `stage-specification.md`,
`NativeStageReport.json` и `GateReport.json` в НОВОМ каталоге. Он не продолжает предыдущие стадии,
не делает resume и не закрывает PRODUCT. Для CLI результат одной стадии означает код 1
(исполнено, но workflow не готов); отказ — 2. Команда находится в devtools и не устанавливается
в дочерние репозитории как новый публичный интент `./ai-ops`.

```bash
python3 -m ai_ops_kit.devtools.codex_stage_cli \
  --input input.json --output-dir result \
  --model YOUR_MODEL --codex-bin /path/to/codex
```

`input.json` содержит `task` (непустая строка) и `published` с ровно двумя непустыми строками:
`intake`, `requirements`. Подготовку и приёмку этих артефактов выполняет существующий процесс;
наличие текста не объявляет соответствующие гейты пройденными. Модель выбирается явно.
Опционально `--auth-file` указывает существующий native auth.json, `--timeout` — положительное
число секунд (по умолчанию 120). Живой запуск расходует лимиты аккаунта; бесплатность Codex
не заявляется. API-key fallback и Jev отсутствуют.

## Контекст и исполнение

Роль и skills берутся из `registry/workflows.yaml`; отсутствие обязательного тела и превышение
32 KiB обязательного контекста отказывают до native launch. Pure serializer/audit вынесен из
offline probe в providers; API probe и его CLI сохраняются. Тело роли и опубликованные данные
передаются через stdin prompt, skills — через vetted SessionStart command hook. Hook получает
предварительно проверенный snapshot; он не перечитывает изменённые файлы skills посреди запуска.

Native процесс получает пустой временный workspace и private native home. Auth копируется с
правами 0600 и удаляется вместе с temporary directory. Пользовательские config/hooks не меняются
и не загружаются через user config. Shell, multi-agent, apps, remote plugins и memories выключены;
web search disabled, native policy read-only. Deny-all PreToolUse — дополнительная граница для
text-only сценария, а не новый универсальный security broker. Ошибки hooks могут fail-open в
runtime: поэтому кит не принимает результат без наблюдаемого SessionStart и совпавшего hash ACK.
ACK доказывает исполнение handler, а не видимость всего контекста в raw model input.

Наблюдаемые tool attempts, неожиданные native items, missing completion, пустой ответ,
ошибка процесса, timeout и изменение временного workspace отклоняют публикацию. Это проверка
наблюдаемого окна, а не полное покрытие инструментов или доказательство OS isolation.
Managed runtime policy продолжает действовать; если она отключит hook, стадия не принимается.

## Гейты и происхождение

Ответ — REASONING от solution-architect. Hash-only native audit и serialization receipt — FACT.
Receipt по-прежнему говорит `runtime_delivery_verified: false`, audit —
`native_coverage_verified: false`, `side_effect_verified: false`. Никакой текст модели не
становится human decision или gate evidence: существующий gate executor оценивает PRODUCT с
пустым evidence, обязательные проверки остаются незакрытыми. `workflow_status: blocked` всегда;
TaskState/completed_checks всего workflow не записываются. Это первый ограниченный адаптер,
не general Codex provider и не решение владельца о production ship эпика #1246.

Источник native shape/CLI: [официальные hooks](https://learn.chatgpt.com/docs/hooks),
[developer commands](https://learn.chatgpt.com/docs/developer-commands),
[feature configuration](https://learn.chatgpt.com/docs/config-file/config-basic).
