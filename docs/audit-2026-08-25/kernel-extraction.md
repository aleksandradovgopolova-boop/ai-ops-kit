# AI Ops — граница ядра и план извлечения (strangler)

**Дата:** 2026-08-25 · **База:** `/Users/sasad/ai-ops-kit` v3.37.0 · измерено по реальному импорт-графу и `packages/layering.yaml`.
**Принцип:** не «AI Ops v2 с нуля», а вырезание резкого ядра из нынешнего кода. Каждый шаг измерим существующим ратчетом слоёв; полевой корпус (тесты, квалификация, field-fixes) сохраняется.

---

## 0. Сущность ядра (несокрушимая ценность продукта)

Ядро — это одна детерминированная транзакция вокруг недетерминированного исполнителя:

```
Task
 → classify (роль/workflow/риск)          детерминированно, по реестрам
 → spec-gate (достаточность спеки)         fail-closed: нет спеки → стоп
 → execute(ExecutorPort)                   ЕДИНСТВЕННЫЙ вероятностный шаг, за портом
 → evidence (build/lint/test/scan)         детерминированный сбор
 → gate (fail-closed, writer≠judge)        blocking без доказуемости → fail
 → derive_status                           чистая функция от (gate results, run report)
 → deliver(DeliveryPort)                   идемпотентно, проверка SHA
 → usage/decision-log                      честно: unavailable ≠ 0, actor у каждой записи
```

Всё, что не в этой цепочке (аналитика, планирование, сессии, research, product-learning), — **не ядро**, а спутник.

---

## 1. Граница: что внутри, что снаружи

Классификация нынешних пакетов `ai_ops_kit/*` (числа — реальные исходящие рёбра импорта).

| Роль в целевой архитектуре | Нынешние пакеты/модули | Что делает | Действие |
|---|---|---|---|
| **KERNEL — foundation** | `shared` (contracts, gitio, budget, usage_ledger, lifecycle_store, path_hygiene) | контракты и I/O-примитивы; лист графа (out=0) | оставить как есть |
| **KERNEL — spine** | `engine` **минус** `ai_route`, минус тяжёлый `parallel_*` | execution_pipeline, ai_ops_run (транзакция), tool_loop, tool_broker, worktree, acceptance_verify, pipeline_evidence, run_handoff | расщепить God-функции на фазы (шаг 3) |
| **KERNEL — gates** | `gates` **плюс** `deploy_readiness` (сейчас в `engops`) | gate_executor, gate_policy, gate_result_v2, spec_levels, verification_tiers, evidence_collector, approvals, preflight | принять deploy_readiness (шаг 1.5) |
| **KERNEL — state** | `lifecycle`: workitem.derive_status, run_report, active_work | детерминированная машина состояний WorkItem | вынуть классификацию (шаг 2) |
| **KERNEL — delivery** | `delivery`: pr_open, review_branch | верифицированная доставка draft PR | формализовать вызов только из ai_ops_run (шаг 1) |
| **KERNEL — governance** | `governance` (517 строк): policy_engine, enforcement, decision_log, human_override | автономия/HITL, fail-closed до require_approval | оставить в ядре |
| **PORTS (шов ядра)** | новый `kernel/ports.py` | ExecutorPort, ContextPort, EvidenceProvider, GatePort, DeliveryPort, PolicyPort | создать (шаг 0) |
| **ADAPTERS (сменные, за портом)** | `providers` (ExecutorPort), `context` (ContextPort), `security` scan (EvidenceProvider), `integrations/github` | реализации портов; заменяемы без правки ядра | развязать через порт (шаг 1, 5) |
| **PRIMITIVES (ядро зовёт ВНИЗ — разрешено)** | `checks`, `ui/presenter` | чистая проверяющая логика; форматирование вывода | оставить |
| **SATELLITES (читают события ядра, версионируются отдельно, вправе отставать)** | `planning`, `intelligence`, `engops` (session_*, advisors, branch/commit policy), `research`, `product-learning` | планирование, аналитика, сессии, исследования | отрезать по контракту событий (шаг 6) |
| **ENTRYPOINTS (процесс, не импорт)** | `cli`, `validation`, `devtools` | точки входа, валидаторы инвариантов | оставить |

**Целевой размер ядра:** ~4–6k строк тестируемой по ветвям логики (сегодня та же логика размазана внутри `engine` 9355 + `gates` 3998 + `lifecycle` 1923 + `delivery` 441 + `governance` 517, причём заперта в God-функциях `run` 1477 и `run_pipeline` 1077).

---

## 2. Порты — единственный шов между ядром и остальным

```python
# kernel/ports.py — Protocol'ы (structural typing, stdlib только)
class ExecutorPort(Protocol):        # реализует providers/ (или внешний рантайм в шаге 5)
    def run(self, spec: ExecutionSpec) -> ExecutionResult: ...
class ContextPort(Protocol):         # реализует context/ ; ядро принимает готовый ContextBundle
    def build(self, task: Task, budget: Budget) -> ContextBundle: ...
class EvidenceProvider(Protocol):    # реализуют gates/evidence_collector, security/security_scan, checks/
    def collect(self, change: Change) -> Evidence: ...
class GatePort(Protocol):            # gates/gate_executor
    def evaluate(self, evidence: Evidence, workflow: Workflow) -> list[GateResultV2]: ...
class DeliveryPort(Protocol):        # delivery/pr_open
    def deliver(self, handoff: RunHandoff) -> DeliveryReceipt: ...
class PolicyPort(Protocol):          # governance/policy_engine
    def decide(self, action: Action, ctx: RunContext) -> Autonomy: ...
```

Ядро зависит ТОЛЬКО от этих Protocol'ов и от контрактов в `ai_ops_kit/shared/contracts.py`. Реализации внедряются на входе (`ai_ops_run`), не импортируются в глубине.

---

## 3. Ключевой факт: граница ядра = 5 взаимных пар

Это извлечение — **не новая работа поверх карты рефакторинга, а она же с названным пунктом назначения.** Все 5 замороженных взаимных пар (`packages/layering.yaml → baseline.mutual_pairs: 5`, все внутри `capabilities`) — это ровно те рёбра, что размывают границу ядра. Снять их = вырезать ядро.

| Взаимная пара | Реальное ребро (проверено) | Разрыв = извлечение |
|---|---|---|
| `engine ↔ lifecycle` | `ai_ops_kit/lifecycle/workitem.py` → `engine/ai_route` | вынести классификацию из workitem в шаг ядра `classify` |
| `engine ↔ gates` | `gates/evidence_collector` → `engine/tool_broker` | broker внедряется как `EvidenceProvider` (DI), не импортируется |
| `context ↔ engine` | `context/context_compiler.py:38` → `engine/run_plan` | run_plan как TypedDict-контракт, не импорт модуля |
| `delivery ↔ engine` | `engine/execution_pipeline` ↔ `delivery` (lazy) | delivery зовётся только из `ai_ops_run` через DeliveryPort + контракт-тест |
| `engops ↔ gates` | `gates/gate_executor.py:313` → `engops/deploy_readiness` (+ `sys.path`-хак :301-310) | перенести `deploy_readiness` в `gates` |

Снятие пятой пары превращает `capabilities` из кольца в DAG — именно то, что нужно ядру.

---

## 4. План извлечения (strangler, по шагам)

Каждый шаг: цель · файлы · что двигает ратчет · effort · риск · зависимости.

### Шаг 0 — Объявить порты и контракт ядра (без переезда кода)
- **Цель:** зафиксировать целевой шов; чистое добавление.
- **Файлы:** новый ports.py в пакете kernel (создаётся), расширить `ai_ops_kit/shared/contracts.py` (ExecutionSpec, ExecutionResult, ContextBundle, RunContext).
- **Ратчет:** не двигает (только новые Protocol'ы).
- **Effort:** S · **Риск:** очень низкий · **Зависимости:** нет.

### Шаг 1 — Снять 4 «лёгкие» пары через DI/контракт
- **Цель:** `engine↔gates`, `context↔engine`, `delivery↔engine`, `engops↔gates` → DAG.
- **Файлы:** `ai_ops_kit/gates/evidence_collector.py` (принять broker параметром), `context/context_compiler.py:38` (TypedDict вместо импорта), `ai_ops_kit/engine/execution_pipeline.py` + `ai_ops_kit/engine/ai_ops_run.py` (delivery только транзакционно) + контракт-тест, перенос `engops/deploy_readiness.py → gates/deploy_readiness.py` (убрать `sys.path`-хак `gate_executor.py:301-310`).
- **Ратчет:** `mutual_pairs 5 → 1` в `layering.yaml` (вниз — легально).
- **Effort:** M · **Риск:** низкий (это priority-1 из их REFACTORING_MAP) · **Зависимости:** шаг 0.

### Шаг 2 — Вынести классификацию из `workitem` (корневая пара)
- **Цель:** `engine↔lifecycle` → 0; workitem перестаёт знать про routing.
- **Файлы:** `ai_ops_kit/engine/ai_route.py` → шаг ядра `classify(task) -> Classification`; `ai_ops_kit/lifecycle/workitem.py` перестаёт импортировать engine, `derive_status()` остаётся чистой функцией.
- **Ратчет:** `mutual_pairs 1 → 0`. Кольцо capabilities официально стало DAG.
- **Effort:** M · **Риск:** средний (workitem — центральный объект; нужен контракт-тест на derive_status до правки) · **Зависимости:** шаг 1.

### Шаг 3 — Расщепить God-функции на фазы за портами
- **Цель:** критический путь тестируем по ветвям.
- **Предусловие (обязательно):** сперва покрыть фазы характеристическими тестами (иначе рефакторинг вслепую) — совпадает с TEST-1 из аудита.
- **Файлы:** `engine/execution_pipeline.run_pipeline` (1077) → `detect / worktree / install / spec_gate / execute / evidence / gate / commit` как отдельные функции; `engine/ai_ops_run.run` (1477) → тонкий транзакционный контроллер, вызывающий фазы + DeliveryPort.
- **Ратчет:** не про циклы — про размер/тестируемость (можно завести derived-метрику max-func-lines как новый ратчет).
- **Effort:** L · **Риск:** средний (снижается характеристическими тестами) · **Зависимости:** шаг 2, TEST-1.

### Шаг 4 — Закрепить границу пакета ядра
- **Цель:** сделать «ядро не зависит от спутника» проверяемым, а не подразумеваемым.
- **Файлы:** `packages/layering.yaml` — ввести супер-слой `kernel` = {shared, engine, gates, lifecycle, delivery, governance} + правило «kernel не импортирует planning/intelligence/engops-satellite»; тест в `ai_ops_kit/validation/validate_layering.py`.
- **Ратчет:** новое правило (не число) — краснеет на нарушении границы ядра.
- **Effort:** S · **Риск:** низкий · **Зависимости:** шаги 1–2.

### Шаг 5 — (опционально, по данным) заменить самописную инфраструктуру за ExecutorPort
- **Цель:** снять свой tool-loop / durable-транзакцию / worktree, если внешний рантайм делает надёжнее (это ИХ инвариант «свой tool-loop не наращиваем»).
- **Файлы:** новая реализация `ExecutorPort` поверх внешнего агент-рантайма/durable-движка; старый `ai_ops_kit/engine/tool_loop.py` остаётся как fallback-реализация того же порта.
- **Ратчет:** не двигает (за портом).
- **Effort:** L–XL · **Риск:** средний, но ИЗОЛИРОВАН портом · **Зависимости:** шаги 0–3; **решение о запуске — только по замеру**, стоит ли самописный лишних денег/багов.

### Шаг 6 — Спутники на контракте событий
- **Цель:** `planning/intelligence/engops-satellite/research/product-learning` читают стабильный `KernelEvent`, версионируются отдельно, вправе отставать; отключение любого не ломает доставку (у них это уже наполовину так — слой intelligence выше ядра).
- **Файлы:** контракт `KernelEvent` в `ai_ops_kit/shared/contracts.py`; спутники переключаются с прямых импортов ядра на события; тест «off-switch спутника не ломает delivery».
- **Ратчет:** правило «спутник не импортируется ядром» (частично уже есть для intelligence).
- **Effort:** M · **Риск:** низкий · **Зависимости:** шаг 4.

---

## 5. Что это даёт и чего стоит

**Даёт:**
- Кольцо `capabilities` → DAG (шаги 1–2): пакеты снова можно рассуждать/тестировать/извлекать по отдельности (закрывает ARC-1).
- Критический путь тестируем по ветвям (шаг 3): бьёт в корень «тесты не ловят дефекты» (ARC-2/TEST-1).
- Инфраструктура сменна за портом (шаг 5): реализует их же инвариант, снимает самописный долг (ARC-5, часть INT-1).
- Амбиция изолирована: спутники отстают, не роняя ядро (закрывает риск масштабирования и PROD-1).

**Стоит:** шаги 0–2,4 — недели, низкий/средний риск, это их же карта рефакторинга. Шаг 3 — отдельный спринт (с тестами вперёд). Шаг 5 — крупный, но опциональный и по данным. **Полевой корпус (тесты/квалификация/field-fixes) сохраняется целиком — ничего не выбрасывается.**

**Как понять, что работает (метрики):** `mutual_pairs` 5→0; `cycles_longer_than_two` 11→снижение; max-func-lines ratchet вниз; доля покрытия под integration-сбором вверх; отключение любого спутника оставляет `./ai-ops run … --execute` зелёным.

---

## 6. Решения, которые твои (не мои)

1. **Амбиция:** острое ядро + спутники (моя рекомендация) vs единая платформа. От этого зависит, режем ли мы спутники агрессивно (шаг 6) или мягко.
2. **Шаг 5 — запускать ли замену рантайма?** Только по замеру стоимости самописной инфраструктуры. По умолчанию — НЕ трогать, оставить за портом «на потом».
3. **Порядок vs аудит:** этот план — это Phase 2 (Architecture) из аудита. Phase 0 (снять ложную уверенность: INT-1/2/4/5, permissions) я бы сделал ДО него — иначе извлечение унаследует те же тихие расхождения.

---

*Всё измерено на ревизии рабочего дерева `architecture-hardening-sprint` (8 незакоммиченных изменений; я ничего не трогал, анализ read-only). Числа рёбер — из реального импорт-графа; пары — из `packages/layering.yaml → baseline`.*
