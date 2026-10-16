# Runtime context/audit prototype — #1267

Внутренний R&D CLI: `python3 -m ai_ops_kit.devtools.runtime_context_probe`.
Не поставляется дочкам, не устанавливается как hook. Начальный scope — offline replay.

## Воспроизведение

Из корня пакета:

```bash
python3 -m ai_ops_kit.devtools.runtime_context_probe --runtime codex < qualification/runtime-context-prototype/codex-complete.input.json
python3 -m ai_ops_kit.devtools.runtime_context_probe --runtime claude-code < qualification/runtime-context-prototype/claude-code-complete.input.json
```

Тот же вызов с `*-gap.input.json` возвращает 1/degraded, с `*-missing-skill.input.json` —
2/error и пустой stdout. Это коды devtools probe, не новые коды публичного `./ai-ops` и не
native hook deny. CLI stdout — отчёт; только его `context_output` имеет native response shape.
Не подключайте этот CLI напрямую в runtime hooks: runtime получит не тот верхний объект.

## Что доказано

`capture.json` — шесть actual subprocess вызовов: по два успешных serialization/gap результата
и одному отказу missing skill для каждого runtime. Fixtures tool events синтетические;
stage specification взята из PRODUCT workflow. CLI output содержит точный skill body,
owner/review_mode и хеши. Ответ SessionStart у двух runtime имеет одинаковый контекстный shape;
Codex tool events дополнительно связываются по turn_id, отсутствующий ID не выдумывается.

Receipt утверждает FACT сериализации, не ACK runtime/модели. FACT payload_observed значит
получение предоставленного replay payload, а не аутентичность его источника или выполнение
инструмента. Audit хранит hashes и correlation IDs, без cwd, tool arguments/results и bodies.
Полный контекст присутствует только в предназначенном для отправки `context_output`; в capture
сохранены hashes/размеры/проверка exact body, а не повторная копия текста skills.

Известные replay gaps: orphan/missing result, duplicate payload/call, неизвестное событие или
source, missing identity, другой session/turn и смена tool arguments. `observed` означает
согласованность поступившего окна, не полноту всех native событий. Без ожидаемой полной
трассы нельзя обнаружить исчезновение пары before+after целиком. Schema validation —
проверка используемого подмножества, не валидатор всего протокола runtime.

Тест реального CLI даёт tool_input с командой записи fixture, затем сравнивает дерево файлов:
probe команду не исполняет и ничего не записывает в fixture. Это side-effect proof самого наблюдателя,
не доказательство запрета native действия. Result payload не закрывает evidence gate.

## Ограничения и следующий шаг

Live runtime runs — 0; model turns — 0. Без live qualification нельзя объявить реальную
доставку skills, поведение timeout/trust/отключённого hook, либо полноту audit supported.
Writer/read-only — инструктивный контекст, не новая граница полномочий. Required skill error
останавливает только probe; существующий broker/gates остаётся policy boundary.

Контекст имеет строгий предел 32768 UTF-8 bytes; это не token budget и не гарантия против
native spilling. Для live Codex нужен явно выбранный additionalContextLimit и проверка
фактической доставки, иначе runtime может показать только preview.
[Official OpenAI documentation](https://learn.chatgpt.com/docs/hooks).
Сериализация SessionStart и input fields сверены с
[Claude hooks](https://code.claude.com/docs/en/hooks).
Первичные документы прочитаны 2026-10-06, metadata исследования — qualification/runtime-hooks.

Следующая qualification — изолированный live stage, проверка фактического model input и
native correlation, затем измерение downstream эффекта. Новых зависимостей/Mods/tool loop нет.

## Проверки ветки

Целевые unit/CLI и package-surface проверки: 43 passed. Быстрый профиль: 8311 passed,
34 skipped. full-current-python (CPython 3.14.7 / darwin): 9002 passed, 35 skipped,
2 warnings. Шесть captures воспроизведены с теми же stdout/stderr hashes.
Свежий independent read-only review — без actionable findings; reviewer отдельно проверил
форматы по первичным источникам. Compatibility-matrix подтверждает только CI.

Первый CI выявил Linux-only отказ самого тестового subprocess: pytest автоматически
включил 262145-byte вход в param ID и PYTEST_CURRENT_TEST, превысив exec environment limit.
Исправлены только IDs тестовых кейсов; payloads/assertions и код probe не изменены.
После этой коррекции: 32 targeted tests passed; correction проверена reviewer. Результат
full-current-python выше получен до смены pytest IDs; актуальную Linux проверку выполняет CI.
