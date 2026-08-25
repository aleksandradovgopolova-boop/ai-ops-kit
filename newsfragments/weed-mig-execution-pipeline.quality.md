Прополка: покрытие ядра исполнения `execution_pipeline` перенесено из монолитного
`test_execution_pipeline_selftest` (одна мега-функция ~1284 строки) в гранулярные тесты
`tests/unit/test_execution_pipeline.py` — 80 новых юнит-тестов, каждый проверяет ОДНО поведение
с настоящей проверкой значения (не только наличия артефакта или верхнего status). Перенесены
связные группы целиком: петля/отчёт прогона (stopped/applied_writes/профиль/гейты/not_yet/
out-of-scope), commit и isolate (evidence на точном SHA, ветка ai-ops/*, guard повторного прогона,
snapshot-delta, shell-правка), resume, spec-first, env-квалификация, security (fail-closed,
форс в оценку, reviewer, #5-guard, reevaluate-only, secret_boundary, spec-depth), structured-id
diff по стекам (pytest/go/rust/java/tsc, coverage-loss, new-red), baseline не обходит гейты,
ревью (ux_review, contentless warn), approvals (recheck_after_diff, _record_valid,
_human_approval_domains_uncovered), base-binding и base-preflight, authoring. Монолит СОХРАНЁН
(назван в pr-smoke `-k`); снятие — отдельным шагом после полного переноса.
