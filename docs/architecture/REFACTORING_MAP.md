# Refactoring Map — AI Ops Kit

> **Статус:** анализ · Sprint 1 (2026-08-25)
> **Территория:** анализ без изменений кода
> **Источник:** AST-анализ импортов, структура `ai_ops_kit/`, `packages/layering.yaml`

---

## Карта модулей

### Foundation (слой 1)

| Модуль | Ответственность | Зависимости | Размер |
|--------|-----------------|-------------|--------|
| `tools/contracts.py` | TypedDict-контракты (WorkItemState, GateResultV2, DeliveryIntent, ...) | stdlib | ~200 строк |
| `tools/budget.py` | Примитив бюджета прогона | stdlib | ~68 строк |
| `tools/gitio.py` | Обёртка над git (subprocess) | stdlib | ~39 строк |
| `tools/lifecycle_store.py` | Durable-запись и fail-closed чтение lifecycle-состояния | stdlib, yaml | ~404 строки |
| `tools/usage_ledger.py` | Учёт cost/token per model call | stdlib | ~252 строки |
| `tools/path_hygiene.py` | Нормализация путей, project detection | stdlib | ~50 строк |
| `tools/project_detector.py` | Детект стека (.ai/, .git/, package.json, ...) | stdlib | ~80 строк |
| `tools/generate_artifacts.py` | Генерация runtime-артефактов | stdlib, yaml | ~120 строк |
| `tools/generate_runtime.py` | Генерация runtime-конфигурации | stdlib, yaml | ~100 строк |
| `tools/_bootstrap.py` | Инициализация кита при старте | stdlib | ~60 строк |

**Оценка:** Foundation чист. Все модули — инфраструктура, не зависят ни от кого. `lifecycle_store` (404 строки) — самый крупный; кандидат на разделение на read/write, но не срочно.

---

### Primitives (слой 2)

| Модуль | Ответственность | Зависимости | Размер |
|--------|-----------------|-------------|--------|
| Пакет `checks` (11 модулей) | Чистая проверяющая логика (acceptance, architecture, feature, plan, requirements, spec, quality attributes, memory governance, reviewer result, adr registry) | stdlib, yaml | ~800 строк суммарно |
| Пакет `governance` (4 модуля) | Policy engine, enforcement, decision log, human override | shared | ~500 строк суммарно |
| Пакет `security` (6 модулей) | Data classification, seam scan, security enforcement, security pack, review cascade, security scan | shared | ~600 строк суммарно |
| Пакет `ui` (6 модулей) | Experience contract, presenter, storybook adapter/query, evidence collect, readiness | shared | ~500 строк суммарно |
| `ai_ops_kit/integrations/github.py` | GitHub API как operational source of truth | shared | ~200 строк |

**Оценка:** Primitives чисты. Пакет `checks` — результат целенаправленного выноса логики из validation (v3.38). Каждый модуль — self-contained.

---

### Capabilities (слой 3, кольцо)

#### Пакет engine (17 модулей, ~3500 строк) — самый крупный пакет

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/engine/execution_pipeline.py` | Главная execution chain (detect → worktree → install → checks → spec → tool loop → commit → gates → report) |
| `ai_ops_kit/engine/ai_ops_run.py` | Транзакционный контроллер: вызывает pipeline + delivery после фиксации |
| `ai_ops_kit/engine/ai_route.py` | Классификация work item по реестрам (317 строк) — **предметная логика, не infrastructure** |
| `ai_ops_kit/engine/tool_broker.py` | Исполнение инструментов (shell, file, git) по policy |
| `ai_ops_kit/engine/tool_loop.py` | Model proposes → policy decides → broker executes |
| `ai_ops_kit/engine/workpackage_executor.py` | Исполнение work packages (параллельные задачи) |
| `ai_ops_kit/engine/parallel_executor.py` | Параллельное исполнение с budget-aware scheduling |
| `ai_ops_kit/engine/run_plan.py` | План прогона (какие gates, какой workflow) |
| `ai_ops_kit/engine/atomic_planner.py` | Атомарное планирование (один шаг за раз) |
| `ai_ops_kit/engine/pipeline_evidence.py` | Сбор evidence в рамках pipeline |
| `ai_ops_kit/engine/pipeline_helpers.py` | Вспомогательные функции pipeline |
| `ai_ops_kit/engine/worktree.py` | Git worktree isolation |

**Проблемы:**
- `ai_route.py` — предметная логика (классификация по реестрам), но лежит в engine. Это корень mutual pair engine ↔ lifecycle (workitem → ai_route). Переезд в `shared` формально решил бы цикл, но положил бы domain-логику в foundation (нарушение AC-01). **Решение — не переезд, а проектирование: «кто классифицирует» (AC-03).**
- `execution_pipeline.py` (1193 строки) — слишком крупный. Содержит и orchestration, и evidence collection, и gate invocation. Кандидат на разделение.

#### Пакет gates (13 модулей, ~2000 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/gates/gate_executor.py` | Единый исполнитель quality gates (классификация, оценка, отчёт) |
| `ai_ops_kit/gates/gate_policy.py` | Risk-calibrated UI enforcement (advisory/blocking по калибровке) |
| `ai_ops_kit/gates/gate_result_v2.py` | GateResult v2 schema + миграционный адаптер v2↔v1 |
| `ai_ops_kit/gates/evidence_collector.py` | Сбор evidence (build/lint/test через tool_broker) |
| `ai_ops_kit/gates/approvals.py` | Human approval flow |
| `ai_ops_kit/gates/concurrency_preflight.py` | Проверка коллизий параллельной работы |
| `ai_ops_kit/gates/economic_preflight.py` | Экономическая целесообразность (cost vs. value) |
| deploy_readiness — **в engops, не в gates** | Проверка готовности к deployment |

**Проблемы:**
- `evidence_collector.py` импортирует `engine.tool_broker` — корень mutual pair engine ↔ gates. **Решение: dependency injection — broker передаётся как параметр.**
- deploy_readiness — в engops, но вызывается из gate_executor. Это engops-логика, которая оценивается как gate. Граница размыта.

#### Пакет lifecycle (6 модулей, ~800 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/lifecycle/workitem.py` | Unified WorkItem entity + derive_status() |
| `ai_ops_kit/lifecycle/active_work.py` | Текущая активная работа (owner detection) |
| `ai_ops_kit/lifecycle/run_report.py` | Финальный отчёт о прогоне |
| `ai_ops_kit/lifecycle/child_doctor.py` | Диагностика child-репозитория |
| `ai_ops_kit/lifecycle/lifecycle_intent.py` | Намерение lifecycle-перехода |
| `ai_ops_kit/lifecycle/merge_memory.py` | Память о мержах |

**Проблемы:**
- `workitem.py` импортирует `engine.ai_route` — корень mutual pair. Workitem знает слишком много: и про routing, и про gates, и про status derivation.

#### Пакет context (9 модулей, ~1200 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/context/context_compiler.py` | Компиляция контекста для модели (gates + retrieval + promotion) |
| `ai_ops_kit/context/context_engine.py` | Движок контекста (orchestration) |
| `ai_ops_kit/context/context_hybrid.py` | Гибридный контекст (repo graph + semantic) |
| `ai_ops_kit/context/context_cost.py` | Стоимость контекста (token budget) |
| `ai_ops_kit/context/context_retrieval.py` | Retrieval (поиск релевантных фрагментов) |
| `ai_ops_kit/context/context_promotion_gate.py` | Gate продвижения контекста |
| `ai_ops_kit/context/context_shadow.py` | Shadow-контекст (для тестирования) |
| `ai_ops_kit/context/repo_graph.py` | Граф репозитория |
| `ai_ops_kit/context/semantic_lite.py` | Лёгкая семантика |

**Проблемы:**
- `context_compiler.py` импортирует `engine.run_plan` — корень mutual pair context ↔ engine. **Решение: контракт плана (TypedDict), не импорт модуля.**

#### Пакет delivery (2 модуля, ~400 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/delivery/pr_open.py` | Открытие draft PR (идемпотентно, SHA-верификация) |
| `ai_ops_kit/delivery/review_branch.py` | Read-only review ветки |

**Оценка:** Delivery чист. Все импорты из engine — lazy. Граница с engine чёткая.

#### Пакет planning (18 модулей, ~2500 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/planning/product_bootstrap.py` | Инициализация продуктового слоя |
| `ai_ops_kit/planning/product_contract.py` | Продуктовый контракт |
| `ai_ops_kit/planning/product_registry.py` | Реестр продуктов |
| `ai_ops_kit/planning/product_templates.py` | Шаблоны продуктовых артефактов |
| `ai_ops_kit/planning/roadmap.py` | Дорожная карта |
| `ai_ops_kit/planning/delivery_plan.py` | План доставки |
| `ai_ops_kit/planning/next_work.py` | Следующая работа |
| Пакет `backlog/` (5 модулей) | Бэклог: classify, dedup, depgraph, prioritize |
| `ai_ops_kit/planning/contours.py` | Контуры (группировка задач) |
| `ai_ops_kit/planning/passport_generator.py` | Генератор паспорта |
| `ai_ops_kit/planning/short_path.py` | Короткий путь |
| `ai_ops_kit/planning/staleness.py` | Детект устаревания |
| `ai_ops_kit/planning/artifact_registry.py` | Реестр артефактов |

**Оценка:** Planning — точка входа из CLI. Не импортируется ядром. Чистая граница.

#### Пакет engops (18 модулей, ~2500 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/engops/deploy_readiness.py` | Проверка готовности к deployment |
| `ai_ops_kit/engops/engineering_advisor.py` | Инженерный советник (рекомендации) |
| `ai_ops_kit/engops/architecture_baseline.py` | Архитектурный baseline |
| `ai_ops_kit/engops/branch_policy.py` | Политика веток |
| `ai_ops_kit/engops/commit_policy.py` | Политика коммитов |
| `ai_ops_kit/engops/delegation_advisor.py` | Советник делегирования |
| `ai_ops_kit/engops/session_boundary.py` | Границы сессии |
| `ai_ops_kit/engops/session_guardrails.py` | Ограничения сессии |
| `ai_ops_kit/engops/session_handoff.py` | Передача сессии |
| `ai_ops_kit/engops/session_launcher.py` | Запуск сессии |
| `ai_ops_kit/engops/session_telemetry.py` | Телеметрия сессии |
| ... | (ещё ~7 модулей) |

**Проблемы:**
- `deploy_readiness.py` — это gate-логика, но лежит в engops. Вызывается из gate_executor (lazy). Граница размыта: это engops-концерн или gate?
- Engops — самый «разношёрстный» пакет: session management, deploy readiness, architecture baseline, delegation advisor — разные предметные области в одном пакете.

#### Пакет providers (9 модулей, ~1200 строк)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/providers/orchestrator.py` | HTTP-оркестратор (model calls) |
| `ai_ops_kit/providers/model_router.py` | Маршрутизация моделей |
| `ai_ops_kit/providers/cost_account.py` | Учёт стоимости |
| `ai_ops_kit/providers/provider_endpoints.py` | Эндпоинты провайдеров |
| `ai_ops_kit/providers/response_contract.py` | Контракты ответов |
| ... | (ещё ~4 модуля) |

**Оценка:** Providers чист после переезда `usage_ledger` и `budget` в shared.

---

### Intelligence (слой 4)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/intelligence/product_health.py` | Детерминированный health score (adoption, retention, errors, ...) |
| `ai_ops_kit/intelligence/effect_metrics.py` | Метрики эффекта |
| `ai_ops_kit/intelligence/evolution_triggers.py` | ADR-vs-reality evolution triggers |
| `ai_ops_kit/intelligence/health_product.py` | Продуктовое здоровье |
| `ai_ops_kit/intelligence/health_tech.py` | Техническое здоровье |
| `ai_ops_kit/intelligence/health_delivery.py` | Здоровье delivery |
| `ai_ops_kit/intelligence/drift_artifacts.py` | Артефакты дрейфа |
| `ai_ops_kit/intelligence/nightly_review.py` | Ночной обзор |
| Аналитика исходов | Аналитика outcomes (не подключён к поставке) |
| `ai_ops_kit/intelligence/product_audit.py` | Продуктовый аудит |
| Советник рефакторинга | Рекомендации по рефакторингу (не подключён к поставке) |
| `ai_ops_kit/intelligence/risk_register.py` | Реестр рисков |
| Наблюдение за сессиями | Мониторинг активных сессий (не подключён к поставке) |
| `ai_ops_kit/intelligence/team_sync.py` | Командная синхронизация |
| Петля решений | Замыкание governance-контура (не подключён к поставке) |
| ... | (ещё ~5 модулей) |

**Оценка:** Intelligence чист. Зависит от kernel (читает события), kernel не зависит от него. Инвариант проверяется layering validator.

---

### Entrypoints (слой 5)

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/cli/ai_ops_cli.py` | Intent-based CLI |
| Пакет `devtools` (12 модулей) | Bench, changelog, gate evals, model comparison, mutation probe, ... |
| Пакет `validation` (80+ модулей) | Invariant validators (один на concern) |

**Оценка:** Entrypoints чисты. Вызываются процессом, не импортируются как библиотеки.

---

## Где ответственность дублируется

### 1. Evidence collection: gates vs engine

`ai_ops_kit/engine/pipeline_evidence.py` собирает evidence в рамках pipeline. `ai_ops_kit/gates/evidence_collector.py` собирает evidence для gates. Оба работают с инструментами (build/lint/test), но по-разному.

**Рекомендация:** Определить, кто владелец. Если evidence — это gate-концерн (доказательство для gate), то `pipeline_evidence.py` должен делегировать в `evidence_collector.py`, а не дублировать. Если evidence — это engine-концерн (данные для pipeline), то `evidence_collector.py` не должен знать про tool_broker напрямую.

### 2. Cost accounting: providers vs shared

`tools/usage_ledger.py` — учёт cost/token. `tools/budget.py` — примитив бюджета. `ai_ops_kit/providers/cost_account.py` — учёт стоимости провайдеров.

**Рекомендация:** Чёткое разделение: `shared` — примитивы (запись, чтение); `providers` — бизнес-логика (тарификация, маршрутизация по стоимости). Сегодня, похоже, так и есть, но стоит зафиксировать.

### 3. Health: intelligence vs engops

`ai_ops_kit/intelligence/product_health.py` — health score. Пакет `engops` — deploy readiness, architecture baseline. Оба оценивают «здоровье», но с разных сторон.

**Рекомендация:** Intelligence — продуктовое здоровье (adoption, retention). Engops — инженерное здоровье (deploy readiness, branch policy). Граница уже чёткая по слоям, но стоит документировать.

---

## Где границы размыты

### 1. ai_route — engine или domain?

`ai_ops_kit/engine/ai_route.py` (317 строк) — классификация work item по реестрам. Это предметная логика (domain), но лежит в engine. `ai_ops_kit/lifecycle/workitem.py` импортирует его — и это создаёт mutual pair engine ↔ lifecycle.

**Проблема:** Переезд в `shared` снимает цикл, но нарушает AC-01 (domain не должен быть в foundation). Переезд в `checks` (primitives) — возможный компромисс, но classification — не check.

**Рекомендация:** Проектирование, а не переезд. Решить «кто классифицирует» (AC-03): если workitem не должен звать роутер сам — классификация становится отдельным шагом, и цикл исчезает.

### 2. deploy_readiness — engops или gates?

`ai_ops_kit/engops/deploy_readiness.py` лежит в engops, но вызывается из `ai_ops_kit/gates/gate_executor.py`. Это gate-логика (проверка готовности к deployment), но packaged как engops.

**Проблема:** Если deploy readiness — gate, почему не в пакете `gates`? Если engops — почему gate_executor его вызывает?

**Рекомендация:** Переместить в пакет `gates` (как provider, не как executor) или формализовать: engops предоставляет данные, gates оценивает.

### 3. execution_pipeline — 1193 строки

Слишком крупный модуль. Содержит: orchestration, evidence collection, gate invocation, commit logic, delivery trigger.

**Проблема:** Модуль с 7+ ответственностями — кандидат на split. Но split — это рефакторинг, и он должен быть отдельным спринтом.

**Рекомендация:** Не трогать в этом спринте. Зафиксировать как known tech debt.

### 4. Пакет engops — 18 модулей, разные предметные области

Session management (boundary, guardrails, handoff, launcher, telemetry), deploy readiness, architecture baseline, branch/commit policy, delegation advisor — всё в одном пакете.

**Проблема:** Пакет стал «свалкой» для всего, что не fits в другие пакеты. Не нарушает layering, но затрудняет навигацию.

**Рекомендация:** Рассмотреть разделение на подпакеты: session management и policy (branch/commit/deploy). Не срочно.

---

## Конкретные предложения по рефакторингу

> ⚠️ **Это анализ, не план реализации.** Каждый пункт — отдельный спринт.

### Приоритет 1: Снять mutual pairs (зависит от ратчета)

| # | Действие | Снимает пару | Сложность |
|---|----------|-------------|-----------|
| 1 | evidence_collector получает tool_broker как параметр (DI), не импортирует напрямую | engine ↔ gates | Низкая |
| 2 | Формализовать: delivery вызывается ТОЛЬКО из ai_ops_run, добавить контракт-тест | delivery ↔ engine | Низкая |
| 3 | deploy_readiness переезжает в пакет gates как provider | engops ↔ gates | Средняя |
| 4 | context_compiler использует run_plan как TypedDict-контракт, не как импорт | context ↔ engine | Средняя |

### Приоритет 2: Уменьшить размер крупных модулей

| # | Действие | Модуль | Сложность |
|---|----------|--------|-----------|
| 5 | Выделить orchestration из execution_pipeline в отдельный модуль | `ai_ops_kit/engine/execution_pipeline.py` (1193) | Высокая |
| 6 | Разделить workitem на status derivation + routing | `ai_ops_kit/lifecycle/workitem.py` | Средняя |

### Приоритет 3: Улучшить навигацию

| # | Действие | Пакет | Сложность |
|---|----------|-------|-----------|
| 7 | Подпакеты в engops: session, policy | Пакет `engops` | Низкая |
| 8 | Документировать ответственность каждого модуля в docstring | все | Низкая |

---

## Ссылки

- [ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md) — 15 архитектурных правил
- [DEPENDENCY_DAG.md](DEPENDENCY_DAG.md) — граф зависимостей и ratchet-план
- `packages/layering.yaml` — source of truth для слоёв
