Покрытие ядра исполнения `ai_ops_run` перенесено из монолитного `test_ai_ops_run_selftest`
(одна мега-функция ~90 проверок) в гранулярные тесты `test_ai_ops_run.py`: одно поведение —
один тест, с настоящей проверкой значения, а не только факта существования артефакта. Добавлено
44 теста, покрывающих ранее непокрытые ветви: причина просроченной KLP-ротации; planned-путь
контроллера (неметериализованное состояние, регистрация active-work, треки VISUAL/ANALYTICS и
агрегация их гейтов, отсутствие analytics_runtime_verification в дорелизном плане); resume-политика
(повреждённый run-settings не перезаписан, base переписан/ушёл вперёд -> blocked даже с force/replan,
write-barrier durable RunPlan); pipeline-исполнение (applied_writes, commit-barrier по seq журнала,
lifecycle-артефакты, единый план); F-012 снятие active-work с честным статусом; типизированный сбой
провайдера (failure_class=network, retryable); контекст (bundle/payload, fed_to_model); spec/work
(SpecCoverage L0, handoff, атомарный пакет); заметка про живого предложителя; reevaluate_only;
реальный resume контроллера (обе фазы в worktree, устаревшая база, base_moved); orchestrated-путь;
поля DeliveryReceipt и идемпотентность реконсиляции; fix-loop (провал теста -> ready, событие
fix_attempt).

Монолит `tests/unit/test_ai_ops_run_selftest.py` НЕ снят: его имя `test_ai_ops_run_selftest`
названо в нетестовом файле `.github/workflows/pr-smoke.yml` (`-k`-фильтр smoke-прогона). Снятие
файла оборвало бы этот фильтр, поэтому покрытие продублировано гранулярно, а монолит оставлен до
отдельной правки workflow.
