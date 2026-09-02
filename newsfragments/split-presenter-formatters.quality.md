Слой коммуникации разрежён: группа переводчиков повседневных команд (`from_execution_preview`,
`from_onboarding_profile`, `from_new_feature`, `from_plan_built`, `from_specification`,
`from_discovery_draft`, `from_review`, `from_advice` и константа `_CMD_RU`) вынесена из
god-модуля `ai_ops_kit/ui/presenter.py` (1497 -> 1180 строк) в модуль-сосед
`ai_ops_kit/ui/presenter_formatters.py`. Поведение не меняется — чистый перенос плюс ленивый
ре-экспорт (PEP 562 `__getattr__`), поэтому все вызовы `presenter.from_review(...)` продолжают
работать, а цикла импорта нет ни в одном порядке загрузки.
