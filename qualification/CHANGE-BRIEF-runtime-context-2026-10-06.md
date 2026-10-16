# Change Brief — runtime context/audit prototype

До кода. Исход: проверить offline переносимость объявленных skills и event correlation
между command-hook shapes Claude Code и Codex. Native integration не квалифицируется.

Изменение: один непоставляемый CLI в существующем devtools; resolve_skills используется
повторно. Вход — stage и replay payloads, выход — native context response и redacted audit.
Публичные stable схемы, runtime registry, workflow, installer и зависимости не меняются.

Positive: точные bodies/hash, owner и review_mode в сериализованном контексте двух runtime.
Fail-closed: unavailable skill/oversize/malformed ввод не дают успешного probe; разрывы,
дубликаты, другой session и неизвестные события дают degraded. Это отказ probe, не deny runtime.
Side-effect proof: реальный subprocess с tool_input для записи fixture не выполняет команду
и сохраняет дерево; audit не содержит raw input/output/body, только hashes и correlation IDs.

Риски: ACK выдан за доставку модели; полный replay выдан за полное native coverage; callback
считается источником evidence; дубли скрываются перезаписью; секреты попадают в audit.
Для предотвращения результата scope offline-replay, no live runtime runs, receipt только
observed payload. Сравнение footprint — bytes, не tokens/качество/экономия.

Проверки: granular unit/CLI tests, core smoke, свежий independent review и full-current-python.
