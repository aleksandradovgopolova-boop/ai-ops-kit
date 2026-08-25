# Architecture Constitution — AI Ops Kit

> **Статус:** действующий инвариант · Sprint 1 (2026-08-25)
> **Проверка:** `tests/contracts/test_architecture_constitution.py` + `validate_layering.py`
> **Обновление:** только осознанно, с фиксацией в CHANGELOG и поднятием/опусканием ратчета

---

## Зачем этот документ

Код растёт быстрее, чем осознанность в нём. Когда система достигает ~350 модулей и 262 внутренних импортов, «так исторически сложилось» перестаёт работать — нужны исполняемые правила, а не пожелания.

Этот документ — 15 архитектурных правил, каждое из которых:
1. **Сформулировано** однозначно (не «старайтесь», а «запрещено»)
2. **Обосновано** (почему нарушение ломает систему)
3. **Проверяемо** (какой тест или валидатор ловит нарушение)

Правила не все одинаково автоматизируемы. AC-01 и AC-11 проверяются кодом на каждом CI-прогоне. AC-14 и AC-15 требуют дизайн-ревью. Но даже неавтоматизированное правило — не декорация: оно явно, и PR, нарушающий его, обязан объяснить почему.

---

## AC-01: Domain не импортирует infrastructure

**Формулировка.** Модули предметной области (`checks`, `governance`, `gates`, `lifecycle`, `intelligence`) не импортируют инфраструктурные модули (`shared.gitio`, `shared.path_hygiene`, провайдеры HTTP, CLI-парсеры).

**Почему важно.** Domain-логика — это то, что делает kit полезным. Infrastructure — то, как kit работает на конкретной машине. Если домен зависит от инфраструктуры, вы не можете перенести домен в другую среду без переписывания. Сегодня `shared` — foundation (слой 0), и все примитивы зависят от него — это разрешено. Запрещено обратное: чтобы foundation тянул что-либо выше.

**Как проверяется.**
- `validate_layering.py` — правило `foundation-is-a-leaf`: `shared` не импортирует ничего.
- `test_domain_does_not_import_infrastructure` — AST-проверка: модули из `checks/`, `governance/` не содержат `import` на модули, которые в свою очередь импортируют `subprocess`, `http`, `argparse`.
- Слои в `packages/layering.yaml`: primitives зависит только от foundation.

---

## AC-02: ProductChange не зависит от WorkItem implementation details

**Формулировка.** Продуктовое изменение (feature, fix, refactor) описывается контрактом (`shared/contracts.py`: `WorkItemState`, `DeliveryIntent`), а не внутренними полями `lifecycle/workitem.py`. Потребитель WorkItem работает через контракт, а не через `workitem._route()` или `workitem._classify()`.

**Почему важно.** WorkItem — центральный объект, его меняют чаще всего. Если внешний код знает про `_route`, `_classify`, `_blueprint` — любое изменение внутри WorkItem ломает N потребителей. Контракт стабилен; реализация — нет.

**Как проверяется.**
- Дизайн-ревью: PR, добавляющий импорт из `lifecycle.workitem` вне `engine/` и `lifecycle/`, обязан обосновать.
- `test_public_surface.py` — проверяет, что declared API surface совпадает с реальным.

---

## AC-03: WorkItem имеет ровно один lifecycle owner

**Формулировка.** Каждый WorkItem в любой момент времени имеет ровно одного owner'а — агента или человека, ответственного за следующий переход. Нет «совместного владения».

**Почему важно.** Совместное владение = ничейное владение. Если два агента считают, что отвечают за один WorkItem, они либо дублируют работу, либо конфликтуют. Один owner — один переход за раз — детерминированная машина состояний.

**Как проверяется.**
- `lifecycle/active_work.py` — `active_work()` возвращает единственного owner'а.
- `test_execution_path_reconciled.py` — reconciliation проверяет, что каждый WorkItem имеет owner.
- `governance/decision_log.py` — каждая запись имеет ровно одного `actor`.

---

## AC-04: State не вычисляется из нескольких источников

**Формулировка.** Состояние WorkItem (`done`, `blocked`, `needs_human_decision`, `needs_more_evidence`) вычисляется детерминированно из ЕДИНСТВЕННОГО источника — `gate_executor.evaluate()` + `run_report.build_report()`. Никакой другой код не вправе присваивать состояние напрямую.

**Почему важно.** Если состояние можно записать из двух мест, два источника разойдутся — и система окажется в невозможной конфигурации (один источник говорит «done», другой — «blocked»). Детерминированный источник = воспроизводимость = возможность отладки.

**Как проверяется.**
- `test_state_single_source` — AST-анализ: присваивания `state =` / `status =` в модулях lifecycle/ встречаются только в функциях, которые вызывают `gate_executor.evaluate()` или `run_report.build_report()`.
- `lifecycle/workitem.py` — статус вычисляется функцией `derive_status()`, не присваивается напрямую.
- `shared/contracts.py` — `WorkItemState` — TypedDict, не класс с setter'ами.

---

## AC-05: Gate не может быть blocking без applicability evidence

**Формулировка.** Блокирующий гейт (`blocking: true`) обязан иметь `applicability` — доказательство того, что он применим к данному изменению. Гейт без applicability evidence — это `not_applicable`, а не `fail`.

**Почему важно.** 35 гейтов в `quality/gates.yaml`. Если каждый применялся бы к каждому изменению, ни один PR не прошёл бы. Applicability — это фильтр: `architecture_review` применяется только при `architecture_change`, `deploy_readiness` — только при `deployment`. Без этого фильтра гейты становятся шумом, а шум отключают.

**Как проверяется.**
- `test_gate_has_applicability` — каждый гейт в `quality/gates.yaml` имеет непустое поле `applicability` (список workflow-типов).
- `gate_result_v2.py` — `check()` валидирует: `status=not_applicable` требует `applicability=not_applicable`.
- `test_process_applicability.py` — gate coverage matrix проверяет, что PRODUCT/CRITICAL имеют полный контур.

---

## AC-06: ABSTAIN не является FAIL

**Формулировка.** `abstain` — это субъективное сомнение ревьюера, которое калибровка НЕ считает блоком (для advisory) или передаёт человеку (для blocking). Это не `fail`, не `warn`, а отдельный статус с отдельной семантикой.

**Почему важно.** Если `abstain` деградирует в `fail`, ревьюеры перестают воздерживаться — и система теряет канал «я не уверен, но не буду блокировать». Если деградирует в `warn` — blocking-abstain (человек должен решить) тихо проходит. Два вида abstain (advisory-abstain и blocking-abstain) имеют разную семантику, и смешивать их нельзя.

**Как проверяется.**
- `gate_result_v2.py` — `check()` валидирует: advisory-abstain → `resolution=resolved, delivery_allowed=true`; blocking-abstain → `resolution=pending_human, delivery_allowed=false, human_handoff=true`.
- `to_v1()` — blocking-abstain деградирует в `fail` (fail-closed), advisory-abstain — в `warn`. Не наоборот.
- `STATUS_V2 = {"pass", "warn", "fail", "not_applicable", "abstain"}` — 5 статусов, не 3.

---

## AC-07: Delivery не является частью execution

**Формулировка.** `delivery/` (открытие PR, review ветки) — отдельный пакет, вызываемый ТОЛЬКО транзакционным контроллером (`engine/ai_ops_run.py`) после durable-фиксации RunHandoff + final report. `execution_pipeline.py` не вызывает delivery напрямую.

**Почему важно.** Pipeline — это execution: он выполняет работу. Delivery — это transaction: он доставляет результат. Если pipeline сам открывает PR, обход pipeline (например, из тестов или dry-run) не может быть безопасным. Разделение позволяет: (a) запускать pipeline без доставки, (b) доставлять без pipeline (reconciliation), (c) тестировать оба независимо.

**Как проверяется.**
- `validate_layering.py` — `delivery <-> engine` — известная взаимная пара внутри capabilities, но все импорты engine → delivery — lazy (inside-function), что зафиксировано код-ревью.
- `engine/execution_pipeline.py` — `run_pipeline` не содержит прямого вызова `_deliver_pr`; delivery вызывается только из `ai_ops_run.py` после фиксации.
- `delivery/pr_open.py` — идемпотентное открытие PR с SHA-верификацией; не знает про pipeline.

---

## AC-08: PR не является доказательством deployment

**Формулировка.** Открытый или смерженный PR — это доказательство code review, а не deployment. Deployment требует отдельного evidence: `deploy_readiness` gate + `DeliveryReceipt` с SHA-верификацией.

**Почему важно.** «PR смержен = задеплоено» — опасная иллюзия. PR может ждать deploy, deploy может провалиться, SHA может не совпасть. `delivery/pr_open.py` различает «PR открыт», «checks passed на этом SHA» и «checks unavailable» — три разных состояния, а не одно.

**Как проверяется.**
- `delivery/pr_open.py` — R-41: различает "no checks" от "checks passed" от "unavailable".
- `quality/gates.yaml` — `deploy_readiness` — отдельный blocking gate, не покрывается `code_review`.
- `shared/contracts.py` — `DeliveryReceipt` — отдельный контракт с `tested_revision` и SHA verification.

---

## AC-09: Deployment не является доказательством outcome

**Формулировка.** Успешный deployment — это доказательство того, что код работает в production. Это НЕ доказательство того, что продукт стал лучше (adoption, retention, error rate). Outcome измеряется `intelligence/` — отдельно от deployment.

**Почему важно.** «Задеплоили = стало лучше» — классическая ошибка. Deployment — output; outcome — результат для пользователя. Intelligence-слой (product_health, effect_metrics, evolution_triggers) существует именно для этого разделения. Kernel не зависит от Intelligence — потому что delivery не зависит от outcome.

**Как проверяется.**
- `validate_layering.py` — `verified_invariants: kernel-does-not-depend-on-intelligence`. Intelligence — слой ВЫШЕ capabilities; зависимость вверх запрещена.
- `intelligence/evolution_triggers.py` — сравнивает ADR-обещания с реальными метриками; это advisory signals, не gates.
- Отключение intelligence-слоя не ломает delivery.

---

## AC-10: Capability, Policy, Workflow, Gate и Evidence — разные сущности

**Формулировка.** Пять типовых сущностей не смешиваются:
- **Capability** — что система умеет (registry/capability-index.yaml)
- **Policy** — правила автономии (governance/policy_engine.py: suggest/prepare/execute/require_approval)
- **Workflow** — последовательность шагов (registry/workflows.yaml: PRODUCT, CRITICAL, QUICK, ...)
- **Gate** — контрольная точка качества (quality/gates.yaml: 35 gates)
- **Evidence** — доказательство прохождения (gate-evidence, gate-result-v2)

**Почему важно.** Когда gate становится policy, или workflow — gate, система теряет способность рассуждать о каждом типе отдельно. Policy говорит «кто решает»; gate — «что проверяется»; workflow — «в каком порядке»; evidence — «чем доказано»; capability — «что доступно». Смешение = невозможность независимо менять одно без другого.

**Как проверяется.**
- `test_capability_policy_separation` — AST-проверка: модули governance/ не определяют gate-логику; модули gates/ не определяют policy-логику.
- `registry/` — отдельные YAML-файлы для capability-index, workflows, model-roles (policy).
- `schemas/` — отдельные JSON Schema для gate-result, gate-evidence, workflow.

---

## AC-11: Новый dependency не может создавать запрещённый cycle

**Формулировка.** Новый импорт между пакетами не вправе: (a) создавать зависимость вверх по слоям, (b) увеличивать число взаимных пар или циклов сверх ратчет-потолка в `packages/layering.yaml`.

**Почему важно.** Ратчет — это не «стремиться к нулю», это «не расти». Текущий потолок: 5 взаимных пар, 11 циклов длиннее двух (все внутри capabilities). Превышение краснеет на CI. Снижение обязано быть записано в layering.yaml (ратчет ходит только вниз).

**Как проверяется.**
- `test_no_forbidden_cycles` — вызывает `validate_layering.py` и проверяет возврат 0.
- `validate_layering.py` — `ratchet_errors()` сравнивает текущие числа с baseline.
- `validate_layering.py` — `check()` проверяет отсутствие зависимостей вверх и нарушений rules.
- CI: `python ai_ops_kit/validation/validate_layering.py` — обязательный шаг.

---

## AC-12: Любой automation claim должен иметь executable evidence

**Формулировка.** Если модуль заявляет «я проверяю X» или «я генерирую Y» — это проверяемо. Нет «документационных» selftest'ов, которые всегда зелёные. Нет `# TODO: добавить проверку`, которая живёт годами.

**Почему важно.** `test_no_fake.py` — один из ключевых contract-тестов — AST-анализом проверяет, что модуль не заявляет selftest, который не запускал. Это принцип «честной декларации»: если ты говоришь «я проверил», покажи как.

**Как проверяется.**
- `test_no_fake.py` — AST-парсинг: каждый `selftest()` вызывается, а не определяется.
- `test_public_surface.py` — declared API surface совпадает с реальным.
- `quality/gates.yaml` — каждый gate имеет `validator` или `closed_by` — исполняемый способ закрытия.

---

## AC-13: Любой state transition должен быть воспроизводим

**Формулировка.** Переход WorkItem из состояния A в состояние B воспроизводим при тех же входных данных. Нет недетерминированных переходов. Нет «состояние зависит от времени суток» или «зависит от того, кто запустил».

**Почему важно.** Воспроизводимость — основа отладки. Если баг не воспроизводится, его нельзя починить. Детерминированные переходы означают: при тех же gate results и том же run report — тот же статус. Никаких скрытых состояний.

**Как проверяется.**
- `lifecycle/workitem.py` — `derive_status()` — чистая функция от gate results + run report.
- `shared/contracts.py` — `GateResultV2`, `RunReport` — полные входные данные для derive_status.
- `test_critical_path.py` — gate executor contracts: при одинаковых evidence — одинаковый результат.

---

## AC-14: AI не может самостоятельно расширять свою authority

**Формулировка.** AI-агент работает в рамках autonomy level, определённого `governance/policy_engine.py` (suggest / prepare / execute / require_approval). Агент не вправе повышать свой уровень. Повышение — только через POLICY.yaml, который читает человек.

**Почему важно.** AI с само-расширяющейся authority — это неконтролируемая система. Fail-closed: отсутствие POLICY.yaml = `require_approval` (максимальное ограничение). Агент может предложить изменение policy, но не принять его.

**Как проверяется.**
- `governance/policy_engine.py` — fail-closed: нет POLICY.yaml → `require_approval`.
- `governance/enforcement.py` — единственная точка входа governance в execution path.
- `governance/decision_log.py` — каждая запись содержит `actor`, `data`, `outcome`, `human_overrode`.
- `governance/human_override.py` — override — сигнал для обучения, не ошибка.

---

## AC-15: Human-facing interface не требует знания внутренних идентификатор

**Формулировка.** CLI, отчёты и human-in-the-loop интерфейсы оперируют человекочитаемыми именами (`feature/add-login`, `PRODUCT workflow`), а не внутренними ID (`wid-8f3a`, `gate-0x1f`). Внутренние ID — для логов и machine-readable артефактов.

**Почему важно.** Если человеку нужно знать `wid-8f3a` чтобы понять, что происходит — интерфейс сломан. Человек работает с намерениями (`add login feature`), не с идентификаторами. Внутренние ID — для машин; человекочитаемые имена — для людей.

**Как проверяется.**
- `cli/ai_ops_cli.py` — intent-based CLI: человек описывает намерение, система классифицирует.
- `lifecycle/run_report.py` — отчёт содержит человекочитаемые описания + machine-readable артефакты.
- Дизайн-ревью: PR, добавляющий human-facing вывод с внутренними ID, обязан объяснить почему.

---

## История изменений

| Дата | Изменение |
|------|-----------|
| 2026-08-25 | Sprint 1: 15 правил созданы на основе внешнего архитектурного ревью |
