# #1446: producer CI-архива до потери association

**Результат.** Существующий publisher наблюдает CI открытых PR и сохраняет
проверенную точную привязку в том же payload; после merge historical lookup
использует её лишь через существующий verified Pages prior.

**Пути.** release_plan_sources capture/refresh/final freshness; release_plan
archive producer/lookup; existing previous/project/deploy; локальные fixtures.
Новый producer не исполняет PR код, не получает artifacts и не расширяет права.

**Инварианты.** Exact repository/PR/head/base, все policy checks, latest run/attempt
и полный jobs digest. До merge SHA ещё неизвестен: после него обязателен реальный
Git first parent == сохранённому base и серверный merged/closed PR. Неполные,
чужие, изменившиеся, failed/rerun и противоречащие данные не дают PASS.
Локальный файл и его digest не заменяют подтверждённый Pages deploy.

**Failure modes.** Подмена repo/PR; stale head/base/merge; rerun/job mutation;
partial source; подмена prior. Проверяем positive producer→published-prior fixture
→lookup и отрицательные случаи, отсутствие записи/API mutations и сохранение
readiness=false без архива. Fixture не является live attestation.

**Границы.** Только локальные commit/diff/tests/review. Без push/PR/merge/bump,
live deploy/уведомлений, новых permissions/credentials, восстановления прошлого
без источника. Исходные a856db83 и 8e7721ae остаются отдельными коммитами.
