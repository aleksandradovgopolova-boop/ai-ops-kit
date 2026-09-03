K6-глубина: god-функция `run_pipeline` (399 строк, держала потолок func-size каталога `engine/`)
расщеплена на приватные фазовые помощники В ТОМ ЖЕ файле `execution_pipeline.py` —
`_pipeline_check_spec_drift` (сверка с контрактом ядра), `_pipeline_resolve_policy` (политика
containment), `_pipeline_run_gates` (гейты RunPlan + печать закрытия + персист gate-evidence),
`_pipeline_assess_readiness` (evidence-ревизия, spec-depth, baseline-diff, квалификация окружения,
перепроверка одобрений и связности контуров, итоговый ready), `_pipeline_build_report` (проекция
состояния фаз в единый отчёт) и `_pipeline_check_invariants` (fail-closed инварианты K7).
`run_pipeline` остался оркестратором и ужат 399 -> 162 строки. Поведение не менялось (чистый вынос):
мутационная проба `security-report-seam-pipeline-uses-projection` осталась дословно в
`_pipeline_build_report` и по-прежнему killed. Потолок func-size `engine/` опущен ратчетом
399 -> 184 (следующий максимум — `_evaluate_security`). In-file вынос по конструкции добавляет
структурную обвязку (сигнатуры/распаковка/return-словари фаз), поэтому файл перешёл порог 700
(663 -> 771) — внесён ОСОЗНАННО в `packages/module-size-baseline.yaml` записью в ленте `raises`,
рационале-комментарии перенесены дословно, а не срезаны ради счётчика строк.
