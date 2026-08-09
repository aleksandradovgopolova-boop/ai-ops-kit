# File Index

Аннотированная карта репозитория для людей и агентов (аналог llms.txt).
Разделы упорядочены от контрактов к инструментам; полный контекст — в `AGENTS.md`.

## Корень

Версия, история, лицензии, видение и roadmap, инструкции для людей и агентов (AGENTS.md/CLAUDE.md),
сборка пакета и вход в контур проверки.

- `.ai-change-brief.md` — Change Brief текущего среза (по `templates/quality/ChangeBrief.md`)
- `.dockerignore`
- `.gitignore`
- `.pre-commit-config.yaml`
- `AGENTS.md`
- `APPLY.md`
- `CHANGELOG.md`
- `CLAUDE.md`
- `FILE_INDEX.md` — этот файл
- `LICENSE`
- `MIGRATION_GUIDE.md`
- `NOTICE.md`
- `README.md`
- `RELEASE_NOTES_v1.0.0.md`
- `ROADMAP.md`
- `VERSION`
- `VISION.md`
- `mkdocs.yml`
- `pyproject.toml`, `setup.py` — дистрибутив (`pip install -e .`); включает `ai_ops_kit`
- `pytest.ini` — маркеры (в т.ч. `slow`) и addopts контура
- `requirements.txt` (рантайм: только pyyaml), `requirements-dev.txt` (pytest/hypothesis/ruff/mypy)

## scripts/

Единственная точка входа в контур проверки (v3.31.0): построчного чеклиста больше нет.

- `scripts/check-full.sh` — полный контур перед коммитом (~4.5 мин), тот же набор, что в CI
- `scripts/check-fast.sh` — быстрый профиль во время работы (~1 мин, без маркера `slow`)

## docs/

Документация для людей: Onboarding (ценность простым языком), Quickstart (+типовые ошибки), Walkthrough (сквозной сценарий), гайд внедрения по ролям, параллельные сессии.

- `docs/ONBOARDING.md`
- `docs/QUICKSTART.md`
- `docs/WALKTHROUGH.md`
- `docs/adoption-guide.md`
- `docs/parallel-sessions.md`
- `docs/3.0-design.md` — дизайн 3.0: `ai-ops run` основным путём + сплит на 5 пакетов (план, запуск по явному решению)
- `docs/dogfooding-metrics.md` — чеклист обкатки: как метрики (North Star/baseline) закрываются сами через `/ai-run`

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
- `registry/tracks.yaml` — quality tracks: signal->gates (base_workflow + tracks, v2.32)
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
- `commands/task/ai-session-start.md` — session bootstrap новой сессии (v2.22)
- `commands/task/ai-start-task.md`
- `commands/task/ai-run.md` — единый контроллер задачи: route->RunPlan->WorkItem->exec->report (v2.34)
- `commands/task/ai-verify.md`
- `commands/task/ai-worktree.md` — изоляция работы через git worktree (v2.24)

## skills/

Скиллы, поставляемые китом (грузятся раннером из `.claude/skills/`). Реестр — `manifest.skills.shipped`.

- `skills/contradiction-resolution/SKILL.md`
- `skills/decision-support/SKILL.md`
- `skills/e2e-browser-testing/SKILL.md`
- `skills/frontend-design/SKILL.md`
- `skills/product-demo-video/SKILL.md`
- `skills/repo-onboarding/SKILL.md` — первичный онбординг репо -> черновики context/* (v2.22)
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
- `rules/ai/ToolBrokerPolicy.md` — контролируемое исполнение: policy решает, не модель (v2.36)
- `rules/ai/ToolUsage.md`
- `rules/content/demo-video.yaml`
- `rules/ai/red-team-checklist.yaml`
- `rules/core/AIWorkingAgreement.md`
- `rules/core/ContextManagement.md`
- `rules/core/DefinitionOfDone.md`
- `rules/core/DelegationPolicy.md` — культура делегирования разведки сабагенту (v3.17.0)
- `rules/core/EngineeringOperatingModel.md` — операционная гигиена: коммит, ветка (**отставание базы**), окружения, зрелость поставки, **экономическая граница до траты** (v3.19.0–3.21.0, фича закрыта)
- `rules/core/EvidencePolicy.md`
- `rules/core/FreshnessPolicy.md`
- `rules/core/HumanApproval.md`
- `rules/core/ScopeControl.md`
- `rules/core/SessionEconomyPolicy.md` — пороги гигиены контекста сессии + Task Completion Ritual (v3.16.0)
- `rules/core/ProductStatusPolicy.md` — живой статус продукта, читать первым/обновлять на PR (v2.27)
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
- `rules/engineering/ConcurrencyAwareness.md` — осознание параллельной работы, preflight коллизий (v2.28)
- `rules/engineering/ErrorHandling.md`
- `rules/engineering/EventNamingConvention.md` — единое имя события во всех слоях (v2.29)
- `rules/meta/repo-onboarding.yaml` — чек-лист онбординга репозитория (v2.22)
- `rules/meta/skill-authoring.yaml`
- `rules/product/MeasurementBaseline.md`
- `rules/research/session-review.yaml`
- `rules/thinking/constraint-analysis.yaml`
- `rules/thinking/contradiction-resolution.yaml`
- `rules/thinking/decision-support.yaml`
- `rules/quality/AccessibilityBaseline.md`
- `rules/quality/code-review-etiquette.yaml`
- `rules/quality/deploy-readiness.yaml` — чек-лист готовности поставки для гейта `deploy_readiness` (v3.20.0)
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
- `templates/ci/ai-ops-record.yml` — CI-нетто автонакопления срезов эффекта (v2.30)
- `templates/ci/ai-ops-validate.yml` — child-CI валидации: пин kit = installed_version, без protected-трения (v2.35)
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
- `context/product/ProductStatus.md` — живой статус готовности: что реально в проде (v2.27)
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

## product-learning/

FeatureLearning (v3.3.0): DecisionPackage -> гипотеза -> проверка -> verdict -> learnings -> ADR/бэклог.
Схема — `schemas/feature-learning.schema.json`.

- `product-learning/FL-001.yaml`
- `product-learning/FL-002.yaml`
- `product-learning/FL-003.yaml`

## regression-corpus/

Regression Corpus + Failure Taxonomy (v3.5.0): по кейсу на слой отказа — что сломалось, чем ловится,
чтобы класс дефекта не вернулся молча.

- `regression-corpus/RC-001.yaml` … `RC-004.yaml`

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

- `schemas/active-work.schema.json` — реестр активных работ, conflict forecast (v2.22)
- `schemas/capability-entry.schema.json`
- `schemas/child-config.schema.json`
- `schemas/decision-package.schema.json` — research: выходной пакет для принятия решения (research.decision-package, DP-*)
- `schemas/decisions-registry.schema.json`
- `schemas/event-catalog.schema.json` — единый каталог имён событий (v2.29)
- `schemas/feature-blueprint.schema.json`
- `schemas/gate-evidence.schema.json`
- `schemas/gate-result.schema.json`
- `schemas/knowledge-graph.schema.json`
- `schemas/package-manifest.schema.json`
- `schemas/product-health.schema.json`
- `schemas/provenance.schema.json`
- `schemas/provider-entry.schema.json`
- `schemas/registry-entity.schema.json`
- `schemas/research-request.schema.json` — research: входной контракт, decision-first (research.request, RR-*)
- `schemas/research-evidence.schema.json` — research: единица знания с provenance и freshness (research.evidence, EV-*)
- `schemas/reviewer-result.schema.json` — структурный вердикт ревьюера (источник истины, v2.33)
- `schemas/repository-profile.schema.json` — профиль репозитория: стек+команды (v2.41)
- `schemas/run-plan.schema.json` — RunPlan: base_workflow + tracks + агрегированные гейты (v2.32)
- `schemas/route-decision.schema.json`
- `schemas/runtime-entry.schema.json`
- `schemas/update-result.schema.json`
- `schemas/workflow.schema.json`
- `schemas/workitem.schema.json`

## research/

Bounded context «Research» (extractable module): контракты ResearchRequest → Evidence → DecisionPackage, правила изоляции, layout `.research/` для child, roadmap выделения в research-center.

- `research/README.md`
- `research/ACCEPTANCE.md` — acceptance criteria Research v0.2 (12 критериев, все закрыты; зафиксировано 2026-07-23)
- `research/writer-preflight.md` — чек-лист writer'а перед ревью (из накопленных judge-находок; цель — один раунд)

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

## ai_ops_kit/

**Код движка.** 95 модулей в 12 пакетах (v3.31.0). Плоское имя (`tools/<module>.py`) осталось
алиасом через `sys.modules` — ОДИН объект модуля, не копия, поэтому состояние общее и 661
существующий импорт работает без правки. Аннотации отдельных модулей — ниже, в разделе `tools/`.

Правила границ проверяет `tests/unit/test_package_surface.py`: каждый модуль ровно в одном пакете,
модулей вне пакетов нет, dev-only не лежит в продуктовом пакете.

- `ai_ops_kit/shared/` (5) — общий фундамент: `_bootstrap` (кладёт корень в `sys.path`; единственный
  модуль, оставшийся плоским — переезд дал бы цикл), `contracts` (TypedDict), `project_detector`,
  `generate_artifacts`, `generate_runtime`
- `ai_ops_kit/context/` (9) — сборка контекста: `context_compiler`, `context_engine`, `context_hybrid`,
  `context_retrieval`, `context_shadow`, `context_promotion_gate`, `context_cost`, `repo_graph`,
  `semantic_lite`
- `ai_ops_kit/engine/` (18) — исполнение: `ai_ops_run`, `execution_pipeline` (+`pipeline_*`),
  `tool_broker`, `tool_loop`, `worktree`, `gitio`, `run_plan`, `run_handoff`, `budget`,
  `atomic_planner`, `workpackage_executor`, `parallel_{planner,executor,live}`
- `ai_ops_kit/gates/` (13) — гейты и допуск: `gate_executor`, `gate_policy`, `gate_runtime`,
  `gate_result_v2`, `preflight`, `economic_preflight`, `concurrency_preflight`, `evidence_collector`,
  `regression_evidence`, `verification_tiers`, `spec_levels`, `invariants`, `approvals`
- `ai_ops_kit/providers/` (9) — модели и деньги: `orchestrator` (+`_http`/`_providers`/`_usage`),
  `model_router`, `provider_endpoints`, `usage_ledger`, `cost_account`, `cost_method`
- `ai_ops_kit/lifecycle/` (9) — состояние работы: `lifecycle_store`, `lifecycle_intent`, `workitem`,
  `active_work`, `run_report`, `product_health`, `effect_metrics`, `evolution_triggers`, `merge_memory`
- `ai_ops_kit/delivery/` (2) — доставка наружу: `pr_open`, `review_branch`
- `ai_ops_kit/engops/` (11) — инженерная операционная модель: `commit_policy`, `branch_policy`,
  `environment_map`, `deploy_readiness`, `architecture_baseline`, `engineering_advisor`,
  `delegation_advisor`, `session_{boundary,guardrails,telemetry,telemetry_provider}`
- `ai_ops_kit/security/` (6) — `security_scan`, `security_pack`, `security_enforcement`,
  `security_review_cascade`, `data_classification`, `seam_scan`
- `ai_ops_kit/ui/` (4) — `storybook_adapter`, `storybook_query`, `ui_evidence_collect`, `ui_readiness`
- `ai_ops_kit/cli/` (1) — `ai_ops_cli`
- `ai_ops_kit/devtools/` (8) — инструменты разработки САМОГО кита, в child-репозиторий НЕ едут
  (состав — зеркало `installer.DEV_ONLY_TOOLS`): `bench_lite`, `bench_performance`, `changelog_gen`,
  `kit_observability`, `model_comparison`, `promotion_qual`, `qual_run`, `retrieval_bench`

## validation/

Валидаторы — запускаются из pytest (`tests/unit/test_validator_runtime_contract.py` гоняет каждый
из копии репозитория) и в CI, все должны быть PASS (см. AGENTS.md). Код плоский, в пакеты не
переезжал; тела селфтестов вынесены в `tests/`.

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
- `validation/validate_engops_policy.py` — связность порогов EngOps + паритет «правило ↔ DEFAULTS кода» (v3.19.0)
- `validation/validate_event_catalog.py` — согласованность имён событий, drift-скан (v2.29)
- `validation/validate_duties.py` — обязанности постоянного агента Robin (v2.21)
- `validation/validate_feature_blueprint.py`
- `validation/validate_freshness.py`
- `validation/validate_research_artifacts.py` — research-модуль: схемы + связи RR→EV→DP + freshness + quote-конвенция (CI)
- `validation/validate_knowledge_graph.py`
- `validation/validate_openspec_change.py`
- `validation/validate_presets.py`
- `validation/validate_references.py`
- `validation/validate_reviewer_result.py` — структурный результат ревьюера (v2.33)
- `validation/validate_security_posture.py`
- `validation/validate_stale_gates.py`
- `validation/validate_workflow_gates.py`

## tools/

**Плоские имена — алиасы, реальный код в `ai_ops_kit/` (см. раздел выше).** Пути сохранены: их знают
документация, `doctor` и 661 существующий импорт. Аннотации ниже описывают сами модули — по какому бы
имени их ни импортировали; объект модуля один и тот же.

Генераторы (runtime-команды, артефакты по blueprint), sequential-оркестратор, gate executor (исполнение и блокировка quality gates), Product Health, run_report (оценка прогона + история срезов), effect_metrics (метрики эффекта).

- `tools/effect_metrics.py`
- `tools/gate_executor.py`
- `tools/generate_artifacts.py`
- `tools/generate_runtime.py`
- `tools/orchestrator.py` — провайдеры (mock/anthropic/openai-compatible) + **first-class `claude-cli`** (`make_claude_cli_provider`: локальный `claude -p` read-only как сильный writer, без ключа, v3.9.0)
- `tools/product_health.py`
- `tools/run_plan.py` — построение RunPlan (base_workflow + tracks -> gates), validate (v2.32)
- `tools/run_report.py`
- `tools/ai_ops_run.py` — единый контроллер `ai-ops run` (v2.34); complexity-routing консумирует writer_tier -> strong-executor=claude-cli (v3.9.0)
- `tools/model_router.py` — provider-neutral resolver роль->cheapest-qualified + **complexity-aware `writer_tier`** (класс задачи -> сильный/дешёвый writer, v3.9.0)
- `tools/commit_policy.py` — CommitContract: смешение зон кит/продукт, артефакты прогонов, запрещённые файлы, секрет в сообщении, protected_paths без approval (v3.19.0)
- `tools/branch_policy.py` — BranchContract: защищённые ветки (доставка только PR), имя ветки прогона, **отставание базы** и рассинхрон базы с upstream; unavailable != 0 (v3.19.0)
- `tools/environment_map.py` — read-only карта окружений: объявлено vs обнаружено (CI environment, .env.<name>); detected_not_declared/declared_not_detected; секреты ТОЛЬКО именами (v3.20.0)
- `tools/deploy_readiness.py` — честная зрелость поставки absent/configured/runnable/verified; без объявленного отката verified недостижим; платформенная поставка = путь вне репозитория (v3.20.0)
- `tools/economic_preflight.py` — граница расхода ДО tool loop: оценка по истории usage_ledger против лимитов RunPlan; решение по худшему прогону; нет истории = unavailable, не ноль (v3.21.0)
- `tools/provider_endpoints.py` — map провайдер->endpoint+key_env для openai-compatible (v3.7.12)
- `tools/parallel_live.py` — **concurrent parallel-2**: отдельный клон на пакет + governed fan-in (`run_live_concurrent`; доказан live, v3.8)
- `tools/parallel_executor.py` — bounded parallel-2 executor поверх decision-слоя (v3.7.1)
- `tools/parallel_planner.py` — планирование параллельных пакетов (disjoint-scope)
- `tools/security_review_cascade.py` — асимметричный fail-closed security-судья (detector->verifier->reducer); experimental/qualification-only, НЕ в strict-path (v3.8.4)
- `tools/budget.py` — execution budget: потолок вызовов модели (v2.38)
- `tools/project_detector.py` — детект стека -> RepositoryProfile (build/lint/test команды, v2.41)
- `tools/evidence_collector.py` — stack-aware сбор evidence: гоняет команды профиля через Broker -> gate implementation_verification (v2.44)
- `validation/validate_package_boundaries.py` — границы 5 пакетов 3.0: DAG зависимостей + непересечение + резолв include (v2.46, срез 0)
- `validation/validate_standalone_engine.py` — доказывает самодостаточность движка: строит managed из managed_set и гоняет `ai-ops run` из `.ai/managed/` отдельным процессом без parent-клона (v2.82)
- `validation/validate_qualification.py` — согласованность пакета живых сценариев (форма, task_type из workflows, известные флаги, матрица ОС/стеков) (v2.84)
- `validation/validate_requirements_artifact.py` — структура артефакта требований (testable requirements + acceptance scenarios) -> evidence гейта requirements (v2.86)
- `validation/validate_plan_artifact.py` — структура плана (work_packages + dependencies + write_scope) -> evidence гейта plan_readiness (v2.86)
- `validation/validate_spec_artifact.py` — форма spec-change + рендер в OpenSpec-markdown; движок валидирует реальным `openspec` CLI -> evidence гейта specification (v2.89)
- `validation/validate_container_assets.py` — стережёт jail-флаги контейнера (read-only/cap-drop/лимиты/non-root) от регресса (v2.90)
- `containers/Dockerfile` — эталонный образ изолированного рантайма движка (non-root, python+node+openspec) (v2.90)
- `containers/run-sandboxed.sh` — запуск движка в jail'е: read-only root + writable только worktree + лимиты + cap-drop (v2.90, P0.2)
- `docs/container-isolation.md` — два слоя изоляции (брокер + контейнер), что enforce'ит jail, как запускать, честная граница по сети (v2.90)
- `qualification/scenarios.yaml` — 5 канонических live-сценариев квалификации движка + матрица ОС/стеков (v2.84)
- `docs/qualification-runbook.md` — как прогнать живую квалификацию на реальном child (env, команды, чтение отчёта, матрица) (v2.84)
- `packages/<name>/package.yaml` — декларации границ 5 пакетов 3.0 (файл→пакет), без переноса файлов (v2.46)
- `tools/tool_broker.py` — Tool Broker + Policy Engine: модель предлагает, политика решает (v2.36)
- `tools/tool_loop.py` — tool-calling петля: proposer → Policy → Broker → Evidence → контекст (механика, v2.42); + независимый ревьюер `make_reviewer_proposer`/`run_review` под read-only (writer ≠ judge, v2.83)
- `tools/execution_pipeline.py` — единый движок: detect → tool-loop → [worktree] → commit → evidence → гейты → [draft PR] (v2.58–2.62)
- `tools/pr_open.py` — открытие draft PR через GitHub REST (токен из env; механизм, v2.62)
- `tools/active_work.py` — реестр активных работ + conflict forecast (v2.22)
- `tools/concurrency_preflight.py` — коллизии параллельной работы до старта (v2.28)
- `tools/merge_memory.py` — запись знания задачи в память при мердже (v2.25)
- `tools/worktree.py` — git worktree на WorkItem, изоляция параллельных сессий (v2.24)
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

Примеры: child-конфиг, openspec-demo, feature-blueprint-demo, knowledge-graph-demo, product-health-demo, research-demo (все проходят свои валидаторы в CI).

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
- `examples/research-demo/requests/RR-001.yaml` — демо research-контура: запрос (decision-first)
- `examples/research-demo/evidence/EV-001.yaml`
- `examples/research-demo/evidence/EV-002.yaml`
- `examples/research-demo/decisions/DP-001.yaml` — демо DecisionPackage (confidence=medium, без review)

## .github/

CI пакета (package-quality — 4 параллельные группы), быстрый слой на PR (pr-smoke) и релизный
workflow (release.yml: VERSION в main -> тег + Release; идемпотентен — существующий релиз не пересоздаёт).

- `.github/workflows/package-quality.yml`
- `.github/workflows/pr-smoke.yml`
- `.github/workflows/release.yml`
- `.github/ci-groups/{fast,contracts,selftests-a,selftests-m}.sh` — разбиение полного контура на группы
