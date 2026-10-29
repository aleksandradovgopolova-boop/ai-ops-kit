# Контекст как измеряемый ресурс — #1403

**Результат.** До исполнения compiler исключает forbidden, проверяет обязательные источники и бюджет; отчёт хранит время сборки и качество выборки только по явной разметке.

**Затрагиваемые пути.** `.ai-ops.yaml` → child-config schema → context_compiler (bundle/payload) → preflight → артефакты и run-report; hybrid-additions; CLI компиляции → воспроизводимый локальный прогон.

**Инварианты.** Новый сборщик не создаётся. Без разметки precision/waste/miss = unknown; required/optional не означают релевантность. Токены — оценка context_cost, время — часы процесса. Forbidden не читается для payload. Недоступный required, некорректная политика и переполнение блокируют исполнение до writer. Старые конфиги остаются допустимыми.

**Failure modes.** Обход forbidden через symlink/нормализацию; required вытеснен или обрезан; служебная обёртка не учтена бюджетом; malformed config превращается в разрешение; hybrid добавляет запрещённый источник после compiler.

**Доказательство.** Positive: настоящий файл попадает в payload и его hash подтверждён. Fail-closed: missing/conflicting/over-budget required и malformed policy блокируют preflight. Side-effect proof: файл с forbidden-маркером существует и выбран базовым bundle, но чтения/маркера в payload нет; запрещённый hybrid не fed. Контролируемый локальный fixture даёт метрики по заранее записанной разметке, без LLM и внешней оплаты; targeted regressions, core smoke, ruff, независимое review.

**Не входит.** Семантическая оценка релевантности моделью; токенайзер провайдера; контекст, самостоятельно прочитанный native runtime вне compiled payload; закрытие #1403 до проверки полного результата.
