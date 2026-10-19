# Change Brief — готовая работа использует свободный слот

- Исполнитель: AI (Codex).
- Результат: независимый готовый пакет стартует после подтверждённой зависимости, не ожидая посторонний медленный пакет; `next` не рекомендует пересекающиеся области записи.
- Пути: `planning/next_work._parallel_set`, authoritative `planning/delivery_plan.scope_prefix`, lower-layer `engine/parallel_planner` scope/SHA checks, `engine/parallel_executor._run_packages`, существующие unit-тесты (включая hex-shape fixture parallel_live) и changelog-фрагмент.
- Инварианты: реальные зависимости и contract-first сохранены; максимум два исполнителя, отдельная изоляция остаётся обязанностью runner; области активных писателей не пересекаются; fan-in получает топологический порядок и доказательства точного SHA.
- Failure modes: глобальная/неизвестная область; несостоявшаяся зависимость; исключение/отмена runner; занятый конфликтующий слот; неполное доказательство при `status=pass`.
- Доказательство: сначала красные регрессии; Events/барьеры доказывают перекрытие и запрет старта; реальные временные файлы подтверждают действия; сбой не создаёт integration/DeliveryIntent.
- Проверки: целевые unit-тесты, один независимый AI-review, `full-current-python` под общим блокирующим замком (конкретный риск: изменены concurrency admission и package exact-SHA gate), все обязательные CI точного итогового head.
- Замер: только контролируемое расписание и его события; продуктовый lead time, USD и человеческая приёмка из него не выводятся.
- Не входит: native session launcher, автодекомпозиция без доказанных scopes, provider/delivery binding, отмена уже запущенного внешнего процесса и повышение параллельного лимита.

## Prospective amendment 2026-10-19 — durable baseline root alias

- До исправления: исходный full на 64538a01 сохранён как FAIL (9324 pass, 1 fail, 35 skip); отдельная регрессия воспроизводится за 1.99s. macOS `/var` alias и resolved `/private/var` сравниваются как разные корни при сохранении baseline.
- Пути: только existing `parallel_live._preserve_package_artifacts` и actual clone/ledger unit-тесты. Один canonical resolved run-root используется для baseline child path; leaf НЕ разрешается через resolve и остаётся под прежним symlink guard.
- Инвариант: настоящие package calls/receipts сохраняются; symlink baseline по-прежнему блокирует delivery и сохраняет исходные клоны. Ledger validation/readback не меняются.
- Proof: явный root symlink alias на Linux/macOS, два реальных package commit/ledger эффекта и durable receipt; реально подменённый baseline leaf symlink даёт fail-closed без записи наружу. Один узкий fresh delta review; relevant targets/guards и все exact-head CI. Исходный failed full не переписывается и не объявляется успешным; второй full без нового конкретного риска не запускается.
