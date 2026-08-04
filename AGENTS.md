# AGENTS.md — инструкция для AI-агентов, работающих с этим репозиторием

Это **AI Ops Kit** — переиспользуемый пакет (parent) AI-first операционной системы для
команд: агенты, workflow-контракты, quality gates, маршрутизация, управляемые обновления
child-репозиториев. Здесь разрабатывается сам пакет; в продуктовые репозитории он
устанавливается через `installer/ai_ops.py init`.

## Карта репозитория

| Зона | Что это | Менять можно? |
|---|---|---|
| `registry/` | Машиночитаемые реестры: агенты, workflow-контракты, провайдеры, модели, среды, capability-index, routing-policy | Да, но только синхронно с файлами, на которые они ссылаются |
| `agents/` | 51 агент (markdown) | Да; новый/изменённый агент требует записи в `registry/agents.yaml` и eval-кейсов в `evaluations/agents/` |
| `quality/gates.yaml` | Реестр quality gates | Да, blocking-гейтов MVP ≤ 8 |
| `workflows/`, `commands/`, `rules/`, `templates/`, `context/`, `memory/` | Прозаический слой | Да |
| `schemas/` | JSON Schema контрактов | Осторожно: это публичные контракты, breaking — только major |
| `validation/`, `tools/` | Валидаторы и инструменты (Python, только pyyaml) | Да, каждому инструменту — selftest |
| `installer/ai_ops.py` | CLI `ai-ops` для child-репозиториев | Да |
| `manifest/ai-ops-manifest.yaml` | Центральный манифест пакета | `package_version` — только при релизе |
| `packages/` | Декларации границ 5 пакетов 3.0 (файл→пакет, зависимости) — БЕЗ переноса файлов (3.0-срез 0) | Синхронно с `validate_package_boundaries.py` |
| `qualification/` | Пакет живых сценариев для квалификации движка (данные) | Синхронно с `validate_qualification.py` |
| `containers/` | Эталонный контейнер изоляции движка (P0.2 jail): Dockerfile + run-sandboxed.sh | Синхронно с `validate_container_assets.py` |
| `VERSION`, `CHANGELOG.md` | Версия и история (SemVer) | Только при релизе |

Полный аннотированный список файлов — в `FILE_INDEX.md`.

## Быстрый инженерный цикл (lean)

Правило дня: инвариант формулируется ДО реализации, а не после. Проверок в CI уже десятки —
проблема не в их количестве, а в том, что нужный шов иногда осознаётся постфактум (напр. rc2:
scope-тест проходил вхолостую → фикс тронул только mock → предположение теста различалось
Linux/macOS — три итерации одного класса ошибки). Цикл ниже ловит это в первом PR. Без новых
подсистем/валидаторов — это процесс, не код.

**1. Change Brief (8–10 строк) ДО кода** — обязательный блок в задаче/PR (шаблон:
`templates/quality/ChangeBrief.md`). Не начинать писать код, пока не перечислены ВСЕ затронутые
сквозные пути. Поля: Результат / Затрагиваемые пути / Инварианты / Failure modes (≤5) /
Доказательство / Не входит.

**2. Три обязательных теста на каждую значимую capability (до реализации):**
- positive — механизм реально делает действие;
- fail-closed — сбой НЕ превращается в зелёный результат;
- **side-effect proof** — проверяемое действие ДЕЙСТВИТЕЛЬНО произошло, ПРЕЖДЕ чем проверять
  реакцию гейта. Пример (scope): сперва доказать «коммит создан ∧ HEAD сменился ∧ diff непуст ∧
  запрещённый файл реально изменён», и только потом — что gate заблокировал. Иначе тест зелёный
  вхолостую.
- Environment-тест (Git/FS/сеть/ОС/внешний CLI) добавляется ТОЛЬКО для такого кода, не на каждую
  обычную функцию. Для Git/concurrency локально гонять и `GIT_CONFIG_GLOBAL=/dev/null` (CI-Linux
  без идентичности), и нативный macOS smoke. Полная OS×Python-матрица сейчас НЕ нужна.

**3. Один свежий review до merge** — одна AI-сессия БЕЗ авторского контекста, ≤5 находок, одна
итерация исправлений. Проверяет: заявленный пользовательский результат, 5 failure modes,
исполнение инвариантов, ОТСУТСТВИЕ пустых тестов, связность слоёв, соответствие заявлений runtime.
Остался P0/P1 после итерации → PR блокируется и перепланируется; P2 → backlog.

**4. Не гонять полный цикл после каждой правки:** во время разработки — целевой self-test
изменяемого контура; перед PR — короткий core smoke; в PR — полный существующий CI ОДИН раз.

**Рефакторинг — правило третьего изменения:** общий компонент выделяем, только когда один и тот же
шов протягивается через несколько модулей В ТРЕТИЙ раз (кандидаты, когда/если дойдёт: provider
fallback → `failure_policy.py`; strict security → `security_decision.py`; доставка single/parallel
→ `delivery_controller.py`). Не рефакторить «на будущее», особенно перед RC/stable.

**Минимальные метрики (следующие 5 значимых PR):** первый CI зелёный? · сколько fix-коммитов? ·
сколько review-итераций? · найден ли дефект после merge? Если стабильно 2–3 фикса на класс — этот
шов в общий helper/guard.

**Отложено (кандидат в отдельный PR; 3.8 stable пройден):** `tools/dev_check.py` (`quality-fast`) —
статические профили `--core/--parallel/--security` из 8–12 критичных self-test ядра (ai_ops_run,
execution_pipeline, workpackage_executor, parallel_executor, parallel_live, lifecycle_store,
pr_open, security_enforcement, model_router, provider_endpoints). Не заменяет CI — быстрый ответ
в разработке. Без анализа изменённых файлов/dependency-graph сейчас.

## Перед коммитом — обязательно

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS:

```bash
python3 validation/validate_ai_first_registry.py
python3 validation/validate_ai_first_workflows.py
python3 validation/validate_ai_first_config.py
python3 validation/validate_ai_first_providers.py
python3 validation/ai_route.py --selftest
python3 validation/ai_capability_selftest.py
python3 validation/validate_stale_gates.py --selftest
python3 tools/generate_runtime.py --selftest
python3 validation/validate_runtime_surface.py --selftest
python3 tools/architecture_baseline.py --selftest
python3 tools/generate_artifacts.py --selftest
python3 tools/run_report.py --selftest
python3 tools/effect_metrics.py --selftest
python3 tools/orchestrator.py --selftest
python3 tools/budget.py --selftest
python3 tools/tool_loop.py --selftest
python3 tools/gitio.py --selftest
python3 tools/lifecycle_store.py --selftest
python3 tools/execution_pipeline.py --selftest
python3 tools/pr_open.py --selftest
python3 tools/gate_executor.py --selftest
python3 validation/validate_reviewer_result.py --selftest
python3 tools/tool_broker.py --selftest
python3 tools/security_scan.py --selftest
python3 tools/context_compiler.py --selftest
python3 validation/validate_context_bundle.py --selftest
python3 tools/spec_levels.py --selftest
python3 validation/validate_spec_coverage.py --selftest
python3 tools/run_handoff.py --selftest
python3 validation/validate_run_handoff.py --selftest
python3 tools/atomic_planner.py --selftest
python3 tools/security_pack.py --selftest
python3 validation/validate_security_domains.py --selftest
python3 validation/validate_security_domains.py
python3 tools/ai_ops_cli.py --selftest
python3 validation/validate_context_qualification.py
python3 validation/validate_product_qualification.py
python3 validation/validate_workflow_gates.py --selftest
python3 validation/validate_workflow_gates.py
python3 validation/validate_scenario_evidence.py --selftest
python3 validation/validate_bootstrap_qualification.py --selftest
python3 validation/validate_bootstrap_qualification.py
python3 validation/validate_surface_wiring.py --selftest
python3 tools/workitem.py --selftest
python3 tools/run_plan.py --selftest
python3 tools/run_plan.py validate
python3 tools/ai_ops_run.py --selftest
python3 tools/bench_lite.py --selftest
python3 tools/gate_policy.py --selftest
python3 tools/gate_result_v2.py --selftest
python3 tools/storybook_adapter.py --selftest
python3 validation/validate_storybook_evidence.py --selftest
python3 validation/validate_architecture_decision.py --selftest
python3 validation/validate_adr_registry.py --selftest
python3 validation/validate_adr_registry.py
python3 validation/validate_quality_attributes.py --selftest
python3 validation/validate_quality_attributes.py
python3 tools/evolution_triggers.py --selftest
python3 validation/validate_feature_learning.py --selftest
python3 validation/validate_feature_learning.py
python3 validation/validate_learning_loop.py --selftest
python3 validation/validate_learning_loop.py
python3 validation/validate_context_architecture.py --selftest
python3 validation/validate_loop_policy.py --selftest
python3 validation/validate_work_graph.py --selftest
python3 validation/validate_work_graph.py examples/work-graph-demo
python3 validation/validate_budget_contract.py --selftest
python3 validation/validate_budget_contract.py examples/budget-demo
python3 validation/validate_capability_scope.py --selftest
python3 validation/validate_capability_scope.py examples/capability-demo
python3 validation/validate_access_filter.py --selftest
python3 validation/validate_access_filter.py examples/access-filter-demo
python3 validation/validate_provider_residency.py --selftest
python3 validation/validate_provider_residency.py examples/residency-demo
python3 tools/cost_account.py --selftest
python3 tools/model_comparison.py --selftest
python3 tools/model_comparison.py examples/model-comparison-demo
python3 validation/validate_model_roles.py --selftest
python3 validation/validate_model_roles.py
python3 validation/validate_model_qualification.py --selftest
python3 validation/validate_model_qualification.py
python3 tools/security_review_cascade.py --selftest
python3 validation/validate_release_claims.py --selftest
python3 validation/validate_release_claims.py
python3 tools/usage_ledger.py --selftest
python3 tools/session_telemetry.py --selftest
python3 tools/session_guardrails.py --selftest
python3 tools/session_boundary.py --selftest
python3 tools/delegation_advisor.py --selftest
python3 tools/cost_method.py --selftest
python3 tools/commit_policy.py --selftest
python3 tools/branch_policy.py --selftest
python3 validation/validate_engops_policy.py --selftest
python3 validation/validate_engops_policy.py
python3 tools/environment_map.py --selftest
python3 tools/deploy_readiness.py --selftest
python3 tools/economic_preflight.py --selftest
python3 tools/ui_readiness.py --selftest
python3 tools/model_router.py --selftest
python3 tools/provider_endpoints.py --selftest
python3 tools/parallel_live.py --selftest
python3 validation/validate_regression_corpus.py --selftest
python3 validation/validate_regression_corpus.py
python3 validation/validate_loop_trace.py --selftest
python3 validation/validate_loop_trace.py examples/loop-trace-demo
python3 validation/validate_integration_trace.py --selftest
python3 validation/validate_integration_trace.py examples/integration-trace-demo
python3 validation/validate_post_release_readout.py --selftest
python3 validation/validate_post_release_readout.py examples/readout-demo
python3 tools/repo_graph.py --selftest
python3 tools/data_classification.py --selftest
python3 tools/context_retrieval.py --selftest
python3 tools/semantic_lite.py --selftest
python3 tools/context_engine.py --selftest
python3 tools/context_promotion_gate.py --selftest
python3 tools/context_hybrid.py --selftest
python3 tools/context_shadow.py --selftest
python3 tools/retrieval_bench.py --selftest
python3 tools/gate_runtime.py --selftest
python3 tools/parallel_planner.py --selftest
python3 tools/parallel_planner.py examples/work-graph-demo
python3 tools/parallel_executor.py --selftest
python3 tools/storybook_query.py --selftest
python3 tools/seam_scan.py --selftest
python3 tools/ui_evidence_collect.py --selftest
python3 tools/project_detector.py --selftest
python3 tools/evidence_collector.py --selftest
python3 tools/active_work.py --selftest
python3 tools/worktree.py --selftest
python3 tools/merge_memory.py --selftest
python3 tools/concurrency_preflight.py --selftest
python3 tools/qual_run.py --selftest
python3 validation/validate_python_compat.py --selftest
python3 validation/validate_python_compat.py
python3 validation/validate_event_catalog.py --selftest
python3 validation/validate_event_catalog.py examples/event-catalog-demo/events.yaml
python3 validation/validate_security_posture.py --selftest
python3 validation/validate_security_posture.py
python3 validation/validate_supply_chain.py --selftest
python3 validation/validate_supply_chain.py
python3 validation/validate_memory_governance.py --selftest
python3 validation/validate_memory_governance.py
python3 validation/validate_key_lifecycle.py --selftest
python3 validation/validate_key_lifecycle.py
python3 tools/security_enforcement.py --selftest
python3 tools/security_enforcement.py --key-preflight examples/key-lifecycle-demo/KLP-001.yaml
python3 validation/validate_duties.py --selftest
python3 validation/validate_duties.py
python3 validation/validate_presets.py
python3 validation/validate_agent_evals.py
python3 validation/validate_agent_evals.py --selftest
python3 validation/validate_agent_evals.py --all
python3 validation/validate_openspec_change.py examples/openspec-demo
python3 validation/validate_feature_blueprint.py --selftest
python3 validation/validate_feature_blueprint.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_cross_artifacts.py --selftest
python3 validation/validate_cross_artifacts.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_knowledge_graph.py --selftest
python3 validation/validate_knowledge_graph.py examples/knowledge-graph-demo/graph.yaml
python3 tools/product_health.py --selftest
python3 tools/product_health.py examples/product-health-demo/input.yaml
python3 validation/validate_references.py
python3 validation/validate_claims.py --selftest
python3 validation/validate_claims.py
python3 validation/validate_freshness.py --selftest
python3 validation/validate_freshness.py context
python3 validation/validate_context_completeness.py --selftest
python3 tools/context_cost.py --selftest
python3 validation/validate_decisions.py --selftest
python3 validation/validate_decisions.py
python3 validation/validate_agents_checklist.py --selftest
python3 validation/validate_agents_checklist.py
python3 validation/validate_package_boundaries.py --selftest
python3 validation/validate_package_boundaries.py
python3 validation/validate_standalone_engine.py --selftest
python3 validation/validate_qualification.py --selftest
python3 validation/validate_qualification.py
python3 validation/validate_promotion_qualification.py --selftest
python3 validation/validate_promotion_qualification.py
python3 tools/promotion_qual.py --selftest
python3 tools/promotion_qual.py --verify-negatives
python3 validation/validate_stack_qualification.py --selftest
python3 validation/validate_pipeline_e2e.py --selftest
python3 validation/validate_requirements_artifact.py --selftest
python3 validation/validate_plan_artifact.py --selftest
python3 validation/validate_spec_artifact.py --selftest
python3 validation/validate_container_assets.py --selftest
python3 validation/validate_container_assets.py
python3 validation/validate_container_delivery.py
python3 tools/preflight.py --selftest
python3 tools/approvals.py --selftest
python3 tools/review_branch.py --selftest
python3 tools/workpackage_executor.py --selftest
python3 installer/ai_ops.py --selftest
python3 validation/validate_research_artifacts.py --selftest
python3 validation/validate_research_artifacts.py
python3 .research/tools/verify_quotes.py --selftest
python3 .research/tools/freshness_sweep.py --selftest
python3 .research/tools/ev_scaffold.py --selftest
```

## Ключевые инварианты (валидаторы их проверяют, но знать заранее дешевле)

- **Registry — источник истины.** Файл агента без записи в `registry/agents.yaml` (и наоборот) — ошибка.
- **Capability-декларации честные.** В `registry/runtimes.yaml` и `capability-index.yaml`
  нельзя объявлять возможности, не реализованные в коде; для планов — `status: unsupported` + note "planned".
- **Writer ≠ judge.** В workflow-контрактах стадия с `review_mode: read-only` не может быть writer'ом.
- **Стадии ссылаются только на существующие agent id и gate id.**
- **Никаких новых зависимостей** без явного решения: Python-инструменты работают на stdlib + pyyaml.
- **Язык документации — русский**, идентификаторы и ключи — английские.
- **Три кольца (owner-review 2026-07-30, см. `qualification/bootstrap/v3.8.0-plan.yaml` → `architecture_rings`).**
  Kernel (Task→Context→Execution→Evidence→Decision→Delivery) НЕ зависит от Intelligence (research/
  product-learning/аналитика); Intelligence зависит от Kernel и ЧИТАЕТ его события. Governance подключается
  ПО РИСКУ, не на каждой задаче. Изменение продукта не должно требовать заполнения исследовательской онтологии.
- **Runtime через адаптер, не замена.** AI Ops управляет исполнителем (Claude Code/Codex/OpenHands SDK/…)
  через адаптер; workflow/approvals/evidence не переписываются при смене runtime. Свой tool-loop не наращиваем,
  если внешний runtime делает это надёжно.
- **Capability_freeze (3.8): СНЯТ — 3.8 stable достигнут.** В 3.9 аддитивно добавлены first-class Claude Code
  executing adapter + complexity-aware routing (доказаны live). Новые концепт-возможности — ПО ДАННЫМ реальных
  прогонов (3.10 Real-Product Qualification), а не по красоте; точечно и аддитивно.

## Релизный процесс

1. Обновить `VERSION`, `manifest/ai-ops-manifest.yaml -> ai_ops.package_version`
   и добавить раздел `## [X.Y.Z] — дата` в `CHANGELOG.md`.
2. Коммит `release: AI Ops Kit vX.Y.Z` в `main`.
3. Тег `vX.Y.Z` и GitHub Release создаёт автоматически `.github/workflows/release.yml`
   (по изменению VERSION в main; текст — раздел CHANGELOG). Руками теги не создавать.
