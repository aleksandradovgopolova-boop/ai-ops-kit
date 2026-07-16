# Roadmap — путь к AI Product Operating System

Видение — в `VISION.md`. Здесь — что уже есть, чего не хватает и в каком порядке
закрываем разрыв. Каждая фаза — отдельный minor-релиз, аддитивный и обратно
совместимый; breaking changes — только в 2.0.

## Что уже есть (опора)

| Механизм видения | Состояние в ките |
|---|---|
| Product First | Контракт PRODUCT (problem → users → value → ... → handoff), агенты product/* |
| Writer ≠ judge, gates | 26 gates с revision-binding, machine-readable результаты (MVP-blocking ≤ 8) |
| Everything as Code | Registry как источник истины, схемы контрактов, валидаторы в CI |
| Review-агенты | 14 независимых ревьюеров по зонам: plan, prompt, requirements, code, architecture, performance, security, accessibility, ux, design-system, analytics, documentation, observability, product |
| Аналитика | Частично: ProductAnalyticsPlan, Experiment (шаблоны), experiment-designer, product-analyst |
| Документация | documentation-steward, gate documentation_drift (пока non-blocking) |
| Observability | observability-engineer, workflow release.md, incident-resolution + memory |
| Память/инсайты | memory/ + стадии memory-capture (замкнуто в 1.2.0) |
| Генераторы | Образец: tools/generate_runtime.py (единый источник, drift-детект) |

## Фаза 1 — Продуктовый фундамент (v1.3) ✅ выполнена

Цель: «Analytics/Design/Docs by Default» как контракты, а не пожелания.

- **Шаблоны недостающих артефактов**: TrackingPlan, EventSchema, DashboardSpec,
  UXFlow, ScreenStates (Empty/Loading/Error/Success), DesignReview, RolloutPlan,
  FeatureFlag, RollbackStrategy, MonitoringSpec (SLO/alerts), ProblemStatement, JTBD,
  Personas, Hypotheses, OpportunitySolutionTree.
- **Новые quality gates** (сначала non-blocking, ужесточение — фаза 3):
  discovery_completeness, ux_review, design_system_usage, analytics_readiness,
  documentation_updated, release_safety (flag+rollback), observability_readiness.
- **Feature Blueprint v1**: структура каталога функции + JSON Schema
  (feature-blueprint.schema.json) + валидатор полноты по стадии жизненного цикла.
- **Workflow-контракты ANALYTICS и VISUAL** (заявлены как post-MVP с v0.2) — стадии,
  агенты, gates.

## Фаза 2 — Review-агенты и Discovery (v1.4) ✅ выполнена

Цель: каждая зона ответственности имеет своего ревьюера; Discovery — первоклассный этап.

- **Новые агенты** (каждый — с записью в registry и eval-кейсами, гейт уже требует):
  product-reviewer, ux-reviewer, design-system-reviewer, analytics-reviewer,
  documentation-reviewer, observability-reviewer. Architecture review — расширение
  зоны solution-architect + отдельный architecture-reviewer.
- **Углубление PRODUCT-контракта**: полноценные Discovery-стадии (problem statement,
  JTBD, personas, hypotheses, impact mapping, competitor review, success metrics,
  risks) с шаблонами фазы 1.
- **UX-чек-листы как данные**: rules/design/ на основе Nielsen Heuristics и WCAG —
  машиночитаемые списки, на которые ссылаются ревьюеры.

## Фаза 3 — Генераторы (v1.5) ✅ выполнена

Цель: стандартизированные артефакты создаются генераторами, а не свободной формой.

- **Generator framework** в tools/ по образцу generate_runtime.py: генератор читает
  Feature Blueprint + результаты предыдущих этапов, создаёт скелеты артефактов из
  шаблонов, drift-детект отличает сгенерированное от отредактированного.
- Первые генераторы: Discovery, PRD, Analytics (Tracking Plan + Event Schema),
  Dashboard Specification, Documentation (User Guide/FAQ/Release Notes/What's New),
  Release (checklist + rollout + rollback), Monitoring (logging/metrics/alerts/SLO),
  Experiment, Retrospective.
- Gates фазы 1 переводятся в blocking для workflow PRODUCT/VISUAL/ANALYTICS.

## Фаза 4 — Knowledge Graph и Product Health (v2.0) ✅ выполнена

Цель: непрерывный цикл Discovery → Delivery → Release → Measurement → Insights → Discovery.

- **Knowledge Graph**: registry/entities.yaml — типы сущностей и связи
  (Goal → Initiative → Epic → Feature → Story → ... → Insight), валидатор ссылочной
  целостности; Feature Blueprint становится узлом графа.
- **Product Health**: контракт метрик (adoption, retention, reliability, errors,
  performance, support load) + Product Health Score; вход — экспорт из
  аналитики/мониторинга, выход — machine-readable отчёт.
- **Continuous Improvement**: workflow INSIGHTS — анализ данных после релиза,
  генерация гипотез и экспериментов, запись в memory/ и вход следующего Discovery.
- Пересмотр schema_version контрактов: breaking НЕ потребовался — все контракты
  остаются schema_version 1, v2.0 полностью обратно совместим с 1.x.

## v2.1 — интеграция research-пакета ✅ выполнена

Курируемая интеграция внешнего исследования (Product & Design Extension Pack):
взяты реальные пробелы, дубли уже построенного отклонены.

- **AI Feature Evals**: ai-evaluator + rules/ai/EvalPolicy.md +
  templates/quality/AIFeatureEvalPlan.md + blocking-гейт ai_eval (applies_when:
  LLM/агентный компонент в фиче). Кит теперь измеряет не только своих агентов,
  но и AI-возможности, отданные пользователям.
- **Adoption как стадия**: adoption-manager, контракт ADOPTION (launch-readiness ->
  adoption-plan -> feedback-loop -> post-launch-review -> independent review),
  стадия adoption в Feature Blueprint, preset product-adoption.
- **Discovery-исследование**: user-researcher + UserResearchPlan (story-based
  интервью) + AssumptionTest (RAT); правила Continuous Discovery в OST-шаблоне.
- **Источники истины**: context/product/DesignSystem.md (DTCG-токены) и
  MetricCatalog.md (семантический слой); поле source_of_truth у gates.
- analytics_readiness усилен evidence events_verified_live; ExperimentReadout,
  InAppContent; Diátaxis-компас в UserGuide; HEART/AARRR в DashboardSpec.

Кандидаты v2.3 ✅ выполнены в v2.3.0 (оба обоснованы данными первого боевого
прогона — memory/lessons-learned/2026-07-09-first-child-run-insights.md):
профили blueprint lean/full и кросс-артефактный валидатор
(tracking-plan ↔ dashboard-spec; расширение на MetricCatalog — следующий шаг).

## Интеграция team-os-toolkit (референс операционной архитектуры команды)

Из четырёх слоёв team-os-toolkit ~60% уже реализовано в ките под другими именами
(registry как SoT, Knowledge Graph, memory-loop, human-approval). Берём механику
недостающего, отклоняем структурный reorg (ковенант: аддитивно, без breaking в 2.x).

- **Фаза 1 — Knowledge Integrity (v2.9) ✅ выполнена.** Drift-control, наведённый
  сначала на сам пакет: validate_references.py (uses_skills/checklist/owner/gate
  резолвятся — закрыл латентную дыру 2.7–2.8), claims.yaml + validate_claims.py
  (утверждения документации о коде: file/symbol/enum), селфтесты с намеренным сломом
  (гейт видят падающим). Гейт knowledge_integrity (non-blocking до обкатки).
- **Фаза 2 — Freshness + Governance (v2.9) ✅ выполнена.** FreshnessPolicy (классы
  stable/evolving/volatile, единый термин stability) + validate_freshness.py + now.md
  как датированный снимок; governance/information-boundaries.md (что можно/нельзя
  хранить — критично для гос-контекста). Гейт knowledge_freshness (advisory).
- **Фаза 3 — Decision Intelligence (v2.10) ✅ выполнена.** decisions/registry.yaml
  (принципы с confidence/recurrence/counterexamples/review_date, эпизоды, outcomes) +
  схема + validate_decisions.py; skill decision-support (recommendation-first: система
  не выдаёт вердикт, пока человек не сформулировал позицию; one-way-door — бриф на
  эскалацию, AI не решает необратимое сам); workflow DECISION; гейт decision_quality
  (non-blocking). Связь с systems-thinking (constraint -> contradiction -> decision).
- **Фаза 4 — Runtime/Robin (v2.21) ✅ выполнена как runtime-агностичная спека.** Кит даёт
  абстрактный контракт `persistent-agent-runtime` (`registry/runtimes.yaml`), спеку
  `runtime/robin/ROBIN.md` (декларативные duties, два слоя памяти staged→promoted через
  человека, append-only interaction-log, read-mostly границы, kill-switch), валидатор
  `validation/validate_duties.py` и шаблон привязки `templates/runtime/runtime-binding.example.yaml`.
  Честно: конкретный рантайм (Hermes, свой сервис, cron+CLI) — привязка на уровне child, не
  в ядре; `verified_against_deploy: false` (из среды разработки деплой не проверялся);
  постоянного runtime у кита по-прежнему нет, оркестратор sequential-only. Не строим: Robin
  как готовый бот.

Отклонено осознанно: reorg `.ai/` целиком, `capabilities/`/`adapters/` как новые
верхнеуровневые слои (дублируют capability-index/presets/runtimes), Robin как готовый бот.

## Execution Engine (v2.31–2.39) — от «конституции» к исполняющему ядру

По внешнему аудиту: у кита сильное ядро `task → workflow → agents → gates`, но не хватало
внешнего слоя автоматики. Всё, что строится **детерминированно/offline**, — сделано и
обкатано на реальном child (ии-среда):

- **Фаза 0 — correctness & safety (v2.31) ✅.** Устранён дрифт `ai-start-task`; `security`
  в ENGINEERING; `ai_red_team` блокирующий; сырой task-текст убран из audit-log;
  состояние прогона — per-WorkItem (`.ai/runtime/workitems/<id>/`).
- **Фаза 1 — контракт исполнения (v2.32–2.33) ✅.** RunPlan = base_workflow + треки
  (`registry/tracks.yaml`): «Design/Analytics/Docs by default» выводится из сигналов и
  добавляет свои гейты. Structured reviewer-result — источник истины вместо regex;
  evidence-схемы гейтов.
- **Фаза 2 — исполнение (v2.34–2.39) ✅ offline-часть.** `ai-ops run` — единый контроллер
  (route→RunPlan→WorkItem→active-work→исполнение→отчёт). Tool Broker + Policy Engine
  («модель предлагает, политика решает»; protected-paths = merge пакет+child). Execution
  budget (потолок вызовов). Провайдеры anthropic/openai/openai-compatible (DeepSeek/local).
- **Живое — разблокировано (v2.42–2.44) ✅.** tool-calling петля подтверждена живым прогоном
  на DeepSeek (`openai-compatible`): цикл `write → проверка → done`, политика и бюджет держат
  (`live_proposal_quality: verified`). Concurrency preflight видит открытые PR через GitHub
  REST-фоллбэк без `gh` (токен из env). Stack-aware evidence collector гоняет команды
  RepositoryProfile через Broker и отдаёт структурный evidence в `implementation_verification`.
- **3.0 в работе (по срезам, `docs/3.0-design.md`):** срез 0 ✅ — границы 5 пакетов объявлены
  и стережутся валидатором (`validate_package_boundaries.py`), файлы не двигали; срез 1 ✅ —
  `ai-run` канонический вход, `ai-start-task` сохранён совместимым алиасом. Остаётся (breaking,
  по явному решению + обкатка на child): по-пакетная установка, физический разнос дерева,
  MIGRATION_GUIDE.

## Правила движения по roadmap

- Каждая фаза проходит полный набор валидаторов; новые механизмы приносят свои
  валидаторы и self-test'ы вместе с собой.
- Новые агенты не принимаются без eval-кейсов (validate_agent_evals.py).
- Gates вводятся как non-blocking и становятся blocking только после обкатки на
  child-репозиториях.
- Capability-декларации честные: заявляем только реализованное, планы — со статусом
  `unsupported` + note "planned".
