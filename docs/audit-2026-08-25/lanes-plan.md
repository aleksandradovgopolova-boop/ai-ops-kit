# AI Ops — план работ лентами (Phase 0 + Phase B), готов к применению

**Статус:** черновик к применению · **НЕ применять сейчас** · **База:** v3.37.0.
**Стартуем, когда сольётся текущий спринт** (`architecture-hardening-sprint`) и рабочее дерево станет чистым. Причина: `planning/plan.yaml` прямо сейчас изменён в этой ветке — вложение задач поверх грязного дерева затрёт чужую работу (грабли из памяти проекта: «резать YAML — по маркерам своей сущности», «git add -A унёс чужое»).

---

## 0. Предусловие старта (гейт)

```
[ ] architecture-hardening-sprint влит в main
[ ] git -C ~/ai-ops-kit status --short  →  пусто
[ ] git -C ~/ai-ops-kit fetch && main == origin/main
[ ] дерево никем не занято: lsof +D ~/ai-ops-kit (или проверка worktree), НЕ grep по имени репо
[ ] Phase 0 применяется первым; Phase B — только после того, как все ленты Phase 0 влиты
```

Затем: этот файл вкладывается в `planning/plan.yaml` (секции `goals:` и `work:`), пересчитывается число WorkItem'ов до/после (сверка множества id — не по диффу), прогоняется `./scripts/check-fast.sh` + `validate_product_model.py`.

---

## 1. Что получается — доска лент

**Порядок фаз строгий:** Phase 0 → (всё влито) → Phase B. Phase 0 снимает «ложную уверенность в качестве»; строить ядро поверх непочиненного контроля качества нельзя.

```
PHASE 0 — «контроль качества честен» (≈ неделя, 4 ЛЕНТЫ ПАРАЛЛЕЛЬНО)
────────────────────────────────────────────────────────────────────
 Lane A · CI safety          write_scope: .github/ templates/ci/ scripts/
   A1 workflow-least-privilege     (permissions: contents: read на 2 workflow)
   A2 kit-runs-own-security-scan   (джоба security_scan --base origin/main)
   A3 child-update-force-with-lease(--force-with-lease + узкий токен в шаблоне дочки)

 Lane B · Validators & honest docs  write_scope: docs/ AGENTS.md config/ ai_ops_kit/validation/
   B1 delete-orphaned-gate-config  (снести config/quality-gates.yaml + guard-валидатор)
   B2 arch-counts-under-claim-markers (счётчики модулей/пакетов/валидаторов из факта; чинит AGENTS.md/overview/REFACTORING_MAP)
   B3 validator-teeth-fail-closed  (fail-closed кейс к 4 «пустым» валидаторам)
   B4 invariant-claims-honest-DOC  (доки: «проверено на синтетике», убрать фантомный --selftest)

 Lane C · Gate integrity     write_scope: ai_ops_kit/gates/ schemas/
   C1 gate-evidence-schema-synced  (тест: _EVIDENCE_KEYS ↔ schemas/gate-evidence.schema.json)
   C2 invariants-docstring-fix     (реальный путь импорта в gates/invariants.py)

 Lane D · Model-fact SoT      write_scope: ai_ops_kit/context/ ai_ops_kit/providers/ registry/
   D1 model-context-from-registry  (MODEL_CONTEXT выводится из registry/models.yaml + sync-тест)
   D2 model-pricing-in-registry    (цены per-token в registry/models.yaml, orchestrator_usage читает)

PHASE B — «ядро вырезано» (спринтами, 2 ЛЕНТЫ; хот-путь СЕРИЙНЫЙ)
────────────────────────────────────────────────────────────────────
 Lane K · Kernel surgery (СЕРИЙНАЯ ЭСТАФЕТА — всё трогает engine/)
   K0 kernel-ports-and-contracts    ports.py + контракты (shared/, kernel/)         → базис
   K1 break-engine-gates-di         evidence_collector получает broker параметром
   K2 break-context-engine-contract run_plan как TypedDict, не импорт
   K3 break-delivery-engine-tx      delivery только из ai_ops_run + контракт-тест
   K4 move-deploy-readiness-to-gates deploy_readiness engops→gates (убить sys.path-хак)
   K5 break-engine-lifecycle-classify классификация из workitem в шаг ядра  → кольцо стало DAG
   K6 split-god-functions           run/run_pipeline на фазы (ПОСЛЕ K-supp тестов)
   K7 wire-invariants-runtime       check_invariant в producer'ах (fail-closed)

 Lane S · Kernel support (ПАРАЛЛЕЛЬНО Lane K)
   S1 characterization-tests-pipeline характеристические тесты фаз ДО K6   (tests/)
   S2 kernel-boundary-rule           слой kernel в layering.yaml + правило   (packages/ validation/)
   S3 max-func-lines-ratchet         новый ратчет размера функций           (packages/ validation/)
```

**Зависимости между лентами:**
- Phase 0: A, B, C, D **не зависят друг от друга** (write_scope не пересекаются) → 4 сессии сразу.
- Phase B: `K0 → K1 → K2 → K3 → K4 → K5 → K6 → K7` — серийно (все трогают `engine/`). `S1` обязана опередить `K6`. `S2/S3` идут параллельно K, задевают только `packages/`+`validation/`+`tests/`.

**Почему Phase B не разбить на 8 лент:** `engine/` — общий у K1–K7; параллельные правки одного пакета = те самые коллизии из памяти. Честная параллельность здесь — **одна эстафета K + одна поддержка S**, максимум две сессии.

---

## 2. Фрагмент plan.yaml (вложить в существующий файл)

> Роль, не исполнитель (`owner_role`); статус только `todo`; `write_scope` — границы ленты; `goal` — существующая цель или новая ниже. Заморозка умений НЕ мешает: всё это либо чинит найденный дефект, либо снижает цену процесса (оговорка решения `ep-2026-08-17`), новым умением не является.

```yaml
# --- добавить в goals: ---
  - id: trustworthy-core
    # НОВАЯ ЦЕЛЬ. ПОДТВЕРЖДЕНА владельцем 2026-08-25 (не под capability-freeze: структура/цена
    # процесса). Суть: маленькое ядро (task→verified change) + этапы жизненного цикла как отдельные
    # спутники, чтобы полное меню росло, не обрушивая друг друга.
    # ПРИ ПРИМЕНЕНИИ: добавить строку-горизонт в ROADMAP.md (roadmap.check сверяет направление↔работу).
    status: active

# --- добавить в work: (Phase 0) ---
  - id: workflow-least-privilege
    title: >-
      На package-quality и pr-smoke объявлен минимальный permissions (contents: read)
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [.github/]
    finding: docs/audit-2026-08-25/audit-report.md  # OPS-2
    reason: >-
      PR-триггерные workflow наследуют дефолтный (часто read/write) токен на исполнении чужого кода.
      Готово, когда оба объявляют минимальный permissions и это проверяется.

  - id: kit-runs-own-security-scan
    title: >-
      Кит гоняет собственный security_scan в CI против диффа PR
    type: engineering
    goal: checks-that-run
    status: todo
    owner_role: engineer
    value: high
    write_scope: [.github/]
    finding: docs/audit-2026-08-25/audit-report.md  # SEC-4
    reason: >-
      Кит держит дочки на детерминированном сканере, а свои диффы им не проверяет (только pre-commit,
      обходится commit -n). Готово, когда джоба security_scan --base origin/main — обязательная.

  - id: child-update-force-with-lease
    title: >-
      Автообновление дочки пушит через --force-with-lease и узким токеном
    type: engineering
    goal: team-works-in-parallel
    status: todo
    owner_role: engineer
    value: medium
    write_scope: [templates/ci/]
    finding: docs/audit-2026-08-25/audit-report.md  # OPS-4 (часть SEC-2)
    reason: >-
      Шаблон дочки делает git push -f и берёт широкий токен. Готово, когда push безопасен к чужой
      работе на ветке, а токен сужен до необходимого.

  - id: delete-orphaned-gate-config
    title: >-
      Осиротевший config/quality-gates.yaml удалён; повторное появление краснеет
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [config/, ai_ops_kit/validation/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-5
    reason: >-
      Второй реестр гейтов (14 гейтов, имена расходятся с SoT), никем не читается, нарушает
      «registry=SoT». Готово, когда файл удалён и валидатор запрещает второй реестр гейтов.

  - id: arch-counts-under-claim-markers
    title: >-
      Счётчики модулей/пакетов/валидаторов выводятся из факта, а не написаны рукой
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [docs/, AGENTS.md, ai_ops_kit/validation/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # DOC-1/2/4
    reason: >-
      AGENTS.md/overview.md/REFACTORING_MAP имеют счётчики вне claim-маркеров, они разошлись в 2.4x и
      указывают на устаревшие каталоги. Готово, когда числа под validate_claims или убраны, а карты
      указывают на ai_ops_kit/shared/ (не tools/).

  - id: validator-teeth-fail-closed
    title: >-
      Четыре «оживлённых» валидатора имеют fail-closed кейс (ловят дефект, не только проходят)
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [tests/, ai_ops_kit/validation/]
    finding: docs/audit-2026-08-25/audit-report.md  # TEST-2
    reason: >-
      container_delivery/pipeline_e2e/product_qualification/stack_qualification тестируются только
      main([])==0 — mutant-survivable. Готово, когда каждый имеет кейс с впрыснутым дефектом и
      assert main([])!=0.

  - id: invariant-claims-honest
    title: >-
      Каталог инвариантов честно помечен «проверено на синтетике»; фантомные ссылки убраны
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: medium
    write_scope: [docs/, AGENTS.md]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-1 (док-часть; рантайм — K7)
    reason: >-
      check_invariant/ALL_INVARIANTS не вызываются из рантайма; доки подают это как машинную
      гарантию. Готово (док-часть), когда AGENTS.md/invariants.md говорят «на синтетике», а
      фантомные --selftest/tools/invariants.py убраны. Рантайм-подключение — K7.

  - id: gate-evidence-schema-synced
    title: >-
      Тест сверяет форму evidence в коде с schemas/gate-evidence.schema.json
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/gates/, schemas/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-4
    reason: >-
      gate_executor валидирует руками по _EVIDENCE_KEYS и цитирует схему, которую не читает; они
      разошлись. Готово, когда тест краснеет на расхождении код↔схема.

  - id: invariants-docstring-fix
    title: >-
      Docstring gates/invariants.py указывает реальный путь импорта
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: low
    write_scope: [ai_ops_kit/gates/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-1/F9
    reason: >-
      Docstring показывает from invariants import ... selftest (нет такого) и tools/invariants.py.
      Готово, когда путь верный и фантомного selftest нет.

  - id: model-context-from-registry
    title: >-
      Окна контекста моделей выводятся из registry/models.yaml, не из кода
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/context/, registry/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-2
    reason: >-
      MODEL_CONTEXT захардкожен устаревшими id мимо реестра; правка реестра тихо не влияет на бюджет.
      Готово, когда значения из реестра и sync-тест связывает их.

  - id: model-pricing-in-registry
    title: >-
      Цены per-token живут в registry/models.yaml, orchestrator_usage читает их оттуда
    type: engineering
    goal: green-means-checked
    status: todo
    owner_role: engineer
    value: medium
    write_scope: [ai_ops_kit/providers/, registry/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-3
    reason: >-
      Цены в трёх представлениях (код-словарь, cost_class, проза) без сверки. Готово, когда цена —
      first-class поле реестра со статусом, а код её читает.

# --- добавить в work: (Phase B) — goal: trustworthy-core ---
  - id: kernel-ports-and-contracts
    title: >-
      Объявлены порты ядра (Executor/Context/Evidence/Gate/Delivery/Policy) и контракты
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/shared/, ai_ops_kit/kernel/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 0
    reason: >-
      Нужен один шов ядра. Готово, когда Protocol'ы и контракты объявлены; чистое добавление, ничего
      не переехало.

  - id: break-engine-gates-di
    title: >-
      evidence_collector получает tool_broker параметром (снят цикл engine↔gates)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/gates/, ai_ops_kit/engine/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 1
    reason: >-
      Готово, когда evidence_collector не импортирует engine напрямую и mutual_pairs в layering.yaml
      уменьшилось на 1.

  - id: break-context-engine-contract
    title: >-
      context_compiler использует run_plan как TypedDict-контракт (снят цикл context↔engine)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/context/, ai_ops_kit/engine/, ai_ops_kit/shared/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 1
    reason: >-
      Готово, когда context не импортирует engine.run_plan модулем, а mutual_pairs уменьшилось на 1.

  - id: break-delivery-engine-tx
    title: >-
      delivery вызывается только из ai_ops_run (контракт-тест; снят цикл delivery↔engine)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: medium
    write_scope: [ai_ops_kit/engine/, ai_ops_kit/delivery/, tests/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 1
    reason: >-
      Готово, когда контракт-тест доказывает: execution_pipeline не зовёт delivery напрямую.

  - id: move-deploy-readiness-to-gates
    title: >-
      deploy_readiness переехал в gates; sys.path-хак в gate_executor удалён (снят цикл engops↔gates)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: medium
    write_scope: [ai_ops_kit/gates/, ai_ops_kit/engops/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 1.5
    reason: >-
      Готово, когда deploy_readiness в gates, gate_executor зовёт его импортом (без sys.path), а
      mutual_pairs уменьшилось на 1.

  - id: break-engine-lifecycle-classify
    title: >-
      Классификация вынесена из workitem в шаг ядра (снят корневой цикл engine↔lifecycle)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/engine/, ai_ops_kit/lifecycle/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 2
    reason: >-
      Готово, когда workitem не импортирует engine, derive_status остаётся чистой, а mutual_pairs
      стало 0 — кольцо capabilities стало DAG.

  - id: split-god-functions
    title: >-
      run/run_pipeline расщеплены на тестируемые по фазам функции
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/engine/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 3
    reason: >-
      Готово, когда фазы (detect/worktree/spec/execute/evidence/gate/commit) — отдельные функции с
      юнит-тестами, а max-func-lines ушёл вниз. ТРЕБУЕТ characterization-tests-pipeline раньше себя.

  - id: wire-invariants-runtime
    title: >-
      check_invariant вызывается в реальных producer'ах (fail-closed на нарушении)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [ai_ops_kit/engine/, ai_ops_kit/gates/, ai_ops_kit/lifecycle/, tests/]
    finding: docs/audit-2026-08-25/audit-report.md  # INT-1 рантайм
    reason: >-
      Готово, когда preflight/run_pipeline/DeliveryReceipt проверяются каталогом на выходе и
      нарушение краснеет — гарантия перестаёт быть декоративной.

  - id: characterization-tests-pipeline
    title: >-
      Характеристические тесты фаз pipeline написаны ДО расщепления God-функций
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [tests/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # Lane S / TEST-1
    reason: >-
      Готово, когда поведение run_pipeline зафиксировано тестами по ветвям — иначе split вслепую.

  - id: kernel-boundary-rule
    title: >-
      Слой kernel объявлен в layering.yaml; ядро не импортирует спутники (проверяется)
    type: engineering
    goal: trustworthy-core
    status: todo
    owner_role: engineer
    value: high
    write_scope: [packages/, ai_ops_kit/validation/]
    finding: docs/audit-2026-08-25/kernel-extraction.md  # шаг 4
    reason: >-
      Готово, когда правило «kernel не зависит от planning/intelligence/engops-satellite» краснеет
      на нарушении.
```

---

## 3. Протокол запуска параллельных сессий (из грабель памяти)

Каждая лента = **отдельная сессия в отдельном git-worktree**, НЕ общий checkout.

1. **Своё дерево:** `git worktree add ../ao-lane-A lane/phase0-ci` (и т.д.). Никогда не работать двум сессиям в одном дереве.
2. **Только свой write_scope:** ленте разрешено писать ТОЛЬКО в свои каталоги (см. доску). `git add <свои пути>`, **никогда `git add -A`**.
3. **Проверка коллизий — механизмом кита:** перед стартом `concurrency_preflight` (кит его имеет) сверяет, что write_scope лент не пересекаются.
4. **Малый PR = одна работа:** code + tests + newsfragment в одном PR, ветка сама зелёная (их же правило `lane-ships-small-prs`). Имя тест-файла — уникальное под работу (tests/ общий, но файлы не пересекаются).
5. **Проверять до пуша:** `./scripts/check-fast.sh` в своём дереве (зеркалит блокирующий CI).
6. **Слияние:** родным merge queue, если он к тому времени включён (их работа `merge-queue-not-handrolled`), иначе — по одному, сверяя `origin/main` реально (не по статусу «MERGED»).
7. **Правка plan.yaml:** статус работы двигать только в своей ленте; при любой правке YAML — сверить множество id до/после (память: «резать YAML по маркерам съело чужое»).
8. **Python-окружение:** свой `.venv` на дерево; не запускать разрушительную переустановку в дереве, делящем окружение (память: «npm ci пошёл по симлинку»).

**Порядок сессий:**
- Волна 1 (Phase 0): 4 сессии сразу — Lane A, B, C, D. Ждём слияния ВСЕХ.
- Волна 2 (Phase B): 2 сессии — Lane K (эстафета K0→K7) + Lane S (S1 раньше K6; S2/S3 параллельно).

---

## 4. Что решаешь ты до старта

1. **Цель `trustworthy-core`:** подтвердить горизонт в ROADMAP.md и что она не под capability-freeze (моя оценка — не под, это структура/цена процесса, но слово за тобой).
2. **Амбиция:** «полное меню, растим вглубь» (рекомендация) vs «всё для всех» — влияет на агрессивность отрезания спутников в будущей Lane 6.
3. **Куда положить аудит:** предлагаю вложить два артефакта (`audit-report`, `kernel-extraction`) в `docs/audit-2026-08-25/` — на них ссылаются поля `finding:` каждой работы.

*Ничего в репозитории не изменено. Стартуем по твоему слову, после слияния текущего спринта.*
