# Промты запуска волн (qwen)

Стартовые промты для сессий qwen, реализующих план `lanes-plan.md`. Запуск: `cd ~/ai-ops-kit && qwen`, затем вставить нужный промт.

- **Волна 1 = Phase 0** («контроль качества честен») — 4 ленты параллельно.
- **Волна 2 = Phase B** («ядро вырезано») — Lane K серийно + Lane S параллельно. **Не веер.**

Полный контекст задач — `audit-report.md` (findings) и `kernel-extraction.md` (граница ядра, рёбра, шаги).

---

## Волна 1 — Phase 0

```
Ты — инженер в репозитории AI Ops Kit (~/ai-ops-kit). Задача: поднять ВОЛНУ 1 (Phase 0). Только Phase 0 — Phase B это отдельная волна позже, её НЕ трогай.

ШАГ 0 — ПРЕДУСЛОВИЕ (не начинать, пока не выполнено):
- ветка architecture-hardening-sprint влита в main;
- git status --short пусто; main == origin/main (git fetch);
- дерево никем не занято: проверь `git worktree list` и `lsof +D ~/ai-ops-kit`, НЕ grep по имени репо.
Если предусловие не выполнено — остановись и скажи, чего не хватает.

ШАГ 1 — ПЛАН И ДОКИ:
План на ветке docs/audit-2026-08-25, каталог docs/audit-2026-08-25/. Влей ветку в main (только новые docs/), затем прочти:
- docs/audit-2026-08-25/lanes-plan.md   (доска лент, фрагмент plan.yaml, протокол сессий)
- docs/audit-2026-08-25/audit-report.md (обоснование задач, ID findings)

ШАГ 2 — ВЛОЖИТЬ ПЛАН В planning/plan.yaml:
Из lanes-plan.md §2 добавь цель trustworthy-core (в goals:) и ВСЕ WorkItem'ы (Phase 0 и Phase B) в work: со status: todo. Phase B в работу не бери.
Добавь строку-горизонт trustworthy-core в ROADMAP.md.
Сверь множество id в plan.yaml до/после (по списку id, не по диффу), прогони:
  python3 ai_ops_kit/validation/validate_product_model.py .
  ./scripts/check-fast.sh
Оформи отдельным малым PR (plan + roadmap), зелёным сам.

ШАГ 3 — ВОЛНА 1: 4 ЛЕНТЫ, каждая = отдельный git worktree + ветка, границы НЕ пересекаются:
  Lane A (CI):          write_scope .github/ templates/ci/ scripts/ — workflow-least-privilege, kit-runs-own-security-scan, child-update-force-with-lease
  Lane B (валидаторы/доки): write_scope docs/ AGENTS.md config/ ai_ops_kit/validation/ — delete-orphaned-gate-config, arch-counts-under-claim-markers, validator-teeth-fail-closed, invariant-claims-honest
  Lane C (гейты):       write_scope ai_ops_kit/gates/ schemas/ — gate-evidence-schema-synced, invariants-docstring-fix
  Lane D (SoT моделей): write_scope ai_ops_kit/context/ ai_ops_kit/providers/ registry/ — model-context-from-registry, model-pricing-in-registry

ПРАВИЛА (жёстко):
- Каждая лента в СВОЁМ worktree, НИКОГДА не в общем дереве.
- Пиши ТОЛЬКО в свой write_scope. `git add <свои пути>`, НИКОГДА `git add -A`.
- Одна работа = один малый PR: code + tests + newsfragment, ветка зелёная сама.
- Тест-файлы называй уникально под работу.
- Перед пушем: ./scripts/check-fast.sh в своём дереве.
- Каждый оживлённый/новый валидатор — с fail-closed кейсом (впрысни дефект, assert != 0).
- Любую правку plan.yaml — сверять множество id до/после.
- Свой .venv на дерево; никакой разрушительной переустановки в общем окружении.

Готово, когда все 4 ленты сданы малыми зелёными PR и plan.yaml помечает статусы. Останов — отчёт. Phase B отдельно.
```

---

## Волна 2 — Phase B (извлечение ядра)

```
Ты — инженер в репозитории AI Ops Kit (~/ai-ops-kit). Задача: поднять ВОЛНУ 2 (Phase B) — извлечение ядра (trustworthy-core). ЭТО НЕ ВЕЕР: Lane K — СЕРИЙНАЯ эстафета в ОДНОМ worktree (все шаги трогают ai_ops_kit/engine/, параллелить их = коллизии). Lane S идёт параллельно, но на другом объёме. Максимум ДВЕ сессии, не больше.

ШАГ 0 — ПРЕДУСЛОВИЕ (не начинать, пока не выполнено):
- ВСЯ Волна 1 (Phase 0) влита в main; работы Phase 0 в plan.yaml имеют status: done;
- git status --short пусто; main == origin/main;
- дерево никем не занято (git worktree list + lsof +D ~/ai-ops-kit, НЕ grep по имени репо).
Если нет — остановись и скажи, чего не хватает.

ШАГ 1 — ПРОЧТИ ДЕТАЛИ (обязательно, там рёбра и file:line):
- docs/audit-2026-08-25/kernel-extraction.md — граница ядра, 5 взаимных пар = граница ядра, шаги 0–4 с конкретными файлами.
- docs/audit-2026-08-25/lanes-plan.md §2 (Phase B) — WorkItem'ы K0–K7, S1–S3.
Ключ: снятие 5 взаимных пар (context↔engine, delivery↔engine, engine↔gates, engops↔gates, engine↔lifecycle) И ЕСТЬ извлечение ядра. Метрика — packages/layering.yaml baseline.mutual_pairs: 5 → 0.

ШАГ 2 — LANE S (отдельный worktree, write_scope: tests/ packages/ ai_ops_kit/validation/), запусти ПЕРВОЙ или параллельно Lane K:
  S1 characterization-tests-pipeline — характеристические тесты фаз run_pipeline ДО любого расщепления. ОБЯЗАНЫ быть влиты до K6.
  S3 max-func-lines-ratchet — новый ратчет размера функций (чтобы K6 был измерим).
  S2 kernel-boundary-rule — слой kernel в packages/layering.yaml + правило «kernel не импортирует planning/intelligence/engops-satellite»; влить ПОСЛЕ K5 (когда кольцо стало DAG).

ШАГ 3 — LANE K (ОДИН worktree, СЕРИЙНО, порядок строгий; write_scope: ai_ops_kit/kernel/ shared/ engine/ gates/ context/ lifecycle/ delivery/ engops/):
  K0 kernel-ports-and-contracts    — ports.py (Executor/Context/Evidence/Gate/Delivery/Policy) + контракты в shared/. Чистое добавление.
  K1 break-engine-gates-di         — evidence_collector получает tool_broker параметром. После: baseline.mutual_pairs 5→4.
  K2 break-context-engine-contract — context_compiler зовёт run_plan как TypedDict, не импорт. 4→3.
  K3 break-delivery-engine-tx      — delivery только из ai_ops_run + контракт-тест. 3→2.
  K4 move-deploy-readiness-to-gates— deploy_readiness engops→gates, убрать sys.path-хак в gate_executor.py. 2→1.
  K5 break-engine-lifecycle-classify — классификация из workitem в шаг ядра; workitem не импортирует engine. 1→0 — КОЛЬЦО СТАЛО DAG.
  K6 split-god-functions           — run/run_pipeline на фазы (detect/worktree/spec/execute/evidence/gate/commit). ТРЕБУЕТ влитого S1.
  K7 wire-invariants-runtime       — check_invariant в producer'ах (preflight/run_pipeline/DeliveryReceipt), fail-closed на нарушении.

ПОСЛЕ КАЖДОГО СНЯТИЯ ПАРЫ (K1–K5): понизь baseline.mutual_pairs в packages/layering.yaml (ратчет ходит только ВНИЗ; ушедшая пара обязана быть списана) и обнови комментарий. Прогони python3 ai_ops_kit/validation/validate_layering.py . — должно быть 0.

ПРАВИЛА (жёстко):
- Lane K — ОДНА сессия, серийно; НЕ запускай K1–K7 параллельными сессиями (общий engine/).
- Пиши только в свой write_scope; `git add <пути>`, НИКОГДА `git add -A`.
- Один WorkItem = один малый PR: code + tests + newsfragment, зелёный сам; ./scripts/check-fast.sh перед пушем.
- K6 НЕ начинать, пока S1 (характеристические тесты) не влит — иначе рефакторинг вслепую.
- Рефакторинг сохраняет поведение: тесты до и после зелёные без правки самих тестов (кроме новых).
- Правку plan.yaml — сверять множество id до/после.

Готово с Волной 2, когда baseline.mutual_pairs = 0, все K0–K7 и S1–S3 влиты малыми зелёными PR, plan.yaml помечает их done, а validate_layering и check-full зелёные. Останов — отчёт: назови новое число mutual_pairs, cycles_longer_than_two и max-func-lines до/после.
```
