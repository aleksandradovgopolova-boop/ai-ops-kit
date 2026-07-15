# File Index

Аннотированная карта репозитория для людей и агентов (аналог llms.txt).
Разделы упорядочены от контрактов к инструментам; полный контекст — в `AGENTS.md`.

## Корень

Версия, история, лицензии, видение и roadmap, инструкции для людей и агентов (AGENTS.md/CLAUDE.md).

- `.gitignore`
- `AGENTS.md`
- `APPLY.md`
- `CHANGELOG.md`
- `CLAUDE.md`
- `LICENSE`
- `MIGRATION_GUIDE.md`
- `NOTICE.md`
- `README.md`
- `RELEASE_NOTES_v1.0.0.md`
- `ROADMAP.md`
- `VERSION`
- `VISION.md`

## docs/

Документация для людей: Onboarding (ценность простым языком), Quickstart (+типовые ошибки), Walkthrough (сквозной сценарий), гайд внедрения по ролям, параллельные сессии.

- `docs/ONBOARDING.md`
- `docs/QUICKSTART.md`
- `docs/WALKTHROUGH.md`
- `docs/adoption-guide.md`
- `docs/parallel-sessions.md`

## manifest/

Центральный манифест пакета: версия, реестры, gates, spec-протокол, миграции.

- `manifest/ai-ops-manifest.yaml`

## registry/

Машиночитаемые реестры — источник истины: агенты, workflow-контракты, провайдеры, модели, среды, инструменты, capability-index, routing-policy, entities (Knowledge Graph).

- `registry/agents.yaml`
- `registry/capability-index.yaml`
- `registry/entities.yaml`
- `registry/models.yaml`
- `registry/providers.yaml`
- `registry/routing-policy.yaml`
- `registry/runtimes.yaml`
- `registry/skills-catalog.yaml`
- `registry/tools.yaml`
- `registry/workflows.yaml`

## agents/

51 агент по доменам (core/product/engineering/quality/delivery/meta): ревьюеры полного цикла, команда AI-продукта (llm-architect, ai-feature-engineer, ai-red-teamer, ai-evaluator); каждый зарегистрирован в registry/agents.yaml.

- `agents/README.md`
- `agents/core/context-builder.md`
- `agents/core/development-orchestrator.md`
- `agents/core/final-verifier.md`
- `agents/core/implementation-integrator.md`
- `agents/core/intake-classifier.md`
- `agents/core/plan-reviewer.md`
- `agents/core/repository-explorer.md`
- `agents/core/requirements-writer.md`
- `agents/core/task-planner.md`
- `agents/delivery/documentation-steward.md`
- `agents/delivery/incident-analyst.md`
- `agents/delivery/observability-engineer.md`
- `agents/delivery/release-manager.md`
- `agents/engineering/ai-feature-engineer.md`
- `agents/engineering/backend-developer.md`
- `agents/engineering/database-engineer.md`
- `agents/engineering/devops-engineer.md`
- `agents/engineering/frontend-developer.md`
- `agents/engineering/fullstack-developer.md`
- `agents/engineering/integration-engineer.md`
- `agents/engineering/llm-architect.md`
- `agents/engineering/migration-engineer.md`
- `agents/engineering/solution-architect.md`
- `agents/engineering/system-analyst.md`
- `agents/meta/agent-creator.md`
- `agents/meta/prompt-reviewer.md`
- `agents/meta/repository-memory-curator.md`
- `agents/meta/workflow-designer.md`
- `agents/product/adoption-manager.md`
- `agents/product/business-analyst.md`
- `agents/product/experiment-designer.md`
- `agents/product/product-analyst.md`
- `agents/product/product-manager.md`
- `agents/product/ui-ux-designer.md`
- `agents/product/user-researcher.md`
- `agents/quality/accessibility-reviewer.md`
- `agents/quality/ai-evaluator.md`
- `agents/quality/ai-red-teamer.md`
- `agents/quality/analytics-reviewer.md`
- `agents/quality/architecture-reviewer.md`
- `agents/quality/code-reviewer.md`
- `agents/quality/design-system-reviewer.md`
- `agents/quality/documentation-reviewer.md`
- `agents/quality/observability-reviewer.md`
- `agents/quality/performance-reviewer.md`
- `agents/quality/product-reviewer.md`
- `agents/quality/regression-analyst.md`
- `agents/quality/requirements-reviewer.md`
- `agents/quality/security-reviewer.md`
- `agents/quality/test-engineer.md`
- `agents/quality/ux-reviewer.md`

## quality/

Реестр quality gates: machine-readable контракт с revision-binding; gates полного цикла, включая ai_eval для AI-фич.

- `quality/gates.yaml`

## workflows/

Прозаические сценарии; машиночитаемые контракты — registry/workflows.yaml (MVP + VISUAL/ANALYTICS/INSIGHTS/ADOPTION/AI_FEATURE).

- `workflows/adoption.md`
- `workflows/ai-feature.md`
- `workflows/analytics-instrumentation.md`
- `workflows/architecture-change.md`
- `workflows/bug-fix.md`
- `workflows/database-migration.md`
- `workflows/feature-development.md`
- `workflows/hotfix.md`
- `workflows/incident-resolution.md`
- `workflows/insights.md`
- `workflows/integration-change.md`
- `workflows/refactoring.md`
- `workflows/release.md`
- `workflows/ui-change.md`

## commands/

Команды-точки входа для runtime'ов (ai-start-task, ai-review, ...).

- `commands/engineering/ai-design-solution.md`
- `commands/engineering/ai-fix-bug.md`
- `commands/engineering/ai-refactor.md`
- `commands/maintenance/ai-audit-agents.md`
- `commands/maintenance/ai-create-agent.md`
- `commands/maintenance/ai-update-memory.md`
- `commands/product/ai-create-epic.md`
- `commands/product/ai-create-feature.md`
- `commands/product/ai-design-experiment.md`
- `commands/quality/ai-regression-check.md`
- `commands/quality/ai-release-readiness.md`
- `commands/quality/ai-review.md`
- `commands/task/ai-clarify-task.md`
- `commands/task/ai-discover.md`
- `commands/task/ai-finish-task.md`
- `commands/task/ai-implement.md`
- `commands/task/ai-plan-task.md`
- `commands/task/ai-start-task.md`
- `commands/task/ai-verify.md`

## skills/

Скиллы, поставляемые китом (грузятся раннером из `.claude/skills/`). Реестр — `manifest.skills.shipped`.

- `skills/contradiction-resolution/SKILL.md`
- `skills/decision-support/SKILL.md`
- `skills/e2e-browser-testing/SKILL.md`
- `skills/frontend-design/SKILL.md`
- `skills/product-demo-video/SKILL.md`
- `skills/product-session-review/SKILL.md`
- `skills/system-constraint-analysis/SKILL.md`
- `skills/user-documentation/SKILL.md`

## rules/

Правила: core, ai (EvalPolicy, EvalTooling, red-team-checklist), product, engineering, quality + design (чек-листы Nielsen/WCAG/дизайн-системы/адаптивности), research (разбор сессий), thinking (ограничения, противоречия, решения), meta (конвенция авторинга скиллов).

- `rules/ai/CostAndTokenPolicy.md`
- `rules/ai/EvalPolicy.md`
- `rules/ai/EvalTooling.md`
- `rules/ai/ModelRouting.md`
- `rules/ai/ParallelWork.md`
- `rules/ai/PromptInjectionDefense.md`
- `rules/ai/SecretsAndSensitiveData.md`
- `rules/ai/ToolUsage.md`
- `rules/content/demo-video.yaml`
- `rules/ai/red-team-checklist.yaml`
- `rules/core/AIWorkingAgreement.md`
- `rules/core/ContextManagement.md`
- `rules/core/DefinitionOfDone.md`
- `rules/core/EvidencePolicy.md`
- `rules/core/FreshnessPolicy.md`
- `rules/core/HumanApproval.md`
- `rules/core/ScopeControl.md`
- `rules/core/SourceOfTruth.md`
- `rules/design/accessibility-checklist.yaml`
- `rules/design/design-system-checklist.yaml`
- `rules/design/frontend-design.yaml`
- `rules/design/responsive-baseline.yaml`
- `rules/design/ux-heuristics.yaml`
- `rules/documentation/user-docs.yaml`
- `rules/engineering/APICompatibility.md`
- `rules/engineering/Architecture.md`
- `rules/engineering/CodeStyle.md`
- `rules/engineering/DatabaseChanges.md`
- `rules/engineering/DependencyPolicy.md`
- `rules/engineering/ErrorHandling.md`
- `rules/meta/skill-authoring.yaml`
- `rules/product/MeasurementBaseline.md`
- `rules/research/session-review.yaml`
- `rules/thinking/constraint-analysis.yaml`
- `rules/thinking/contradiction-resolution.yaml`
- `rules/thinking/decision-support.yaml`
- `rules/quality/AccessibilityBaseline.md`
- `rules/quality/code-review-etiquette.yaml`
- `rules/quality/e2e-baseline.yaml`
- `rules/quality/PerformanceBudget.md`
- `rules/quality/QualityGates.md`
- `rules/quality/ReviewPolicy.md`
- `rules/quality/SecurityBaseline.md`
- `rules/quality/TestingStrategy.md`

## templates/

Шаблоны артефактов полного цикла: task, engineering, product (включая adoption-набор), quality (включая AIFeatureEvalPlan), documentation, discovery, ux, analytics, release, monitoring, blueprint, ci.

- `templates/analytics/DashboardSpec.md`
- `templates/analytics/EventSchema.md`
- `templates/analytics/TrackingPlan.md`
- `templates/blueprint/FeatureBlueprint.lean.yaml`
- `templates/blueprint/FeatureBlueprint.yaml`
- `templates/ci/ai-ops-update.yml`
- `templates/decisions/DecisionEpisode.md`
- `templates/decisions/OneWayDoorBrief.md`
- `templates/decisions/OutcomeReview.md`
- `templates/discovery/AssumptionTest.md`
- `templates/discovery/Hypotheses.md`
- `templates/discovery/JTBD.md`
- `templates/discovery/OpportunitySolutionTree.md`
- `templates/discovery/Personas.md`
- `templates/discovery/ProblemStatement.md`
- `templates/discovery/UserResearchPlan.md`
- `templates/documentation/FAQ.md`
- `templates/documentation/InAppContent.md`
- `templates/documentation/ReleaseNotes.md`
- `templates/documentation/Runbook.md`
- `templates/documentation/UserGuide.md`
- `templates/documentation/WhatsNew.md`
- `templates/engineering/ADR.md`
- `templates/engineering/AIFeatureSpec.md`
- `templates/engineering/APIContract.md`
- `templates/engineering/DataMigrationPlan.md`
- `templates/engineering/IntegrationContract.md`
- `templates/engineering/SolutionDesign.md`
- `templates/meta/AgentTemplate.md`
- `templates/monitoring/MonitoringSpec.md`
- `templates/product/AdoptionPlan.md`
- `templates/product/Epic.md`
- `templates/product/Experiment.md`
- `templates/product/ExperimentReadout.md`
- `templates/product/Feature.md`
- `templates/product/FeedbackLoop.md`
- `templates/product/LaunchPlan.md`
- `templates/product/PostLaunchReview.md`
- `templates/product/ProductAnalyticsPlan.md`
- `templates/product/UserStory.md`
- `templates/quality/AIFeatureEvalPlan.md`
- `templates/quality/CodeReview.md`
- `templates/quality/GoldenDataset.md`
- `templates/quality/RedTeamReport.md`
- `templates/quality/ReleaseChecklist.md`
- `templates/quality/SecurityReview.md`
- `templates/quality/TestPlan.md`
- `templates/quality/TestReport.md`
- `templates/quality/VerificationEvidence.md`
- `templates/release/FeatureFlag.md`
- `templates/release/RollbackStrategy.md`
- `templates/release/RolloutPlan.md`
- `templates/runtime/runtime-binding.example.yaml` — child объявляет, чем закрывает контракт persistent-agent-runtime (v2.21)
- `templates/task/Retrospective.md`
- `templates/task/TaskBrief.md`
- `templates/task/TaskContext.md`
- `templates/task/TaskHandoff.md`
- `templates/task/TaskPlan.md`
- `templates/task/TaskResult.md`
- `templates/task/TaskState.md`
- `templates/ux/DesignReview.md`
- `templates/ux/ScreenStates.md`
- `templates/ux/UXFlow.md`

## context/

Карта знаний о продукте/системе/команде; источники истины DesignSystem.md и MetricCatalog.md — заполняются в child-репозитории.

- `context/README.md`
- `context/now.md`
- `context/product/BusinessRules.md`
- `context/product/DesignSystem.md`
- `context/product/MetricCatalog.md`
- `context/product/ProductMetrics.md`
- `context/product/ProductOverview.md`
- `context/product/UsersAndRoles.md`
- `context/system/DataMap.md`
- `context/system/IntegrationMap.md`
- `context/system/RepositoryMap.md`
- `context/system/SystemOverview.md`
- `context/team/DevelopmentProcess.md`
- `context/team/Glossary.md`
- `context/team/OwnershipMap.md`

## runtime/

Спецификация постоянного агента-ассистента (Robin), runtime-агностичная (v2.21). Кит даёт контракт+спеку+валидатор; привязка к конкретному рантайму — на уровне child.

- `runtime/robin/ROBIN.md` — спека Робина (read-mostly, память curated/staged→promoted, audit-log, kill-switch, когда внедрять)
- `runtime/robin/duties.example.yaml` — пример декларативных обязанностей (проверяется validate_duties.py)

## knowledge/

Knowledge Integrity (v2.9): claims — утверждения документации о коде, проверяемые детерминированно (validate_claims.py). В child claims живут в `.ai/project/knowledge/`.

- `knowledge/claims.yaml`

## decisions/

Decision Intelligence (v2.10): реестр решений — принципы (способ мышления), эпизоды, исходы; recommendation-first + one-way-door. В child живёт в `.ai/project/decisions/`.

- `decisions/registry.yaml`

## governance/

Границы данных и безопасность: что можно/нельзя хранить и передавать внешним моделям; постура безопасности (карта по 13 областям, security-posture.yaml) и политики (security-policies.md).

- `governance/information-boundaries.md`
- `governance/security-policies.md`
- `governance/security-posture.yaml`

## memory/

Repository memory: decisions/patterns/incidents/known-issues/lessons-learned; пополняется стадией memory-capture (см. memory/README.md).

- `memory/README.md`
- `memory/decisions/README.md`
- `memory/incidents/README.md`
- `memory/known-issues/README.md`
- `memory/lessons-learned/2026-07-09-first-child-run-insights.md`
- `memory/lessons-learned/2026-07-09-routing-unaware-of-new-workflows.md`
- `memory/lessons-learned/README.md`
- `memory/patterns/README.md`

## evaluations/

Стандарт eval-кейсов; кейсы агентов — в evaluations/agents/ (проверяет CI-гейт).

- `evaluations/AgentEvaluationCase.md`
- `evaluations/README.md`
- `evaluations/WorkflowEvaluationCase.md`
- `evaluations/agents/README.md`
- `evaluations/agents/accessibility-reviewer.md`
- `evaluations/agents/adoption-manager.md`
- `evaluations/agents/agent-creator.md`
- `evaluations/agents/ai-evaluator.md`
- `evaluations/agents/ai-feature-engineer.md`
- `evaluations/agents/ai-red-teamer.md`
- `evaluations/agents/analytics-reviewer.md`
- `evaluations/agents/architecture-reviewer.md`
- `evaluations/agents/backend-developer.md`
- `evaluations/agents/business-analyst.md`
- `evaluations/agents/code-reviewer.md`
- `evaluations/agents/context-builder.md`
- `evaluations/agents/database-engineer.md`
- `evaluations/agents/design-system-reviewer.md`
- `evaluations/agents/development-orchestrator.md`
- `evaluations/agents/devops-engineer.md`
- `evaluations/agents/documentation-reviewer.md`
- `evaluations/agents/documentation-steward.md`
- `evaluations/agents/experiment-designer.md`
- `evaluations/agents/final-verifier.md`
- `evaluations/agents/frontend-developer.md`
- `evaluations/agents/fullstack-developer.md`
- `evaluations/agents/implementation-integrator.md`
- `evaluations/agents/incident-analyst.md`
- `evaluations/agents/intake-classifier.md`
- `evaluations/agents/integration-engineer.md`
- `evaluations/agents/llm-architect.md`
- `evaluations/agents/migration-engineer.md`
- `evaluations/agents/observability-engineer.md`
- `evaluations/agents/observability-reviewer.md`
- `evaluations/agents/performance-reviewer.md`
- `evaluations/agents/plan-reviewer.md`
- `evaluations/agents/product-analyst.md`
- `evaluations/agents/product-manager.md`
- `evaluations/agents/product-reviewer.md`
- `evaluations/agents/prompt-reviewer.md`
- `evaluations/agents/regression-analyst.md`
- `evaluations/agents/release-manager.md`
- `evaluations/agents/repository-explorer.md`
- `evaluations/agents/repository-memory-curator.md`
- `evaluations/agents/requirements-reviewer.md`
- `evaluations/agents/requirements-writer.md`
- `evaluations/agents/security-reviewer.md`
- `evaluations/agents/solution-architect.md`
- `evaluations/agents/system-analyst.md`
- `evaluations/agents/task-planner.md`
- `evaluations/agents/test-engineer.md`
- `evaluations/agents/ui-ux-designer.md`
- `evaluations/agents/user-researcher.md`
- `evaluations/agents/ux-reviewer.md`
- `evaluations/agents/workflow-designer.md`

## presets/

Декларативные наборы агентов по id (core, software-product, product-discovery, product-adoption, ai-product, data-and-integrations).

- `presets/ai-product.yaml`
- `presets/core.yaml`
- `presets/data-and-integrations.yaml`
- `presets/product-adoption.yaml`
- `presets/product-discovery.yaml`
- `presets/software-product.yaml`

## schemas/

JSON Schema публичных контрактов: gate-result, route-decision, child-config, feature-blueprint, knowledge-graph, product-health, update-result и др.

- `schemas/capability-entry.schema.json`
- `schemas/child-config.schema.json`
- `schemas/decisions-registry.schema.json`
- `schemas/feature-blueprint.schema.json`
- `schemas/gate-evidence.schema.json`
- `schemas/gate-result.schema.json`
- `schemas/knowledge-graph.schema.json`
- `schemas/package-manifest.schema.json`
- `schemas/product-health.schema.json`
- `schemas/provenance.schema.json`
- `schemas/provider-entry.schema.json`
- `schemas/registry-entity.schema.json`
- `schemas/route-decision.schema.json`
- `schemas/runtime-entry.schema.json`
- `schemas/update-result.schema.json`
- `schemas/workflow.schema.json`
- `schemas/workitem.schema.json`

## security/

Уровни разрешений и boundary-модель managed/project/custom.

- `security/boundary-model.md`
- `security/permission-levels.yaml`

## config/

Конфигурации по умолчанию: model-routing, quality-gates, protected-paths, tool-permissions.

- `config/agents.yaml`
- `config/model-routing.yaml`
- `config/protected-paths.yaml`
- `config/quality-gates.yaml`
- `config/tool-permissions.yaml`

## openspec/

Интеграция OpenSpec (включена по умолчанию, opt-out): change-template, extension-схемы.

- `openspec/README.md`
- `openspec/change-template/README.md`
- `openspec/change-template/change.yaml`
- `openspec/change-template/checklists/.gitkeep`
- `openspec/change-template/decisions/.gitkeep`
- `openspec/change-template/design.md`
- `openspec/change-template/evidence/.gitkeep`
- `openspec/change-template/execution/README.md`
- `openspec/change-template/gates/.gitkeep`
- `openspec/change-template/learning/LearningPatch.md`
- `openspec/change-template/proposal.md`
- `openspec/change-template/requirements.md`
- `openspec/change-template/specs/example-capability/spec.md`
- `openspec/change-template/tasks.md`
- `openspec/change-template/verification.md`
- `openspec/schemas/product/schema.yaml`
- `openspec/schemas/research/schema.yaml`

## platform-guides/

Краткие руководства по подключению конкретных runtime'ов.

- `platform-guides/claude-code.md`
- `platform-guides/codex.md`
- `platform-guides/github-copilot.md`
- `platform-guides/roo-code.md`
- `platform-guides/zcode.md`

## validation/

Валидаторы и self-test'ы — запускаются в CI, все должны быть PASS (см. AGENTS.md).

- `validation/ai_capability_selftest.py`
- `validation/ai_managed_checksums.py`
- `validation/ai_route.py`
- `validation/validate_agent_evals.py`
- `validation/validate_agents_checklist.py`
- `validation/validate_ai_first_config.py`
- `validation/validate_ai_first_providers.py`
- `validation/validate_ai_first_registry.py`
- `validation/validate_ai_first_workflows.py`
- `validation/validate_ai_ops_child.py`
- `validation/validate_claims.py`
- `validation/validate_cross_artifacts.py`
- `validation/validate_decisions.py`
- `validation/validate_duties.py` — обязанности постоянного агента Robin (v2.21)
- `validation/validate_feature_blueprint.py`
- `validation/validate_freshness.py`
- `validation/validate_knowledge_graph.py`
- `validation/validate_openspec_change.py`
- `validation/validate_presets.py`
- `validation/validate_references.py`
- `validation/validate_security_posture.py`
- `validation/validate_stale_gates.py`
- `validation/validate_workflow_gates.py`

## tools/

Генераторы (runtime-команды, артефакты по blueprint), sequential-оркестратор, gate executor (исполнение и блокировка quality gates), Product Health, run_report (оценка прогона + история срезов), effect_metrics (метрики эффекта).

- `tools/effect_metrics.py`
- `tools/gate_executor.py`
- `tools/generate_artifacts.py`
- `tools/generate_runtime.py`
- `tools/orchestrator.py`
- `tools/product_health.py`
- `tools/run_report.py`
- `tools/workitem.py`

## installer/

CLI ai-ops: init/status/diff/update/validate/doctor/migrate для child-репозиториев.

- `installer/ai_ops.py`

## migrations/

Механизм миграций между версиями пакета.

- `migrations/README.md`
- `migrations/_template/down.py`
- `migrations/_template/up.py`

## examples/

Примеры: child-конфиг, openspec-demo, feature-blueprint-demo, knowledge-graph-demo, product-health-demo (все проходят свои валидаторы в CI).

- `examples/child-config.example.yaml`
- `examples/child-install/.ai/custom/.gitkeep`
- `examples/child-install/.ai/generated/.gitkeep`
- `examples/child-install/.ai/managed/.checksums.json`
- `examples/child-install/.ai/managed/.provenance.json`
- `examples/child-install/.ai/managed/core/rules/ExampleScopeControl.md`
- `examples/child-install/.ai/project/.gitkeep`
- `examples/child-install/.ai/runtime/.gitkeep`
- `examples/child-install/README.md`
- `examples/feature-blueprint-demo/express-checkout/analytics/dashboard-spec.md`
- `examples/feature-blueprint-demo/express-checkout/analytics/tracking-plan.md`
- `examples/feature-blueprint-demo/express-checkout/blueprint.yaml`
- `examples/feature-blueprint-demo/express-checkout/discovery/hypotheses.md`
- `examples/feature-blueprint-demo/express-checkout/discovery/problem-statement.md`
- `examples/feature-blueprint-demo/express-checkout/prd/feature.md`
- `examples/feature-blueprint-demo/express-checkout/ux/ux-flow.md`
- `examples/knowledge-graph-demo/graph.yaml`
- `examples/openspec-demo/openspec/changes/add-csv-export/proposal.md`
- `examples/openspec-demo/openspec/changes/add-csv-export/specs/reports/spec.md`
- `examples/openspec-demo/openspec/changes/add-csv-export/tasks.md`
- `examples/openspec-demo/openspec/specs/reports/spec.md`
- `examples/product-health-demo/input.yaml`

## .github/

CI пакета (package-quality) и релизный workflow (release.yml: VERSION в main -> тег + Release).

- `.github/workflows/package-quality.yml`
- `.github/workflows/release.yml`
