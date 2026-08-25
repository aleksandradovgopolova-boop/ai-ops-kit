# Refactoring Map — AI Ops Kit

> **Статус:** анализ · Sprint 1 (2026-08-25)
> **Территория:** анализ без изменений кода
> **Источник:** AST-анализ импортов, структура `ai_ops_kit/`, `packages/layering.yaml`

---

## Карта модулей

### Foundation (слой 1)

| Модуль | Ответственность | Зависимости | Размер |
|--------|-----------------|-------------|--------|
| `shared/contracts.py` | TypedDict-контракты (WorkItemState, GateResultV2, DeliveryIntent, ...) | stdlib | ~200 строк |
| `shared/budget.py` | Примитив бюджета прогона | stdlib | ~68 строк |
| `shared/gitio.py` | Обёртка над git (subprocess) | stdlib | ~39 строк |
| `shared/lifecycle_store.py` | Durable-запись и fail-closed чтение lifecycle-состояния | stdlib, yaml | ~404 строки |
| `shared/usage_ledger.py` | Учёт cost/token per model call | stdlib | ~252 строки |
| `shared/path_hygiene.py` | Нормализация путей, project detection | stdlib | ~50 строк |
| `shared/project_detector.py` | Детект стека (.ai/, .git/, package.json, ...) | stdlib | ~80 строк |
| `shared/generate_artifacts.py` | Генерация runtime-артефактов | stdlib, yaml | ~120 строк |
| `shared/generate_runtime.py` | Генерация runtime-конфигурации | stdlib, yaml | ~100 строк |
| `shared/_bootstrap.py` | Инициализация кита при старте | stdlib | ~60 строк |

**Оценка:** Foundation чист. Все модули — инфраструктура, не зависят ни от кого. `lifecycle_store` (404 строки) — самый крупный; кандидат на разделение на read/write, но не срочно.

---

### Primitives (слой 2)

| Модуль | Ответственность | Зависимости | Размер |
|--------|-----------------|-------------|--------|
| `checks/` (11 модулей) | Чистая проверяющая логика (acceptance, architecture, feature, plan, requirements, spec, quality attributes, memory governance, reviewer result, adr registry) | stdlib, yaml | ~800 строк суммарно |
| `governance/` (4 модуля) | Policy engine, enforcement, decision log, human override | shared | ~500 строк суммарно |
| `security/` (6 модулей) | Data classification, seam scan, security enforcement, security pack, review cascade, security scan | shared | ~600 строк суммарно |
| `ui/` (6 модулей) | Experience contract, presenter, storybook adapter/query, evidence collect, readiness | shared | ~500 строк суммарно |
| `integrations/github.py` | GitHub API как operational source of truth | shared | ~200 строк |

**Оценка:** Primitives чисты. `checks/` — результат целенаправленного выноса логики из validation (v3.38). Каждый модуль — self-contained.

---

### Capabilities (слой 3, кольцо)

#### engine/ (17 модулей, ~3500 строк) — самый крупный пакет

| Модуль | Ответственность |
|--------|-----------------|
| `execution_pipeline.py` | Главная execution chain (detect → worktree → install → checks → spec → tool loop → commit → gates → report) |
| `ai_ops_run.py` | Транзакционный контроллер: вызывает pipeline + delivery после фиксации |
| `ai_route.py` | Классификация work item по реестрам (317 строк) — **предметная логика, не infrastructure** |
| `tool_broker.py` | Исполнение инструментов (shell, file, git) по policy |
| `tool_loop.py` | Model proposes → policy decides → broker executes |
| `workpackage_executor.py` | Исполнение work packages (параллельные задачи) |
| `parallel_executor.py` | Параллельное исполнение с budget-aware scheduling |
| `run_plan.py` | План прогона (какие gates, какой workflow) |
| `atomic_planner.py` | Атомарное планирование (один шаг за раз) |
| `pipeline_evidence.py` | Сбор evidence в рамках pipeline |
| `pipeline_helpers.py` | Вспомогательные функции pipeline |
| `worktree.py` | Git worktree isolation |

**Проблемы:**
- `ai_route.py` — предметная логика (классификация по реестрам), но лежит в engine. Это корень mutual pair engine ↔ lifecycle (workitem → ai_route). Переезд в `shared` формально решил бы цикл, но положил бы domain-логику в foundation (нарушение AC-01). **Решение — не переезд, а проектирование: «кто классифицирует» (AC-03).**
- `execution_pipeline.py` (1193 строки) — слишком крупный. Содержит и orchestration, и evidence collection, и gate invocation. Кандидат на разделение.

#### gates/ (13 модулей, ~2000 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `gate_executor.py` | Единый исполнитель quality gates (классификация, оценка, отчёт) |
| `gate_policy.py` | Risk-calibrated UI enforcement (advisory/blocking по калибровке) |
| `gate_result_v2.py` | GateResult v2 schema + миграционный адаптер v2↔v1 |
| `evidence_collector.py` | Сбор evidence (build/lint/test через tool_broker) |
| `approvals.py` | Human approval flow |
| `concurrency_preflight.py` | Проверка коллизий параллельной работы |
| `economic_preflight.py` | Экономическая целесообразность (cost vs. value) |
| `deploy_readiness.py` — **В engops, не в gates!** | Проверка готовности к deployment |

**Проблемы:**
- `evidence_collector.py` импортирует `engine.tool_broker` — корень mutual pair engine ↔ gates. **Решение: dependency injection — broker передаётся как параметр.**
- `deploy_readiness` — в engops, но вызывается из gate_executor. Это engops-логика, которая оценивается как gate. Граница размыта.

#### lifecycle/ (6 модулей, ~800 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `workitem.py` | Unified WorkItem entity + derive_status() |
| `active_work.py` | Текущая активная работа (owner detection) |
| `run_report.py` | Финальный отчёт о прогоне |
| `child_doctor.py` | Диагностика child-репозитория |
| `lifecycle_intent.py` | Намерение lifecycle-перехода |
| `merge_memory.py` | Память о мержах |

**Проблемы:**
- `workitem.py` импортирует `engine.ai_route` — корень mutual pair. Workitem знает слишком много: и про routing, и про gates, и про status derivation.

#### context/ (9 модулей, ~1200 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `context_compiler.py` | Компиляция контекста для модели (gates + retrieval + promotion) |
| `context_engine.py` | Движок контекста (orchestration) |
| `context_hybrid.py` | Гибридный контекст (repo graph + semantic) |
| `context_cost.py` | Стоимость контекста (token budget) |
| `context_retrieval.py` | Retrieval (поиск релевантных фрагментов) |
| `context_promotion_gate.py` | Gate продвижения контекста |
| `context_shadow.py` | Shadow-контекст (для тестирования) |
| `repo_graph.py` | Граф репозитория |
| `semantic_lite.py` | Лёгкая семантика |

**Проблемы:**
- `context_compiler.py` импортирует `engine.run_plan` — корень mutual pair context ↔ engine. **Решение: контракт плана (TypedDict), не импорт модуля.**

#### delivery/ (2 модуля, ~400 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `pr_open.py` | Открытие draft PR (идемпотентно, SHA-верификация) |
| `review_branch.py` | Read-only review ветки |

**Оценка:** Delivery чист. Все импорты из engine — lazy. Граница с engine чёткая.

#### planning/ (18 модулей, ~2500 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `product_bootstrap.py` | Инициализация продуктового слоя |
| `product_contract.py` | Продуктовый контракт |
| `product_registry.py` | Реестр продуктов |
| `product_templates.py` | Шаблоны продуктовых артефактов |
| `roadmap.py` | Дорожная карта |
| `delivery_plan.py` | План доставки |
| `next_work.py` | Следующая работа |
| `backlog/` (5 модулей) | Бэклог: classify, dedup, depgraph, prioritize |
| `contours.py` | Контуры (группировка задач) |
| `passport_generator.py` | Генератор паспорта |
| `short_path.py` | Короткий путь |
| `staleness.py` | Детект устаревания |
| `artifact_registry.py` | Реестр артефактов |

**Оценка:** Planning — точка входа из CLI. Не импортируется ядром. Чистая граница.

#### engops/ (18 модулей, ~2500 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `deploy_readiness.py` | Проверка готовности к deployment |
| `engineering_advisor.py` | Инженерный советник (рекомендации) |
| `architecture_baseline.py` | Архитектурный baseline |
| `branch_policy.py` | Политика веток |
| `commit_policy.py` | Политика коммитов |
| `delegation_advisor.py` | Советник делегирования |
| `session_boundary.py` | Границы сессии |
| `session_guardrails.py` | Ограничения сессии |
| `session_handoff.py` | Передача сессии |
| `session_launcher.py` | Запуск сессии |
| `session_telemetry.py` | Телеметрия сессии |
| ... | (ещё ~7 модулей) |

**Проблемы:**
- `deploy_readiness.py` — это gate-логика, но лежит в engops. Вызывается из `gate_executor` (lazy). Граница размыта: это engops-концерн или gate?
- Engops — самый «разношёрстный» пакет: session management, deploy readiness, architecture baseline, delegation advisor — разные предметные области в одном пакете.

#### providers/ (9 модулей, ~1200 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `orchestrator.py` | HTTP-оркестратор (model calls) |
| `model_routing.py` | Маршрутизация моделей |
| `cost_accounting.py` | Учёт стоимости |
| `provider_endpoints.py` | Эндпоинты провайдеров |
| `response_contracts.py` | Контракты ответов |
| ... | (ещё ~4 модуля) |

**Оценка:** Providers чист после переезда `usage_ledger` и `budget` в shared.

---

### Intelligence (слой 4)

| Модуль | Ответственность |
|--------|-----------------|
| `product_health.py` | Детерминированный health score (adoption, retention, errors, ...) |
| `effect_metrics.py` | Метрики эффекта |
| `evolution_triggers.py` | ADR-vs-reality evolution triggers |
| `health_product.py` | Продуктовое здоровье |
| `health_tech.py` | Техническое здоровье |
| `health_delivery.py` | Здоровье delivery |
| `drift_artifacts.py` | Артефакты дрейфа |
| `nightly_review.py` | Ночной обзор |
| `outcome_analytics.py` | Аналитика outcomes |
| `product_audit.py` | Продуктовый аудит |
| `refactoring_advisor.py` | Советник рефакторинга |
| `risk_register.py` | Реестр рисков |
| `session_watch.py` | Наблюдение за сессиями |
| `team_sync.py` | Командная синхронизация |
| `decision_loop.py` | Петля решений |
| ... | (ещё ~5 модулей) |

**Оценка:** Intelligence чист. Зависит от kernel (читает события), kernel не зависит от него. Инвариант проверяется layering validator.

---

### Entrypoints (слой 5)

| Модуль | Ответственность |
|--------|-----------------|
| `cli/ai_ops_cli.py` | Intent-based CLI |
| `devtools/` (12 модулей) | Bench, changelog, gate evals, model comparison, mutation probe, ... |
| `validation/` (80+ модулей) | Invariant validators (один на concern) |

**Оценка:** Entrypoints чисты. Вызываются процессом, не импортируются как библиотеки.

---

## Где ответственность дублируется

### 1. Evidence collection: gates/ vs engine/

`engine/pipeline_evidence.py` собирает evidence в рамках pipeline. `gates/evidence_collector.py` собирает evidence для gates. Оба работают с инструментами (build/lint/test), но по-разному.

**Рекомендация:** Определить, кто владелец. Если evidence — это gate-концерн (доказательство для gate), то `pipeline_evidence.py` должен делегировать в `gates/evidence_collector.py`, а не дублировать. Если evidence — это engine-концерн (данные для pipeline), то `evidence_collector.py` не должен знать про tool_broker напрямую.

### 2. Cost accounting: providers/ vs shared/

`shared/usage_ledger.py` — учёт cost/token. `shared/budget.py` — примитив бюджета. `providers/cost_accounting.py` — учёт стоимости провайдеров.

**Рекомендация:** Чёткое разделение: `shared/` — примитивы (запись, чтение); `providers/` — бизнес-логика (тарификация, маршрутизация по стоимости). Сегодня, похоже, так и есть, но стоит зафиксировать.

### 3. Health: intelligence/ vs engops/

`intelligence/product_health.py` — health score. `engops/` — deploy readiness, architecture baseline. Оба оценивают «здоровье», но с разных сторон.

**Рекомендация:** Intelligence — продуктовое здоровье (adoption, retention). Engops — инженерное здоровье (deploy readiness, branch policy). Граница уже чёткая по слоям, но стоит документировать.

---

## Где границы размыты

### 1. `ai_route.py` — engine или domain?

`ai_route.py` (317 строк) — классификация work item по реестрам. Это предметная логика (domain), но лежит в engine. `workitem.py` импортирует его — и это создаёт mutual pair engine ↔ lifecycle.

**Проблема:** Переезд в `shared` снимает цикл, но нарушает AC-01 (domain не должен быть в foundation). Переезд в `checks` (primitives) — возможный компромисс, но classification — не check.

**Рекомендация:** Проектирование, а не переезд. Решить «кто классифицирует» (AC-03): если workitem не должен звать роутер сам — классификация становится отдельным шагом, и цикл исчезает.

### 2. `deploy_readiness.py` — engops или gates?

`deploy_readiness.py` лежит в engops, но вызывается из `gate_executor.py`. Это gate-логика (проверка готовности к deployment), но packaged как engops.

**Проблема:** Если deploy readiness — gate, почему не в `gates/`? Если engops — почему gate_executor его вызывает?

**Рекомендация:** Переместить в `gates/` (как provider, не как executor) или формализовать: engops предоставляет данные, gates оценивает.

### 3. `execution_pipeline.py` — 1193 строки

Слишком крупный модуль. Содержит: orchestration, evidence collection, gate invocation, commit logic, delivery trigger.

**Проблема:** Модуль с 7+ ответственностями — кандидат на split. Но split — это рефакторинг, и он должен быть отдельным спринтом.

**Рекомендация:** Не трогать в этом спринте. Зафиксировать как known tech debt.

### 4. `engops/` — 18 модулей, разные предметные области

Session management (boundary, guardrails, handoff, launcher, telemetry), deploy readiness, architecture baseline, branch/commit policy, delegation advisor — всё в одном пакете.

**Проблема:** Пакет стал «свалкой» для всего, что не fits в другие пакеты. Не нарушает layering, но затрудняет навигацию.

**Рекомендация:** Рассмотреть разделение: `engops/session/` (session management) и `engops/policy/` (branch/commit/deploy policy). Не срочно.

---

## Конкретные предложения по рефакторингу

> ⚠️ **Это анализ, не план реализации.** Каждый пункт — отдельный спринт.

### Приоритет 1: Снять mutual pairs (зависит от ратчета)

| # | Действие | Снимает пару | Сложность |
|---|----------|-------------|-----------|
| 1 | `evidence_collector` получает `tool_broker` как параметр (DI), не импортирует напрямую | engine ↔ gates | Низкая |
| 2 | Формализовать: delivery вызывается ТОЛЬКО из `ai_ops_run`, добавить контракт-тест | delivery ↔ engine | Низкая |
| 3 | `deploy_readiness` переезжает в `gates/` как provider | engops ↔ gates | Средняя |
| 4 | `context_compiler` использует `run_plan` как TypedDict-контракт, не как импорт | context ↔ engine | Средняя |

### Приоритет 2: Уменьшить размер крупных модулей

| # | Действие | Модуль | Сложность |
|---|----------|--------|-----------|
| 5 | Выделить orchestration из `execution_pipeline.py` в отдельный модуль | engine/execution_pipeline.py (1193) | Высокая |
| 6 | Разделить `workitem.py` на status derivation + routing | lifecycle/workitem.py | Средняя |

### Приоритет 3: Улучшить навигацию

| # | Действие | Пакет | Сложность |
|---|----------|-------|-----------|
| 7 | Подпакеты в `engops/`: session/, policy/ | engops/ | Низкая |
| 8 | Документировать ответственность каждого модуля в docstring | все | Низкая |

---

## Ссылки

- [ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md) — 15 архитектурных правил
- [DEPENDENCY_DAG.md](DEPENDENCY_DAG.md) — граф зависимостей и ratchet-план
- [packages/layering.yaml](../../packages/layering.yaml) — source of truth для слоёв
