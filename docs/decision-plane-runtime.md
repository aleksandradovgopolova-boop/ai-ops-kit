# Skills, обязательная policy и происхождение решений

## Передача skills (#1251)

Sequential `orchestrator.run_workflow` загружает только `uses_skills` текущей стадии.
Источник shipped id/path — `manifest/ai-ops-manifest.yaml`; текст передаётся вместе с телом
одного выбранного агента. Явная декларация стадии включает opt-in skill для этого вызова.
Skill, которого нет в пакете (например deep-research), требует `skill_resolver(id) -> str`
от runtime. По умолчанию рабочий entry разрешает skill-файлы, установленные
в `.claude/skills`, `.agents/skills` или `.codex/skills` дочки; builtin без доступного
текста не имитируется. Отсутствующий/пустой контекст, ошибка resolver или путь за пределами пакета
останавливают стадию ДО provider call, результат стадии не фабрикуется. TaskState содержит
skill_failure либо hashes/bytes реально переданного контекста в skill_context.

Это проводка известного контекста, не probabilistic selection и не доказательство экономии
токенов. Приёмка #1251 по downstream quality/token savings остаётся отдельной квалификацией.
Другие native runtime пути не объявляются покрытыми проверкой sequential API.

## Независимый обязательный набор (#1252)

`gate_executor.evaluate` воспринимает `gate_ids` как добавление к workflow. Обязательный набор
восстанавливается из контракта workflow, детерминированного route по исходным signals и
активных tracks; условные human approval gates добавляются по их registry policy. При отказе
route используется CRITICAL, что явно отражается в отчёте. Неполная policy не становится pass.
Пустое предложение роутера не отменяет обязательные проверки, независимый review и security.

Signals должны приходить из intake/проверок репозитория; эта граница не аутентифицирует
произвольного вызывающего, который подделал исходные факты. Владелец сохраняет существующие
явно разрешённые policy overrides и applicability; semantic recommendation не заменяет их.

## Происхождение (#1254)

Gate evidence допускает необязательное `provenance`: FACT / JUDGMENT / REASONING /
HUMAN_DECISION. Legacy `source` сохраняет смысл: deterministic / ai_judgment / human.
Противоречащие поля и неизвестные типы не принимаются как подтверждение.

- FACT: воспроизводимая проверка, а не название модели. Явный тип другого происхождения не закрывает validator.
- JUDGMENT: заключение AI reviewer; не заменяет тест/validator или одобрение человека.
- REASONING: generative output writer; не заменяет independent review.
- HUMAN_DECISION: явно полученное решение человека; не считается deterministic verification.

Collector reviewer маркирует своё evidence как JUDGMENT. Результат стадии сохраняется с
actor/source/hash в stage-*.provenance.json (writer → REASONING, judge → JUDGMENT).
GateReport/JSON CLI выводят kind и описание каждого существенного gate claim в claim_origins;
неполученное/невалидное evidence имеет неизвестное происхождение. Honest not_applicable skip
не делает evidence_verdict.verified истинным. Сам тип происхождения не доказывает истинность
и не аутентифицирует внешнего producer: native ApprovalRecord/security механизмы сохранены.

Изменения gate-evidence/gate-result схем аддитивны: новые поля необязательны, версия не меняется.

Legacy evidence без source/provenance сохраняет прежнюю обработку статуса, но имеет
неизвестное происхождение и не даёт verified. Ожидаемый тип гейта не приписывается producer.

## Квалификация без Jev

[Результаты #1251/#1252](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/6e0360f8204fc054a28d3e6685930cbfb58a0abc/qualification/skills-safety/README.md): измерены actual context и
живые tokens, найдены и устранены high-risk gaps; сохранены before/after и protocol repairs.
Mandatory union дополнен существующим deterministic ceremony floor, независимо от router.
Широкая semantic selection accuracy остаётся незакрытой, новая production модель не вводится.

## Внутренний контракт DecisionProvider (#1248)

`devtools.decision_provider` — internal, не стабильная поверхность дочки. Его фактический
потребитель — `devtools.decision_eval.current`: тот же deterministic baseline, теперь с
машинным аудитом ограниченного выбора. Production workflow не вызывает новый провайдер. Контракт размещён в непоставляемом devtools:
он нужен родительскому измерителю; перенос в production — отдельная работа.

`DecisionRequest(state, question, options, decision_type)` передаёт JSON-состояние, вопрос,
непустой уникальный набор строковых ID и тип решения. `DecisionProvider.decide(request,
budget_ms=...)` возвращает `DecisionReply`: selected с ID опции либо abstain/error с причиной.
Не требуется генерация текста, tool call или writer. Составной выбор model/effort или
agent/skills потребитель заранее кодирует конечными ID, без произвольного payload.

`run_decision` проверяет границу, изолирует состояние каждого вызова и возвращает
`DecisionResult` schema_version=1: тип/статус/решение/confidence, provider, provenance,
флаг фактически вызванного fallback и attempts. В каждой попытке записываются identity и
revision адаптера, provenance, status/reason, решение/confidence, latency и SHA-256 исходного
request. При успехе fallback первичная неудача остаётся в аудите. Секреты из сообщений
исключений не попадают в отчёт; исходное состояние хранится у вызывающего, в аудите только хеш.

Провайдеры подключаются структурно через Protocol или CallbackDecisionProvider. Deterministic
правило получает FACT; heuristic и model — JUDGMENT. Вид задаёт доверенная конфигурация адаптера,
а не его ответ. Это метка происхождения, не подтверждение истинности и не аутентификация
внешней реализации. Контракт не создаёт HUMAN_DECISION/REASONING, evidence или pass гейта.
Адаптеры Jev/LLM и сетевые вызовы здесь не реализованы и в runtime registry не объявлены.

Некорректный ответ, неизвестная опция, NaN/bool confidence или исключение становятся error.
Неверный запрос/configuration отвергается до вызовов. Fallback задаётся явно вызывающим,
запускается только после abstain/error и в оставшемся общем бюджете. Отсутствующий fallback
оставляет отказ; его собственный отказ не становится решением. Confidence в [0,1] не считается
калиброванной вероятностью и сама по себе не разрешает исполнение. Политику порога уверенности
определяет конкретный потребитель; текущий deterministic baseline confidence не выдумывает.

Transport timeout обязан обеспечивать адаптер. Синхронная граница не прерывает зависший
транспорт: budget_ms передаётся адаптеру, а после возврата поздний ответ отклоняется. На этом
основании нельзя объявлять bounded wall-clock для будущего сетевого провайдера без его
отдельной квалификации. TimeoutError/unavailable/malformed сохраняются как отказ; общий
бюджет исключает новый fallback после истечения срока.

Selected остаётся предложением. Независимый deterministic policy floor и mandatory union
из #1252 применяются вне провайдера по исходным signals; смена адаптера не меняет workflow
или эти правила. Тест демонстрирует реальный model downgrade до проверки и его исправление
существующим floor, а также отказ JUDGMENT закрыть deterministic evidence. Production-проводка
и пороги уверенности требуют отдельного полезного сценария и проверки downstream качества.

## Runtime integration research

[Исследование hooks и Mods (#1255)](runtime-hooks-research.md) сравнивает текущие публичные
поверхности, ограничения ошибок/coverage и проект общего адаптера. Research verdict —
ограниченный prototype контекста/аудита; существующие broker/gates сохраняют обязательную policy.
