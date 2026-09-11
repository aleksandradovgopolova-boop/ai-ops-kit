Главный экономический KPI кита теперь считает стоимость успешного ИСХОДА, а не только токены:
`cost_per_successful_outcome` (`providers/cost_account.py`) складывает AI-стоимость и внимание
человека (`manual_interventions` × ставка из дочернего `.ai-ops.yaml`,
`engineering_operating_model.economics.human_attention_cost_per_intervention_usd`). Ставка или число
вмешательств не заданы → внимание человека `unavailable` (не 0), нагруженная стоимость честно
помечена нижней границей; инвариант «провал = чистые потери» сохранён (`cost_per_outcome=None`, если
не доставлено+проверено). Плюс пост-фактум артефакт «работа стоила $X вместо ожидаемых $Y»:
`estimate_vs_actual` сводит оценку до прогона (`economic_preflight`) с фактом и выдаёт дельту —
`rep["cost_delta"]` и `rep["roid_outcome"]` в отчёте прогона. Нет оценки или факта → дельта
`unavailable`, не 0. Достройка поверх готовой экономики (ledger/budget/cost_account). (#637)
