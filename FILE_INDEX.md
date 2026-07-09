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

## manifest/

Центральный манифест пакета: версия, реестры, gates, spec-протокол, миграции.

- `manifest/ai-ops-manifest.yaml`

## registry/

Машиночитаемые реестры — источник истины: агенты, workflow-контракты, провайдеры, модели, среды, инструменты, capability-index, routing-policy.

- `registry/agents.yaml`
- `registry/capability-index.yaml`
- `registry/models.yaml`
- `registry/providers.yaml`
- `registry/routing-policy.yaml`
- `registry/runtimes.yaml`
- `registry/tools.yaml`
- `registry/workflows.yaml`

## agents/

38 агентов по доменам (core/product/engineering/quality/delivery/meta); каждый зарегистрирован в registry/agents.yaml.

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
- `agents/engineering/backend-developer.md`
- `agents/engineering/database-engineer.md`
- `agents/engineering/devops-engineer.md`
- `agents/engineering/frontend-developer.md`
- `agents/engineering/fullstack-developer.md`
- `agents/engineering/integration-engineer.md`
- `agents/engineering/migration-engineer.md`
- `agents/engineering/solution-architect.md`
- `agents/engineering/system-analyst.md`
- `agents/meta/agent-creator.md`
- `agents/meta/prompt-reviewer.md`
- `agents/meta/repository-memory-curator.md`
- `agents/meta/workflow-designer.md`
- `agents/product/business-analyst.md`
- `agents/product/experiment-designer.md`
- `agents/product/product-analyst.md`
- `agents/product/product-manager.md`
- `agents/product/ui-ux-designer.md`
- `agents/quality/accessibility-reviewer.md`
- `agents/quality/code-reviewer.md`
- `agents/quality/performance-reviewer.md`
- `agents/quality/regression-analyst.md`
- `agents/quality/requirements-reviewer.md`
- `agents/quality/security-reviewer.md`
- `agents/quality/test-engineer.md`

## quality/

Реестр quality gates: machine-readable контракт с revision-binding; с v1.3 — gates полного продуктового цикла.

- `quality/gates.yaml`

## workflows/

Прозаические сценарии типовых задач; машиночитаемые контракты — registry/workflows.yaml (MVP + VISUAL/ANALYTICS).

- `workflows/analytics-instrumentation.md`
- `workflows/architecture-change.md`
- `workflows/bug-fix.md`
- `workflows/database-migration.md`
- `workflows/feature-development.md`
- `workflows/hotfix.md`
- `workflows/incident-resolution.md`
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

## rules/

Правила: core (working agreement, source of truth), ai (routing, инъекции, секреты), engineering, quality.

- `rules/ai/CostAndTokenPolicy.md`
- `rules/ai/ModelRouting.md`
- `rules/ai/ParallelWork.md`
- `rules/ai/PromptInjectionDefense.md`
- `rules/ai/SecretsAndSensitiveData.md`
- `rules/ai/ToolUsage.md`
- `rules/core/AIWorkingAgreement.md`
- `rules/core/ContextManagement.md`
- `rules/core/DefinitionOfDone.md`
- `rules/core/EvidencePolicy.md`
- `rules/core/HumanApproval.md`
- `rules/core/ScopeControl.md`
- `rules/core/SourceOfTruth.md`
- `rules/engineering/APICompatibility.md`
- `rules/engineering/Architecture.md`
- `rules/engineering/CodeStyle.md`
- `rules/engineering/DatabaseChanges.md`
- `rules/engineering/DependencyPolicy.md`
- `rules/engineering/ErrorHandling.md`
- `rules/quality/AccessibilityBaseline.md`
- `rules/quality/PerformanceBudget.md`
- `rules/quality/QualityGates.md`
- `rules/quality/ReviewPolicy.md`
- `rules/quality/SecurityBaseline.md`
- `rules/quality/TestingStrategy.md`

## templates/

Шаблоны артефактов полного цикла: task, engineering, product, quality, documentation, discovery, ux, analytics, release, monitoring, blueprint, ci.

- `templates/analytics/DashboardSpec.md`
- `templates/analytics/EventSchema.md`
- `templates/analytics/TrackingPlan.md`
- `templates/blueprint/FeatureBlueprint.yaml`
- `templates/ci/ai-ops-update.yml`
- `templates/discovery/Hypotheses.md`
- `templates/discovery/JTBD.md`
- `templates/discovery/OpportunitySolutionTree.md`
- `templates/discovery/Personas.md`
- `templates/discovery/ProblemStatement.md`
- `templates/documentation/ReleaseNotes.md`
- `templates/documentation/Runbook.md`
- `templates/engineering/ADR.md`
- `templates/engineering/APIContract.md`
- `templates/engineering/DataMigrationPlan.md`
- `templates/engineering/IntegrationContract.md`
- `templates/engineering/SolutionDesign.md`
- `templates/meta/AgentTemplate.md`
- `templates/monitoring/MonitoringSpec.md`
- `templates/product/Epic.md`
- `templates/product/Experiment.md`
- `templates/product/Feature.md`
- `templates/product/ProductAnalyticsPlan.md`
- `templates/product/UserStory.md`
- `templates/quality/CodeReview.md`
- `templates/quality/ReleaseChecklist.md`
- `templates/quality/SecurityReview.md`
- `templates/quality/TestPlan.md`
- `templates/quality/TestReport.md`
- `templates/quality/VerificationEvidence.md`
- `templates/release/FeatureFlag.md`
- `templates/release/RollbackStrategy.md`
- `templates/release/RolloutPlan.md`
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

Карта знаний о продукте/системе/команде — заполняется в child-репозитории.

- `context/README.md`
- `context/product/BusinessRules.md`
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

## memory/

Repository memory: decisions/patterns/incidents/known-issues/lessons-learned; пополняется стадией memory-capture (см. memory/README.md).

- `memory/README.md`
- `memory/decisions/README.md`
- `memory/incidents/README.md`
- `memory/known-issues/README.md`
- `memory/lessons-learned/README.md`
- `memory/patterns/README.md`

## evaluations/

Стандарт eval-кейсов для агентов и workflow; кейсы агентов — в evaluations/agents/ (проверяет CI-гейт).

- `evaluations/AgentEvaluationCase.md`
- `evaluations/README.md`
- `evaluations/WorkflowEvaluationCase.md`
- `evaluations/agents/README.md`

## presets/

Декларативные наборы агентов, подключаемые по id (core, software-product, product-discovery, data-and-integrations).

- `presets/core.yaml`
- `presets/data-and-integrations.yaml`
- `presets/product-discovery.yaml`
- `presets/software-product.yaml`

## schemas/

JSON Schema публичных контрактов: gate-result, route-decision, child-config, feature-blueprint, update-result и др.

- `schemas/capability-entry.schema.json`
- `schemas/child-config.schema.json`
- `schemas/feature-blueprint.schema.json`
- `schemas/gate-result.schema.json`
- `schemas/package-manifest.schema.json`
- `schemas/provenance.schema.json`
- `schemas/provider-entry.schema.json`
- `schemas/registry-entity.schema.json`
- `schemas/route-decision.schema.json`
- `schemas/runtime-entry.schema.json`
- `schemas/update-result.schema.json`
- `schemas/workflow.schema.json`

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
- `validation/validate_ai_first_config.py`
- `validation/validate_ai_first_providers.py`
- `validation/validate_ai_first_registry.py`
- `validation/validate_ai_first_workflows.py`
- `validation/validate_ai_ops_child.py`
- `validation/validate_feature_blueprint.py`
- `validation/validate_openspec_change.py`
- `validation/validate_presets.py`
- `validation/validate_stale_gates.py`

## tools/

Генератор runtime-команд из контрактов и sequential-оркестратор.

- `tools/generate_runtime.py`
- `tools/orchestrator.py`

## installer/

CLI ai-ops: init/status/diff/update/validate/doctor/migrate для child-репозиториев.

- `installer/ai_ops.py`

## migrations/

Механизм миграций между версиями пакета.

- `migrations/README.md`
- `migrations/_template/down.py`
- `migrations/_template/up.py`

## examples/

Примеры: child-конфиг, openspec-demo, feature-blueprint-demo (все проходят свои валидаторы в CI).

- `examples/child-config.example.yaml`
- `examples/child-install/.ai/custom/.gitkeep`
- `examples/child-install/.ai/generated/.gitkeep`
- `examples/child-install/.ai/managed/.checksums.json`
- `examples/child-install/.ai/managed/.provenance.json`
- `examples/child-install/.ai/managed/core/rules/ExampleScopeControl.md`
- `examples/child-install/.ai/project/.gitkeep`
- `examples/child-install/.ai/runtime/.gitkeep`
- `examples/child-install/README.md`
- `examples/feature-blueprint-demo/express-checkout/analytics/tracking-plan.md`
- `examples/feature-blueprint-demo/express-checkout/blueprint.yaml`
- `examples/feature-blueprint-demo/express-checkout/discovery/hypotheses.md`
- `examples/feature-blueprint-demo/express-checkout/discovery/problem-statement.md`
- `examples/feature-blueprint-demo/express-checkout/prd/feature.md`
- `examples/feature-blueprint-demo/express-checkout/ux/ux-flow.md`
- `examples/openspec-demo/openspec/changes/add-csv-export/proposal.md`
- `examples/openspec-demo/openspec/changes/add-csv-export/specs/reports/spec.md`
- `examples/openspec-demo/openspec/changes/add-csv-export/tasks.md`
- `examples/openspec-demo/openspec/specs/reports/spec.md`

## .github/

CI пакета (package-quality) и релизный workflow (release.yml: VERSION в main -> тег + Release).

- `.github/workflows/package-quality.yml`
- `.github/workflows/release.yml`

