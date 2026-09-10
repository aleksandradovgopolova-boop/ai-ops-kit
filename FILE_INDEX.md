# File Index

Аннотированная карта репозитория для людей и агентов (аналог llms.txt).
Разделы упорядочены от контрактов к инструментам; полный контекст — в `AGENTS.md`.

## Корень

Версия, история, лицензии, видение и roadmap, инструкции для людей и агентов (AGENTS.md/CLAUDE.md),
сборка пакета и вход в контур проверки.

- `.dockerignore`
- `.gitignore`
- `.pre-commit-config.yaml`
- `AGENTS.md`
- `APPLY.md`
- `CHANGELOG.md` — свежие релизы (свежее 3.38.0); детальная история — `DEVELOPMENT-HISTORY.md`
- `CLAUDE.md`
- `DEVELOPMENT-HISTORY.md` — детальная инженерная история релизов (3.37.0 → 3.20.1, архив), вынесена из `CHANGELOG.md`
- `FILE_INDEX.md` — этот файл
- `LICENSE`
- `MIGRATION_GUIDE_4.0.md` — переход на 4.0: снятие плоского слоя `tools/` (warn-минор 3.40 предупреждает заранее)
- `NOTICE.md`
- `README.md` — обзор; актуальная витрина «что кит умеет сегодня» — `docs/capability-map.md` (built≠wired честно, генерируется из реестров)
- `ROADMAP.md` — направление продукта: четыре горизонта (Сейчас / Следующий результат / Дальше / Later), контракт проверяется `ai_ops_kit/planning/roadmap.py`. История пути — `docs/changelog/roadmap-history.md`
- `VERSION`
- `VISION.md`
- `mkdocs.yml`
- `pyproject.toml`, `setup.py` — дистрибутив (`pip install -e .`); включает `ai_ops_kit`
- `pytest.ini` — маркеры (в т.ч. `slow`) и addopts контура
- `requirements.txt` (рантайм: только pyyaml), `requirements-dev.txt` (pytest/hypothesis/ruff/mypy)

## history/ (архив)

Записи о прошлых состояниях: верны как история, но не описывают поведение текущего main.

- `history/plan-history.yaml` — закрытые работы и цели, уехавшие из активного плана
- `history/MIGRATION_GUIDE.md` — миграция со старой структуры агентов и 1.x→2.0; перенесён из корня
  (#569): описывал дореформенную раскладку и ссылался на снятый в 4.0 слой `tools/`
- `history/RELEASE_NOTES_v1.0.0.md` — заметки первого стабильного релиза v1.0.0 (zip-дистрибуция);
  перенесён из корня (#569): исторический снимок одной версии, текущий мажор — 4.x

## planning/

- `planning/plan.yaml` — delivery plan самого кита: 5 целей (id совпадают с `ROADMAP.md`) и подтверждённый остаток ревизии как работа. Читается `ai-ops next`; проверяется `delivery_plan.validate` через `validate_product_model`

## scripts/

Единственная точка входа в контур проверки (v3.31.0): построчного чеклиста больше нет.

- `scripts/check-full.sh` — полный контур перед коммитом (~4.5 мин), тот же набор, что в CI
- `scripts/check-fast.sh` — быстрый профиль во время работы (~1 мин, без маркера `slow`)
- `scripts/warn-path-belt.sh` — предупредить об остаточном `.pth`-поясе кита ДО прогона: на такой
  машине «локально всё зелёное» ничего не значит. Только предупреждение, вызывается из обоих контуров

## docs/

Документация для людей: Onboarding (ценность простым языком), Quickstart (+типовые ошибки), Walkthrough (сквозной сценарий), гайд внедрения по ролям, параллельные сессии.

- `docs/capability-map.md` — витрина «что кит умеет сегодня»: capability → состояние (built / built≠wired / partial / planned) → как проверить. СГЕНЕРИРОВАНА из реестров и кода (`python3 -m ai_ops_kit.devtools.capability_inventory`), свежесть держит `tests/contracts/test_capability_inventory.py`
- `docs/ONBOARDING.md`
- `docs/QUICKSTART.md`
- `docs/WALKTHROUGH.md`
- `docs/adoption-guide.md`
- `docs/parallel-sessions.md`
- `docs/3.0-design.md` — дизайн 3.0: `ai-ops run` основным путём + сплит на 5 пакетов (план, запуск по явному решению)
- `docs/dogfooding-metrics.md` — чеклист обкатки: как метрики (North Star/baseline) закрываются сами через `/ai-run`
- `docs/change-briefs/` — заполненные Change Brief'ы, по одному файлу на изменение
  (`<версия>-<slug>.md`, не перезаписываются); правило и состав — в `README.md` каталога
- `docs/audit-report.md` — ревизия репозитория 2026-08-11: реестр находок с доказательствами, что исправлено, оставшийся долг и решения владельца
- `docs/changelog/roadmap-history.md` — архив пройденного пути (фазы v1.3 → v3.36), заморожен 2026-08-11; направление живёт в `ROADMAP.md`

## manifest/

Центральный манифест пакета: версия, реестры, gates, spec-протокол, миграции.

- `manifest/ai-ops-manifest.yaml`

## registry/

Машиночитаемые реестры — источник истины: агенты, workflow-контракты, провайдеры, модели, среды, инструменты, capability-index, routing-policy, entities (Knowledge Graph).

- `registry/agents.yaml`
- `registry/capability-index.yaml`
- `registry/entities.yaml`
- `registry/models.yaml`
- `registry/product-operating-model.yaml` — **модель продуктового репозитория** (v3.35): 8 контуров
  (класс вопросов, источник истины, сигналы изменения, роль, реконструируемость, ярус достройки),
  12 ролей работы (ссылочная целостность на agents.yaml), 14 типов работы, объявляемые и выводимые
  статусы, 7 состояний артефакта, классы репозитория, ярусы Gap Plan, правила отбора next work
- `registry/communication-policy.yaml` — **Human Communication Layer** (v3.35): контракт
  `UserMessage` (четыре вопроса), три аудитории (default `product`), правила простого языка,
  адаптеры (presenter в коде / скилл / инструкция для CLAUDE.md)
- `registry/providers.yaml`
- `registry/routing-policy.yaml`
- `registry/runtimes.yaml`
- `registry/tracks.yaml` — quality tracks: signal->gates (base_workflow + tracks, v2.32)
- `registry/tools.yaml`
- `registry/workflows.yaml`

## agents/

42 агента по доменам (core/product/engineering/quality/delivery/meta): ревьюеры полного цикла, команда AI-продукта (llm-architect, ai-feature-engineer, ai-red-teamer, ai-evaluator); каждый зарегистрирован в registry/agents.yaml.

- `agents/README.md`
- `agents/core/context-builder.md`
- `agents/core/final-verifier.md`
- `agents/core/implementation-integrator.md`
- `agents/core/intake-classifier.md`
- `agents/core/plan-reviewer.md`
- `agents/core/requirements-writer.md`
- `agents/core/task-planner.md`
- `agents/delivery/documentation-steward.md`
- `agents/delivery/incident-analyst.md`
- `agents/delivery/observability-engineer.md`
- `agents/delivery/release-manager.md`
- `agents/engineering/ai-feature-engineer.md`
- `agents/engineering/data-engineer.md`
- `agents/engineering/devops-engineer.md`
- `agents/engineering/fullstack-developer.md`
- `agents/engineering/llm-architect.md`
- `agents/engineering/solution-architect.md`
- `agents/meta/agent-creator.md`
- `agents/meta/repository-memory-curator.md`
- `agents/meta/workflow-designer.md`
- `agents/product/adoption-manager.md`
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
- `skills/plain-language-communication/SKILL.md` — правила разговора с владельцем продукта
  (v3.35, НЕ opt-in; источник истины — registry/communication-policy.yaml, форма — presenter)
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
- `templates/planning/ROADMAP.md`, `templates/planning/plan.yaml` — контур планирования для child (v3.35)
- `templates/runtime/claude-communication.md` — адаптер политики коммуникации для CLAUDE.md (v3.35)
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
- `evaluations/agents/code-reviewer.md`
- `evaluations/agents/context-builder.md`
- `evaluations/agents/data-engineer.md`
- `evaluations/agents/design-system-reviewer.md`
- `evaluations/agents/devops-engineer.md`
- `evaluations/agents/documentation-reviewer.md`
- `evaluations/agents/documentation-steward.md`
- `evaluations/agents/experiment-designer.md`
- `evaluations/agents/final-verifier.md`
- `evaluations/agents/fullstack-developer.md`
- `evaluations/agents/implementation-integrator.md`
- `evaluations/agents/incident-analyst.md`
- `evaluations/agents/intake-classifier.md`
- `evaluations/agents/llm-architect.md`
- `evaluations/agents/observability-engineer.md`
- `evaluations/agents/observability-reviewer.md`
- `evaluations/agents/performance-reviewer.md`
- `evaluations/agents/plan-reviewer.md`
- `evaluations/agents/product-analyst.md`
- `evaluations/agents/product-manager.md`
- `evaluations/agents/product-reviewer.md`
- `evaluations/agents/regression-analyst.md`
- `evaluations/agents/release-manager.md`
- `evaluations/agents/repository-memory-curator.md`
- `evaluations/agents/requirements-reviewer.md`
- `evaluations/agents/requirements-writer.md`
- `evaluations/agents/security-reviewer.md`
- `evaluations/agents/solution-architect.md`
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
- `config/session-economy.yaml`
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

**Код движка.** 19 пакетов (package_ceiling, AGENTS.md). Плоский слой `tools/` снят в 4.0:
точки входа пакетные (`python3 -m ai_ops_kit.<pkg>.<mod>`, PYTHONPATH=.ai/managed), импорт —
`from ai_ops_kit.<pkg> import <mod>` (см. MIGRATION_GUIDE_4.0.md). Аннотации отдельных модулей —
ниже, в разделе «Аннотации модулей ai_ops_kit/».

Импорты внутри пакета — пакетные; `ai_ops_kit` импортируется с одним корнем на `sys.path`, как после `pip install` (`tests/unit/test_package_importable.py`, v3.33.0).

Правила границ проверяет `tests/unit/test_package_surface.py`: каждый модуль ровно в одном пакете,
модулей вне пакетов нет, dev-only не лежит в продуктовом пакете.

- `ai_ops_kit/shared/` — общий фундамент: `_bootstrap` (кладёт корень в `sys.path`; единственный
  модуль, оставшийся плоским — переезд дал бы цикл), `contracts` (TypedDict), `project_detector`,
  `generate_artifacts`, `generate_runtime`, `gitio`, `budget`, `ai_route` (маршрутизация; канон
  после K5, шим — `engine/ai_route`), `path_hygiene` (остаточный `.pth`-пояс кита в
  site-packages: `doctor` блокирует и говорит, чем удалять)
- `ai_ops_kit/context/` — сборка контекста: `context_compiler`, `context_engine`, `context_hybrid`,
  `context_retrieval`, `context_shadow`, `context_promotion_gate`, `context_cost`, `repo_graph`,
  `semantic_lite`
- `ai_ops_kit/engine/` — исполнение: `ai_ops_run` (+`ai_ops_run_{exec,lifecycle,print,reporting}`),
  `execution_pipeline` (+`pipeline_*`), `tool_broker`, `tool_loop`, `worktree`, `run_context`,
  `run_plan`, `run_handoff`, `acceptance_verify`, `atomic_planner`, `workpackage_executor`,
  `sequence_{plan,aggregate}`, `parallel_{planner,executor,live}`
- `ai_ops_kit/gates/` — гейты и допуск: `gate_executor`, `gate_policy`, `gate_runtime`,
  `gate_result_v2`, `preflight`, `economic_preflight`, `concurrency_preflight`, `evidence_collector`,
  `regression_evidence`, `verification_tiers`, `spec_levels`, `invariants`, `approvals`
- `ai_ops_kit/providers/` — модели и деньги: `orchestrator` (+`_http`/`_providers`/`_usage`),
  `model_router`, `provider_endpoints`, `usage_ledger`, `cost_account`, `cost_method`
- `ai_ops_kit/lifecycle/` — состояние работы: `lifecycle_intent`, `workitem`, `work_view`,
  `active_work` (+`work_claims`/`work_reconcile` — носитель заявок и сверка), `run_report`,
  `merge_memory`, `role_handoff`, `attention_bus`
- `ai_ops_kit/planning/staleness.py` — две проверки на ПРОТУХАНИЕ: описание ссылается на то, чего нет, и план отстал от истории (14.08.2026)
- `ai_ops_kit/planning/` — контур Planning & Execution модели продуктового репозитория (v3.35):
  `contours` (состояние контуров + связность изменения с источниками истины; `unknown != not_changed`),
  `delivery_plan` (+`plan_model`/`plan_validate`; `planning/plan.yaml`, вывод статуса из графа/гейтов/активной работы),
  `roadmap` (контракт четырёх горизонтов + связь целей с планом),
  `next_work` (четыре вопроса: где мы / что идёт / что блокирует / что взять следующим),
  `repo_audit` (первый сценарий: DISCOVER -> CLASSIFY -> RECONSTRUCT -> AUDIT -> ASK с provenance)
- `ai_ops_kit/intelligence/` — продуктовая аналитика, кольцо Intelligence: `product_health`,
  `effect_metrics`, `evolution_triggers`, `nightly_{collectors,review,schedule}` (ночной прогон),
  `knowledge_graph`, `outcome_analytics`. Слой ВЫШЕ ядра — ядро от них зависеть не вправе (v3.33.2)
- `ai_ops_kit/delivery/` — доставка наружу: `pr_open`, `review_branch`
- `ai_ops_kit/engops/` — инженерная операционная модель: `commit_policy`, `branch_policy`,
  `environment_map`, `deploy_readiness`, `architecture_baseline`, `engineering_advisor`,
  `delegation_advisor`, `session_{boundary,guardrails,telemetry,telemetry_provider}`
- `ai_ops_kit/security/` — `security_scan`, `security_pack`, `security_enforcement`,
  `security_review_cascade`, `data_classification`, `seam_scan`
- `ai_ops_kit/ui/` — `storybook_adapter`, `storybook_query`, `ui_evidence_collect`, `ui_readiness`,
  `presenter` (+`presenter_formatters`/`presenter_report_formatters`; Human Communication Layer
  v3.35: контракт `UserMessage` и три аудитории; наружу выходит смысл, а не внутреннее состояние)
- `ai_ops_kit/cli/` — точка входа UX: `ai_ops_cli` (+слой команд
  `ai_ops_cli_{commands,intents,lifecycle,product,report}`), `entry`, `human_help`
- `ai_ops_kit/devtools/` — инструменты разработки САМОГО кита, в child-репозиторий НЕ едут
  (состав — зеркало `installer.DEV_ONLY_TOOLS`): `bench_lite`, `bench_performance`, `changelog_gen`,
  `kit_observability`, `model_comparison`, `mutation_probe`, `promotion_qual`, `qual_run`,
  `retrieval_bench`
- `ai_ops_kit/checks/` — проверки-контракты артефактов и результатов: `feature_blueprint`,
  `requirements_artifact`, `plan_artifact`, `spec_artifact`, `acceptance_result`, `reviewer_result`,
  `cross_artifacts`, `run_handoff`, `context_bundle`, `adr_registry`, `architecture_decision`,
  `feature_decision`, `capability_policy`, `quality_attributes`, `memory_governance`, `environment_map`
- `ai_ops_kit/governance/` — governance-контур: `policy_engine`, `decision_boundary`, `decision_log`,
  `enforcement`, `human_override`, `override_learning`
- `ai_ops_kit/kernel/` — `ports` (порты ядра: контракты зависимостей между кольцами)
- `ai_ops_kit/integrations/` — внешние интеграции: `github`

## validation/

Валидаторы — запускаются из pytest (`tests/unit/test_validator_runtime_contract.py` гоняет каждый
из копии репозитория) и в CI, все должны быть PASS (см. AGENTS.md). Пакет `ai_ops_kit/validation/`;
тела селфтестов вынесены в `tests/`.

- `ai_ops_kit/validation/validate_layering.py` — направления зависимостей между пакетами `ai_ops_kit/*`: граф импортов по AST против `packages/layering.yaml` (v3.32.0)
- `ai_ops_kit/validation/_bootstrap.py` — sys.path для запускаемых `validation/*.py`; тёзка `ai_ops_kit/shared/_bootstrap.py` вынужденно: `sys.path[0]` — каталог самого скрипта (v3.31.0)
- `ai_ops_kit/validation/ai_capability_selftest.py`
- `ai_ops_kit/validation/ai_managed_checksums.py`
- `ai_ops_kit/validation/validate_agent_evals.py`
- `ai_ops_kit/validation/validate_agents_checklist.py`
- `ai_ops_kit/validation/validate_ai_first_config.py`
- `ai_ops_kit/validation/validate_ai_first_providers.py`
- `ai_ops_kit/validation/validate_ai_first_registry.py`
- `ai_ops_kit/validation/validate_ai_first_workflows.py`
- `ai_ops_kit/validation/validate_ai_ops_child.py`
- `ai_ops_kit/validation/validate_claims.py`
- `ai_ops_kit/validation/validate_cross_artifacts.py`
- `ai_ops_kit/validation/validate_decisions.py`
- `ai_ops_kit/validation/validate_engops_policy.py` — связность порогов EngOps + паритет «правило ↔ DEFAULTS кода» (v3.19.0)
- `ai_ops_kit/validation/validate_event_catalog.py` — согласованность имён событий, drift-скан (v2.29)
- `ai_ops_kit/validation/validate_duties.py` — обязанности постоянного агента Robin (v2.21)
- `ai_ops_kit/validation/validate_feature_blueprint.py`
- `ai_ops_kit/validation/validate_freshness.py`
- `ai_ops_kit/validation/validate_research_artifacts.py` — research-модуль: схемы + связи RR→EV→DP + freshness + quote-конвенция (CI)
- `ai_ops_kit/validation/validate_knowledge_graph.py`
- `ai_ops_kit/validation/validate_openspec_change.py`
- `ai_ops_kit/validation/validate_presets.py`
- `ai_ops_kit/validation/validate_references.py`
- `ai_ops_kit/validation/validate_product_objects.py` — четыре управляющих объекта продукта: утверждение называет основание, решение имеет альтернативы и условие пересмотра, baseline — дату и источник, readout сверяется с контрактом (2026-08-14)
- `ai_ops_kit/validation/validate_mutation_probes.py` — реестр охранных проверок: образец охраны обязан существовать РОВНО один раз, иначе проба молча ничего не проверяет (2026-08-14)
- `ai_ops_kit/validation/validate_acceptance_result.py` — вердикт сверки критериев приёмки: вердикт по КАЖДОМУ критерию, `met` требует цитаты и источника (B2-14, 2026-08-14)
- `ai_ops_kit/validation/validate_reviewer_result.py` — структурный результат ревьюера (v2.33)
- `ai_ops_kit/validation/validate_security_posture.py`
- `ai_ops_kit/validation/validate_stale_gates.py`
- `ai_ops_kit/validation/validate_workflow_gates.py`

## Аннотации модулей ai_ops_kit/

**Плоский слой `tools/` снят в 4.0 — код целиком под `ai_ops_kit/` (см. раздел выше).** Аннотации
ниже описывают сами модули по их пакетным путям.

Генераторы (runtime-команды, артефакты по blueprint), sequential-оркестратор, gate executor (исполнение и блокировка quality gates), Product Health, run_report (оценка прогона + история срезов), effect_metrics (метрики эффекта).

- `ai_ops_kit/intelligence/effect_metrics.py`
- `ai_ops_kit/gates/gate_executor.py`
- `ai_ops_kit/shared/generate_artifacts.py`
- `ai_ops_kit/shared/generate_runtime.py`
- `ai_ops_kit/providers/orchestrator.py` — провайдеры (mock/anthropic/openai-compatible) + **first-class `claude-cli`** (`make_claude_cli_provider`: локальный `claude -p` read-only как сильный writer, без ключа, v3.9.0)
- `ai_ops_kit/intelligence/product_health.py`
- `ai_ops_kit/engine/run_plan.py` — построение RunPlan (base_workflow + tracks -> gates), validate (v2.32)
- `ai_ops_kit/lifecycle/run_report.py`
- `ai_ops_kit/engine/ai_ops_run.py` — единый контроллер `ai-ops run` (v2.34); complexity-routing консумирует writer_tier -> strong-executor=claude-cli (v3.9.0)
- `ai_ops_kit/providers/model_router.py` — provider-neutral resolver роль->cheapest-qualified + **complexity-aware `writer_tier`** (класс задачи -> сильный/дешёвый writer, v3.9.0)
- `ai_ops_kit/engops/commit_policy.py` — CommitContract: смешение зон кит/продукт, артефакты прогонов, запрещённые файлы, секрет в сообщении, protected_paths без approval (v3.19.0)
- `ai_ops_kit/engops/branch_policy.py` — BranchContract: защищённые ветки (доставка только PR), имя ветки прогона, **отставание базы** и рассинхрон базы с upstream; unavailable != 0 (v3.19.0)
- `ai_ops_kit/checks/environment_map.py` — read-only карта окружений: объявлено vs обнаружено (CI environment, .env.<name>); detected_not_declared/declared_not_detected; секреты ТОЛЬКО именами (v3.20.0)
- `ai_ops_kit/gates/deploy_readiness.py` — честная зрелость поставки absent/configured/runnable/verified; без объявленного отката verified недостижим; платформенная поставка = путь вне репозитория (v3.20.0)
- `ai_ops_kit/gates/economic_preflight.py` — граница расхода ДО tool loop: оценка по истории usage_ledger против лимитов RunPlan; решение по худшему прогону; нет истории = unavailable, не ноль (v3.21.0)
- `ai_ops_kit/providers/provider_endpoints.py` — map провайдер->endpoint+key_env для openai-compatible (v3.7.12)
- `ai_ops_kit/engine/parallel_live.py` — **concurrent parallel-2**: отдельный клон на пакет + governed fan-in (`run_live_concurrent`; доказан live, v3.8)
- `ai_ops_kit/engine/parallel_executor.py` — bounded parallel-2 executor поверх decision-слоя (v3.7.1)
- `ai_ops_kit/engine/parallel_planner.py` — планирование параллельных пакетов (disjoint-scope)
- `ai_ops_kit/security/security_review_cascade.py` — асимметричный fail-closed security-судья (detector->verifier->reducer); experimental/qualification-only, НЕ в strict-path (v3.8.4)
- `ai_ops_kit/shared/budget.py` — execution budget: потолок вызовов модели (v2.38)
- `ai_ops_kit/shared/project_detector.py` — детект стека -> RepositoryProfile (build/lint/test команды, v2.41)
- `ai_ops_kit/gates/evidence_collector.py` — stack-aware сбор evidence: гоняет команды профиля через Broker -> gate implementation_verification (v2.44)
- `ai_ops_kit/validation/validate_package_boundaries.py` — границы 5 пакетов 3.0: DAG зависимостей + непересечение + резолв include (v2.46, срез 0)
- `ai_ops_kit/validation/validate_standalone_engine.py` — доказывает самодостаточность движка: строит managed из managed_set и гоняет `ai-ops run` из `.ai/managed/` отдельным процессом без parent-клона (v2.82)
- `ai_ops_kit/validation/validate_qualification.py` — согласованность пакета живых сценариев (форма, task_type из workflows, известные флаги, матрица ОС/стеков) (v2.84)
- `ai_ops_kit/validation/validate_requirements_artifact.py` — структура артефакта требований (testable requirements + acceptance scenarios) -> evidence гейта requirements (v2.86)
- `ai_ops_kit/validation/validate_plan_artifact.py` — структура плана (work_packages + dependencies + write_scope) -> evidence гейта plan_readiness (v2.86)
- `ai_ops_kit/validation/validate_spec_artifact.py` — форма spec-change + рендер в OpenSpec-markdown; движок валидирует реальным `openspec` CLI -> evidence гейта specification (v2.89)
- `ai_ops_kit/validation/validate_container_assets.py` — стережёт jail-флаги контейнера (read-only/cap-drop/лимиты/non-root) от регресса (v2.90)
- `containers/Dockerfile` — эталонный образ изолированного рантайма движка (non-root, python+node+openspec) (v2.90)
- `containers/run-sandboxed.sh` — запуск движка в jail'е: read-only root + writable только worktree + лимиты + cap-drop (v2.90, P0.2)
- `docs/container-isolation.md` — два слоя изоляции (брокер + контейнер), что enforce'ит jail, как запускать, честная граница по сети (v2.90)
- `qualification/scenarios.yaml` — 5 канонических live-сценариев квалификации движка + матрица ОС/стеков (v2.84)
- `docs/qualification-runbook.md` — как прогнать живую квалификацию на реальном child (env, команды, чтение отчёта, матрица) (v2.84)
- `packages/<name>/package.yaml` — декларации границ 5 пакетов 3.0 (файл→пакет), без переноса файлов (v2.46)
- `packages/layering.yaml` — слои 12 пакетов `ai_ops_kit/*` и допустимые направления зависимостей; замер циклов и то, что сегодня непроверяемо (v3.32.0)
- `ai_ops_kit/engine/tool_broker.py` — Tool Broker + Policy Engine: модель предлагает, политика решает (v2.36)
- `ai_ops_kit/engine/tool_loop.py` — tool-calling петля: proposer → Policy → Broker → Evidence → контекст (механика, v2.42); + независимый ревьюер `make_reviewer_proposer`/`run_review` под read-only (writer ≠ judge, v2.83)
- `ai_ops_kit/devtools/mutation_probe.py` — прогон мутационных проб: снятие охраны обязано ронять названный тест (dev-only, 2026-08-14)
- `ai_ops_kit/planning/staleness.py` — проверки протухания: мёртвые ссылки описания и отставание плана от истории (14.08.2026)
- `ai_ops_kit/engine/acceptance_verify.py` — сверка критериев приёмки с результатом: независимый судья + вердикт с ЦИТАТОЙ, проверяемой кодом (B2-14, 2026-08-14)
- `ai_ops_kit/engine/execution_pipeline.py` — единый движок: detect → tool-loop → [worktree] → commit → evidence → гейты → [draft PR] (v2.58–2.62)
- `ai_ops_kit/delivery/pr_open.py` — открытие draft PR через GitHub REST (токен из env; механизм, v2.62)
- `ai_ops_kit/lifecycle/active_work.py` — реестр активных работ + conflict forecast (v2.22)
- `ai_ops_kit/gates/concurrency_preflight.py` — коллизии параллельной работы до старта (v2.28)
- `ai_ops_kit/lifecycle/merge_memory.py` — запись знания задачи в память при мердже (v2.25)
- `ai_ops_kit/engine/worktree.py` — git worktree на WorkItem, изоляция параллельных сессий (v2.24)
- `ai_ops_kit/lifecycle/workitem.py`

## installer/

CLI ai-ops: init/status/diff/update/validate/doctor/migrate для child-репозиториев. Ядро — тонкий
роутер `ai_ops.py`; тяжёлые команды вынесены в сателлиты (загружаются через `_AO_NS=globals()`).

- `installer/ai_ops.py` — точка входа и роутер команд
- `installer/setup_ops.py` — init/setup
- `installer/update_ops.py` — update
- `installer/doctor.py` — doctor
- `installer/selftest_ops.py` — selftest
- `installer/aux_commands.py` — вспомогательные команды
- `installer/ci_setup.py` — синхронизация CI
- `installer/child_scaffolding.py` — скаффолдинг дочернего репозитория
- `installer/plan_merge_setup.py` — установка merge-драйвера плана
- `installer/delivered_merge_footprint.py` — контроль объёма доставки при мердже

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
