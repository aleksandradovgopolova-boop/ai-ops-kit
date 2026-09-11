Свод статуса после merge-driver plan.yaml (#798): работа `plan-yaml-edits-do-not-conflict-in-parallel`
перенесена в `history/plan-history.yaml` с результатом и pr; исход `kit_edits_do_not_create_conflicts`
цели `team-works-in-parallel` взят (цель остаётся активной — под ней ещё работа сессии ревью). Заодно
уточнён инвариант `next`: работа в статусе `in_progress` — самообъяснимая причина пустого совета
(«уже в работе, не предлагается заново»), а не молчаливое «ничего».
