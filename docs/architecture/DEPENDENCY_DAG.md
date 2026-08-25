# Dependency DAG — AI Ops Kit

> **Статус:** baseline зафиксирован · Sprint 1 (2026-08-25)
> **Источник истины:** `packages/layering.yaml` + `ai_ops_kit/validation/validate_layering.py`
> **Последний замер:** v3.38 (лента №5) — 5 взаимных пар, 11 циклов, 262 внутренних импорта

---

## Текущее состояние

### Слои и направления

```
┌─────────────────────────────────────────────────────────────────────┐
│ 5. entrypoints    cli · devtools · validation                       │  ← вызов процессом
├─────────────────────────────────────────────────────────────────────┤
│ 4. intelligence   product_health · effect_metrics · evolution_...   │  ← читает kernel
├─────────────────────────────────────────────────────────────────────┤
│ 3. capabilities   context · providers · lifecycle · gates ·         │  ← кольцо ядра
│                     engine · delivery · engops · planning            │    (внутренние связи
│                                                                      │     разрешены)
├─────────────────────────────────────────────────────────────────────┤
│ 2. primitives     security · ui · integrations · governance · checks│  ← только foundation
├─────────────────────────────────────────────────────────────────────┤
│ 1. foundation     shared                                            │  ← лист (0 исходящих)
└─────────────────────────────────────────────────────────────────────┘
```

### Замер (v3.38, после развязки всех cross-layer рёбер)

| Метрика | Значение | Потолок (ратчет) |
|---------|----------|-------------------|
| Взаимных пар (mutual pairs) | **5** | 5 |
| Циклов длиннее 2 | **11** | 11 |
| Внутренних импортов | **262** | — |
| Cross-layer нарушений | **0** | 0 |
| Known violations | **0** (пуст) | — |

### 5 оставшихся взаимных пар (все внутри capabilities)

| # | Пара | Корень | Импорт A→B | Импорт B→A | Статус |
|---|------|--------|------------|------------|--------|
| 1 | **engine ↔ gates** | Pipeline запускает gates; evidence collection нужен tool_broker | `execution_pipeline` → `gate_executor` | `evidence_collector` → `tool_broker` | Внутри кольца |
| 2 | **engine ↔ lifecycle** | Контроллер трекает work items; workitem зовёт роутер | `ai_ops_run` → `workitem` | `workitem` → `ai_route` | Дизайн-решение: «кто классифицирует» |
| 3 | **context ↔ engine** | Context compilation нужен run plan; engine нужен compiled context | `context_compiler` → `run_plan` | `execution_pipeline` → `context_compiler` | Lazy-импорты в engine |
| 4 | **delivery ↔ engine** | Review использует pipeline; pipeline зовёт delivery для PR | `review_branch` → `execution_pipeline` | `execution_pipeline` → `pr_open` (lazy) | Transaction boundary |
| 5 | **engops ↔ gates** | Deploy readiness — engops, но оценивается как gate; economic preflight — gate, но нужен advisor | `gate_executor` → `deploy_readiness` (lazy) | `engineering_advisor` → `economic_preflight` (lazy) | Lazy-импорты |

---

## История ратчета

### От невидимого к считаемому (v3.34)

До v3.34 валидаторы не были пакетом. 6 пакетов ядра импортировали валидаторы по плоскому имени; валидаторы импортировали модули движка. Для графа этих рёбер не существовало — не было вершины `validation`.

Перенос в `ai_ops_kit/validation/` дал вершину — и невидимое стало считаемым:

| Замер | Взаимных пар | Циклов | Причина |
|-------|-------------|--------|---------|
| v3.31 (до пакета) | ~6 (невидимых) | ~31 (невидимых) | Методика не видела validation |
| v3.34 (пакет появился) | **12** | **210** | Все рёбра стали видимы; 210 = корректный замер (31 был ошибкой — считал ротации) |

### Развязка cross-layer рёбер (v3.34 → v3.38)

Все 7 cross-layer пар сняты одним способом: чистую проверяющую логику вынесли ВНИЗ в `checks` (primitives), и рантайм перестал тянуть `validation` (entrypoints) вверх.

| Лента | Снятая пара | Как | Пар | Циклов |
|-------|-------------|-----|-----|--------|
| Переезды v3.34 | `gates ↔ providers`, `engops ↔ providers` | `usage_ledger` → `shared` | 12→10 | — |
| Переезды v3.34 | `engine ↔ engops` | `gitio` → `shared` | 10→9 | — |
| Переезды v3.34 | `engine ↔ providers` | `budget` → `shared` | 9→8 | — |
| Переезды v3.34 | `gates ↔ lifecycle` | `lifecycle_store` → `shared` | 8→7 | — |
| Лента №4 | `security ↔ validation` | `memory_governance.check` → `checks` | 7→6 | 52→28 |
| Лента №5 | `engine ↔ validation`, `providers ↔ validation` | Чистые проверки + разрез `render` | 6→5 | 28→17 |
| Лента №5 (шаг 2) | `lifecycle ↔ validation` | `feature_blueprint`/`cross_artifacts` → `checks` | 5 | 17→11 |
| Лента №5 (шаг 3) | `intelligence ↔ validation` | `quality_attributes`/`architecture_decision`/`adr_registry` → `checks` | 5 | 11 (ребро не в цикле) |

### Итого: путь от 210 до 11

```
210 ──→ 52 ──→ 28 ──→ 17 ──→ 11 ──→ ?
 │        │       │       │       │
 │        │       │       │       └── текущий baseline (v3.38)
 │        │       │       └── lifecycle→validation снята
 │        │       └── engine→validation + providers→validation сняты
 │        └── security→validation снята (одно ребро держало многие циклы)
 └── исходный замер при появлении validation как пакета
```

---

## Ratchet план: 11 → 0

### Этап 1: 11 → 7 (снять самые простые)

| Пара | Стратегия | Сложность |
|------|-----------|-----------|
| **engops ↔ gates** | `deploy_readiness` — чистая функция проверки; вынести в `checks` или в `gates` как provider. `economic_preflight` — уже в gates; advisor зовёт его внутри своего слоя. | Низкая |
| **delivery ↔ engine** | Все импорты engine→delivery уже lazy. Формализовать: delivery вызывается ТОЛЬКО из `ai_ops_run`, pipeline не знает про delivery. Добавить контракт-тест. | Низкая |

### Этап 2: 7 → 4 (дизайн-решения)

| Пара | Стратегия | Сложность |
|------|-----------|-----------|
| **context ↔ engine** | `context_compiler` зовёт `run_plan` для knowing which gates to compile. Разорвать: run_plan как контракт (TypedDict), не как импорт. Context компилируется по контракту плана, не по его реализации. | Средняя |
| **engine ↔ gates** | `evidence_collector` зовёт `tool_broker` для запуска build/lint/test. Разорвать: evidence_collector получает broker как параметр (dependency injection), не импортирует напрямую. | Средняя |

### Этап 3: 4 → 0 (архитектурные решения)

| Пара | Стратегия | Сложность |
|------|-----------|-----------|
| **engine ↔ lifecycle** | `workitem` зовёт `ai_route` для классификации. Решение: «кто классифицирует» — не workitem. Классификация — отдельный шаг перед lifecycle, или `ai_route` переезжает в `shared` (но это предметная логика, не foundation — см. комментарий в layering.yaml). | Высокая |

---

## Самые проблемные циклы

### Топ-3 по количеству модулей в цикле

1. **engine → gates → engops → engine** (длина 3)
   - `execution_pipeline` → `gate_executor` → `deploy_readiness` (lazy) → `execution_pipeline`
   - Все 3 импорта существуют в production code; 2 из 3 — lazy

2. **engine → lifecycle → gates → engine** (длина 3, через workitem)
   - `ai_ops_run` → `workitem` → `ai_route` (engine); `workitem` → gate evaluation (gates); `evidence_collector` → `tool_broker` (engine)
   - Корень: workitem — слишком толстый; знает и про routing, и про gates

3. **engine → context → engine** (длина 2, mutual pair)
   - `context_compiler` → `run_plan` (engine); `execution_pipeline` → `context_compiler` (context, lazy)
   - Корень: context compilation нуждается в плане, план нуждается в контексте — классический circular dependency

### Топ-3 по влиянию на codebase

1. **engine ↔ gates** — 6+ модулей engine импортируют gates; 2+ модуля gates импортируют engine. Самый «плотный» цикл.
2. **engine ↔ lifecycle** — `ai_route` (317 строк) — предметная логика классификации, не infrastructure. Переезд в `shared` снял бы цикл, но положил бы domain-логику в foundation — это то, что constitution исправляет (AC-01).
3. **context ↔ engine** — context compilation и execution pipeline связаны по данным (context bundle); развязка требует контракта, а не переезда.

---

## Правила для новых dependencies

### Запрещено (краснеет на CI)

1. **Зависимость вверх по слоям.** Foundation ← primitives ← capabilities ← intelligence ← entrypoints. Зависимость от более высокого слоя к более низкому — ОК. Наоборот — НЕТ.
2. **Foundation тянет что-либо.** `shared` — лист. Любой его импорт — потенциальный цикл через весь граф.
3. **Продуктовый код тянет devtools.** Devtools не едет в child-репозиторий; зависимость от него ломает поставку.
4. **Новый cross-layer mutual pair.** Все cross-layer пары сняты. Новая = регрессия.
5. **Ratchet превышен.** 5 пар / 11 циклов — потолок. Превышение = CI fail.

### Разрешено (зелёное)

1. **Внутренние связи capabilities.** Это кольцо, не лестница. Связи внутри допустимы — но ратчет запрещает расти.
2. **Lazy-импорты внутри capabilities.** If-function import — допустимый способ отложить зависимость до момента вызова. Формально цикл остаётся, но runtime-нагрузка снижается.
3. **Foundation как зависимость.** Любой пакет вправе зависеть от `shared`. Это дизайн, а не нарушение.

### Требует обоснования (жёлтое)

1. **Новый импорт между capabilities-пакетами.** Не запрещён, но если создаёт новую mutual pair — ратчет покраснеет. Обоснование: почему нельзя через контракт / DI / переезд в `checks`.
2. **Импорт из entrypoints в runtime.** `validation` вызывается процессом, не импортируется. Если нужен импорт — значит, логика не в том слое.
3. **Intelligence → capabilities.** Разрешено (intelligence выше). Но capabilities → intelligence запрещено — и это инвариант «kernel не зависит от аналитики».

---

## Как мерить

```bash
# Текущие числа
python ai_ops_kit/validation/validate_layering.py --counts

# Полный граф рёбер
python ai_ops_kit/validation/validate_layering.py --graph

# Проверка (возврат 0 = чисто)
python ai_ops_kit/validation/validate_layering.py

# Contract-тесты
pytest tests/contracts/test_architecture_constitution.py -v
```

---

## Ссылки

- [ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md) — 15 архитектурных правил
- [REFACTORING_MAP.md](REFACTORING_MAP.md) — карта модулей и предложений по рефакторингу
- [packages/layering.yaml](../../packages/layering.yaml) — source of truth для слоёв и ратчета
- [validate_layering.py](../../ai_ops_kit/validation/validate_layering.py) — исполнитель проверок
