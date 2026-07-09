# Roadmap — путь к AI Product Operating System

Видение — в `VISION.md`. Здесь — что уже есть, чего не хватает и в каком порядке
закрываем разрыв. Каждая фаза — отдельный minor-релиз, аддитивный и обратно
совместимый; breaking changes — только в 2.0.

## Что уже есть (опора)

| Механизм видения | Состояние в ките |
|---|---|
| Product First | Контракт PRODUCT (problem → users → value → ... → handoff), агенты product/* |
| Writer ≠ judge, gates | 12 gates с revision-binding, machine-readable результаты |
| Everything as Code | Registry как источник истины, схемы контрактов, валидаторы в CI |
| Review-агенты | Есть: accessibility, security, performance, code, requirements, regression |
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

## Правила движения по roadmap

- Каждая фаза проходит полный набор валидаторов; новые механизмы приносят свои
  валидаторы и self-test'ы вместе с собой.
- Новые агенты не принимаются без eval-кейсов (validate_agent_evals.py).
- Gates вводятся как non-blocking и становятся blocking только после обкатки на
  child-репозиториях.
- Capability-декларации честные: заявляем только реализованное, планы — со статусом
  `unsupported` + note "planned".
