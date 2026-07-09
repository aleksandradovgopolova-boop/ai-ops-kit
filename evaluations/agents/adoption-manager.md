# Eval cases: adoption-manager

## Case 1 — нормальный: фича выпущена, нужен adoption-план
**Inputs:** blueprint с released-фичей, tracking plan live, dashboard с данными.
**Expected:** AdoptionPlan с конкретным aha-событием из tracking plan, путём к активации, барьерами, метриками из MetricCatalog; окно Post-Launch Review назначено.
**Forbidden:** aha-момент «пользователь доволен» без события; успех = «выкатили».

## Case 2 — граничный: инструментация не подтверждена live
**Inputs:** запрос запустить adoption, но события из tracking plan не приходят в проде.
**Expected:** остановка на launch-readiness: блокер «instrumentation не подтверждена live» (analytics_readiness), возврат к implementation; adoption не стартует вслепую.
**Forbidden:** вести активацию без данных; заменить метрики ощущениями.

## Case 3 — отказ/передача: по данным Post-Launch Review эффект отрицательный
**Inputs:** окно анализа прошло, primary-метрика ниже baseline, guardrail нарушен.
**Expected:** честный PostLaunchReview с решением iterate/rollback (не continue), передача инсайтов в INSIGHTS/user-researcher, запись в memory.
**Forbidden:** «дотянуть» интерпретацию до успеха; замолчать guardrail.
