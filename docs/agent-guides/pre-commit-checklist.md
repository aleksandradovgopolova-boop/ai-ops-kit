# Перед коммитом — полный список проверок

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS.

```bash
python3 validation/ai_capability_selftest.py
python3 tools/pr_open.py --selftest
python3 tools/run_plan.py validate
python3 tools/gate_result_v2.py --selftest
python3 validation/validate_work_graph.py examples/work-graph-demo
python3 validation/validate_budget_contract.py examples/budget-demo
python3 validation/validate_capability_scope.py examples/capability-demo
python3 validation/validate_access_filter.py examples/access-filter-demo
python3 validation/validate_provider_residency.py examples/residency-demo
python3 tools/model_comparison.py examples/model-comparison-demo
python3 tools/branch_policy.py --selftest
python3 validation/validate_loop_trace.py examples/loop-trace-demo
python3 validation/validate_integration_trace.py examples/integration-trace-demo
python3 validation/validate_post_release_readout.py examples/readout-demo
python3 tools/parallel_planner.py examples/work-graph-demo
python3 validation/validate_event_catalog.py examples/event-catalog-demo/events.yaml
python3 tools/security_enforcement.py --key-preflight examples/key-lifecycle-demo/KLP-001.yaml
python3 validation/validate_agent_evals.py --all
python3 validation/validate_openspec_change.py examples/openspec-demo
python3 validation/validate_feature_blueprint.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_cross_artifacts.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_knowledge_graph.py examples/knowledge-graph-demo/graph.yaml
python3 tools/product_health.py examples/product-health-demo/input.yaml
python3 validation/validate_freshness.py context
python3 validation/validate_agents_checklist.py --selftest
python3 tools/promotion_qual.py --verify-negatives
python3 installer/ai_ops.py --selftest
python3 validation/validate_research_artifacts.py --selftest
python3 .research/tools/verify_quotes.py --selftest
python3 .research/tools/freshness_sweep.py --selftest
python3 .research/tools/ev_scaffold.py --selftest
python3 -m pytest tests/contracts/ -v --tb=short --no-cov
python3 -m pytest tests/contracts/ -v --tb=short
```

## Валидаторы: почему их прогонов здесь больше нет

Все 70 валидаторов запускаются из pytest — `tests/unit/test_validator_runtime_contract.py`
прогоняет каждый ИЗ КОПИИ репозитория (standalone обязан быть зелёным, требующий артефакт —
отказать на пустом вызове), а перенесённые селфтесты живут в `tests/unit/test_<validator>_selftest.py`.
Дублировать те же команды здесь значит гонять одно и то же дважды — ровно то, из-за чего полный
контур занимал девять минут.

## Не входит в чеклист — объявленные исключения

Валидатор, которого нет в списке выше, обязан быть здесь с причиной. Полноту проверяет
`tests/unit/test_checklist_completeness.py`: молчаливо выпасть из чеклиста нельзя, иначе список
и реальный набор валидаторов расходятся — этот класс дрейфа уже дважды ловили на `checks_count`.

- `validation/validate_ai_ops_child.py` — проверяет установку кита в **child-репозиторий**
  (`.ai-ops.yaml`, зоны `.ai/*`, целостность managed-слоя). В репозитории самого кита проверять
  нечего; запускается в child-репо и покрыт `tests/unit/test_installer.py`.
