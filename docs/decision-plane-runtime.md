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

[Результаты #1251/#1252](../qualification/skills-safety/README.md): измерены actual context и
живые tokens, найдены и устранены high-risk gaps; сохранены before/after и protocol repairs.
Mandatory union дополнен существующим deterministic ceremony floor, независимо от router.
Широкая semantic selection accuracy остаётся незакрытой, новая production модель не вводится.
