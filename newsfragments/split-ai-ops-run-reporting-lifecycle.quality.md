God-модуль `ai_ops_kit/engine/ai_ops_run.py` разрежён: отчётность прогона
(`_compile_context_artifacts`, `_add_context_reports`, `_enrich_run_report`, `_review_fix_context`)
и жизненный цикл прогона (`_start_lifecycle`, `_resume_gate`, `_commit_barrier`, `_finalize_run`,
`_finalize_run_cost`, `_deliver`) вынесены в модули-спутники `ai_ops_run_reporting.py` и
`ai_ops_run_lifecycle.py`. Поведение не меняется — чистый перенос + ре-экспорт (`ai_ops_run.<name>`
и `from ai_ops_kit.engine.ai_ops_run import <name>` резолвятся как прежде). Файл сокращён 2173 -> 1479
строк; семь функций с мутационными пробами остались на месте.
