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
python3 tools/generate_artifacts.py --selftest
python3 tools/run_report.py --selftest
python3 tools/effect_metrics.py --selftest
python3 tools/orchestrator.py --selftest
python3 tools/budget.py --selftest
python3 tools/tool_loop.py --selftest
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
python3 validation/validate_workflow_gates.py --selftest
python3 validation/validate_workflow_gates.py
python3 tools/workitem.py --selftest
python3 tools/run_plan.py --selftest
python3 tools/run_plan.py validate
python3 tools/ai_ops_run.py --selftest
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
python3 validation/validate_decisions.py --selftest
python3 validation/validate_decisions.py
python3 validation/validate_agents_checklist.py --selftest
python3 validation/validate_agents_checklist.py
python3 validation/validate_package_boundaries.py --selftest
python3 validation/validate_package_boundaries.py
python3 validation/validate_standalone_engine.py --selftest
python3 validation/validate_qualification.py --selftest
python3 validation/validate_qualification.py
python3 validation/validate_stack_qualification.py --selftest
python3 validation/validate_pipeline_e2e.py --selftest
python3 validation/validate_requirements_artifact.py --selftest
python3 validation/validate_plan_artifact.py --selftest
python3 validation/validate_spec_artifact.py --selftest
python3 validation/validate_container_assets.py --selftest
python3 validation/validate_container_assets.py
python3 validation/validate_container_delivery.py
python3 installer/ai_ops.py --selftest
```

## Ключевые инварианты (валидаторы их проверяют, но знать заранее дешевле)

- **Registry — источник истины.** Файл агента без записи в `registry/agents.yaml` (и наоборот) — ошибка.
- **Capability-декларации честные.** В `registry/runtimes.yaml` и `capability-index.yaml`
  нельзя объявлять возможности, не реализованные в коде; для планов — `status: unsupported` + note "planned".
- **Writer ≠ judge.** В workflow-контрактах стадия с `review_mode: read-only` не может быть writer'ом.
- **Стадии ссылаются только на существующие agent id и gate id.**
- **Никаких новых зависимостей** без явного решения: Python-инструменты работают на stdlib + pyyaml.
- **Язык документации — русский**, идентификаторы и ключи — английские.

## Релизный процесс

1. Обновить `VERSION`, `manifest/ai-ops-manifest.yaml -> ai_ops.package_version`
   и добавить раздел `## [X.Y.Z] — дата` в `CHANGELOG.md`.
2. Коммит `release: AI Ops Kit vX.Y.Z` в `main`.
3. Тег `vX.Y.Z` и GitHub Release создаёт автоматически `.github/workflows/release.yml`
   (по изменению VERSION в main; текст — раздел CHANGELOG). Руками теги не создавать.
