God-функция `execute_sequence` (engine/workpackage_executor.py) доразобрана без изменения
поведения (K6-глубина): из тела вынесены четыре крупных инлайн-блока в именованные фазовые функции
того же модуля —

- `_verify_resumed_package` — подтверждение пакета до `resume_from` (был вложенный `_verify_skipped`);
- `_build_package_signals_and_task` — сборка per-package сигналов и текста задачи с границами пакета;
- `_persist_package_report` — атомарная запись report.json-чекпоинта и снимок lifecycle-артефактов
  (решение о HARD-STOP при сбое остаётся в вызывающем);
- `_journal_package_end` — событие журнала `package_end`.

`execute_sequence` сократилась с 261 до 182 строк; поведение зафиксировано существующими тестами
`test_workpackage_executor.py` плюс добавленной характеристикой `test_corrupt_prior_report_on_resume_error`
(битый отчёт при resume). Мутационная проба `security-report-sequential-carries-findings` не
затронута (её якорь в `_compute_aggregate_verdict`).
