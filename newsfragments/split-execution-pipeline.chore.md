Монолит `ai_ops_kit/engine/execution_pipeline.py` разрезан на фасад + сателлит
`pipeline_stages.py` (билдеры единого отчёта — loop/commit/containment/delivery/overall/
security-проекция — и стадии прогона: spec-drift, resolve-policy, run-gates, assess-readiness,
check-invariants) для снятия с потолка размера модуля. Чистый структурный рефактор: публичная
поверхность `execution_pipeline.X` сохранена явным ре-экспортом перенесённых имён, обе охранные
пробы (`_deliver_pr` / `_pipeline_build_report`) остались в фасаде, поведение не менялось.
