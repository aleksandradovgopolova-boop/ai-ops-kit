# Доступность локального CLI до параллельного запуска

Результат: явный parallel provider claude-cli (включая поддержанный alias claude-code-local) с отсутствующим/неисполняемым бинарём останавливается в preflight ДО clone, нового claim и model callbacks. Используется только существующий orchestrator_providers.claude_binary: тот же AI_OPS_CLAUDE_BIN/PATH и без повторной реализации поиска.

Пути: run_parallel_live → _policy_refusal → canonical claude_binary; затем неизменённые admission/claim, isolated executor, fan-in и delivery. Для атомарного single-path и остальных providers изменений нет. Явный provider не заменяется mock/fallback. Existing auth/approvals/budget/generation fencing не ослабляются.

Инвариант: бинаря нет/нет X_OK →0 dispatch/model calls и0 clones. Настоящий исполняемый fixture-файл пропускает этот локальный preflight; реальные isolated commits создаёт контролируемый run_fn. Сам fixture CLI не вызывается. Наличие executable не доказывает auth, online health или model capacity; это только обязательная локальная предпосылка. После preflight файл может исчезнуть — дальнейшая ошибка не скрывается.

Пруф: missing и non-executable filesystem fixtures; positive с real executable и реальными package commits/fan-in без native вызова; early refusal перед durable admission validation; повтор той же работы после восстановления fixture CLI запускает каждый пакет ровно один раз (без расходов первой попытки, не crash recovery); existing parallel/claim/provider-resolution tests. Review и все17 exact-head CI до normal merge.

Не входит: новый scheduler/resolver, generic provider health, native/paid probes, автоматическое переназначение или завершение всего1322. Восстановление и перенос на другого исполнителя требуют существующего ownership/lease протокола; неподдерживаемые шаги не объявляются реализованными.

Review-исправление: проверяются оба имени, которые принимает существующий make_provider; lookup остаётся единственным. Alias воспроизведён четырьмя RED, оба имени проходят все отрицательные/positive/retry cases.

CI-исправление структуры тестов: первый запуск на 194899f5 обнаружил превышение лимита850 строк (889) в test_parallel_live_dispatch.py. Новые availability/retry cases вынесены в test_parallel_provider_availability.py, существующие Git fixtures — в _parallel_dispatch_helpers.py без изменения тел. До/после одинаковые84 test cases; лимит и CI остаются прежними. Итоговые размеры764/96/37 строк. Полный applicable CI выполняется заново для итогового SHA.
