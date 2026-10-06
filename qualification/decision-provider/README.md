# Контракт ограниченных решений — #1248

Контракт реализован в существующем пакете devtools и проведён в current baseline offline
harness. Это internal surface; production routing и сетевые провайдеры не подключены.

`cli-proof.json` сохраняет 20 actual current вызовов из обычного CLI evaluation harness:
16 selected, 4 abstain, 0 error; все 20 имеют decision_audit. Код CLI — 1, verdict —
continue experiment, а не ship. Этот запуск проверяет проводку, не пользу семантического
провайдера. Все 20 decision/abstain совпали с сохранённым qualification/decision-plane/baseline/report.json. Источник записан
с dirty=true до коммита после переноса в devtools; source_sha256 включает актуальный путь
контракта. Source hashes сохранены как фактический capture, не заменены хешем будущего коммита.

Первый full-current-python на CPython 3.14.7/darwin: 8969 passed, 35 skipped, 2 failed,
1 warning (688.77 с). Новый providers-файл нарушил delivery budget (685 < 685 неверно);
mutation probe release-prose-does-not-ship не засчитан из-за того же красного installer baseline.
Контракт перенесён в непоставляемый devtools, потолок не изменён.

Fresh read-only review по AGENTS.md выполнен независимой AI-сессией без авторского контекста:
конкретных находок нет. Проверены correctness, fail-closed, изоляция state, primary/fallback,
provenance и проводка; 85 unit/contract тестов passed, повторные unit — 64 passed.

Ограничение: синхронный вызов не прерывает зависший транспорт. Budget передаётся адаптеру,
поздний ответ отклоняется. Нельзя обещать wall-clock timeout или производственную безопасность
будущего Jev/LLM адаптера до его реализации и отдельной квалификации. Invalid confidence
отклоняется; валидная confidence не является разрешением, калибровка не проверяется.

После переноса целевой набор (контракт + installer budget + все объявленные mutation probes)
прошёл: 36 passed, 1 warning, 637.92 с. Предупреждение — существующий малый запас объёма
поставки; потолок не пробит и не поднят. Повторный full-current-python на CPython 3.14.7/darwin прошёл:
**8971 passed, 35 skipped, 2 warnings**, 667.99 с. Ruff прошёл. Compatibility-matrix
проверяется отдельно в CI; этот локальный прогон её не подменяет.
