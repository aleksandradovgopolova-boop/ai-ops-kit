# AI Ops Kit

Открытая **AI Product Operating System** для продуктово-технологических команд:
AI сопровождает продукт на всём жизненном цикле — Discovery → Delivery → Release →
Measurement → Insights → снова Discovery. Агенты (включая независимых ревьюеров всех
зон), workflow-контракты, quality gates, Feature Blueprint, единый продуктовый путь
(WorkItem), генераторы артефактов, Knowledge Graph, Product Health, Decision Intelligence,
постура безопасности, provider/runtime маршрутизация, **единый execution-движок**
(`ai-ops run --engine pipeline`: worktree-изоляция → детектор стека → tool-loop → commit →
evidence на точном SHA → RunPlan-гейты → draft PR) и управляемые обновления дочерних репозиториев.

> **Честный статус (v3.20.0 stable; Engineering Operating Model срезы 1–2 — дисциплина коммита (зоны кит/продукт, секреты, protected_paths без approval) и ветки (доставка только через PR, ОТСТАВАНИЕ БАЗЫ); карта окружений (объявлено vs обнаружено, секреты только именами) и ЧЕСТНАЯ зрелость поставки absent/configured/runnable/verified с блокирующим гейтом `deploy_readiness` по сигналу изменения деплоя — кит не деплоит, а не даёт врать о готовности (`ai-ops engops`); Development Culture & Resource Guardrails ЗАВЕРШЁН — гигиена сессий/контекста: телеметрия, пороги бюджета, Task Completion Ritual + рекомендация continue/compact/clear/new (`ai-ops session`), boundary classifier, культура делегирования, cost-aware work method по приоритетам (`ai-ops method`); Architecture Baseline — v3.15.0; Startup Context Budget ЗАВЕРШЁН v3.12–3.14; UI Evidence Readiness — v3.11.0; Usage Truth — v3.10.0; First-class Claude Code Adapter + complexity-aware routing — v3.9.0):** единый движок
> «задача → draft PR» доказан вживую end-to-end на РЕАЛЬНОМ full-stack (ИИ-Среда, React/TS): сильный
> writer (локальный `claude -p`, без API-ключа) + независимый дешёвый ревьюер (deepseek, writer≠judge)
> + детерминированные проверки по стеку (build/typecheck/test) + baseline-diff + **ЧЕЛОВЕК на strict
> security #5** → reevaluate-only → `ready_for_pr` → draft PR + DeliveryReceipt. **14/14 exit_criteria
> доказаны live, 0 false-green.** Механика проверяется ДЕТЕРМИНИРОВАННО в CI (**179 проверок**). Точная
> версия — в `VERSION`/CHANGELOG. Ключевые свойства:
> - **Portfolio по РОЛЯМ (доказано):** дешёвые модели (deepseek→kimi→qwen, полная эскалация) сложный
>   full-stack green НЕ тянут; сильный writer (`claude -p`) тянет. **Sonnet НЕ требуется.** money-mode
>   роутер берёт cheapest-qualified, writer эскалируется на качественном провале, judge≠writer по модели.
> - **First-class Claude Code Adapter (v3.9.0):** кит сам оркестрирует локальный `claude -p` (read-only,
>   без ключа) как СИЛЬНОГО writer'а — Claude только ПРЕДЛАГАЕТ, кит владеет worktree/diff/evidence/gates/
>   delivery (Claude не пушит/не создаёт PR/не меняет checkout/не закрывает свой review|security). +
>   **complexity-aware routing:** сложный класс задачи → сильный writer СРАЗУ (не cheap-then-fix-loop);
>   QUICK → дешёвый API; review → deepseek; strict security → человек. AI Ops = control plane.
> - **Preflight Truth (v2.115):** проверки идут ДО запуска модели (classification → ContextPayload →
>   spec достаточна → атомарна/декомпозиция подтверждена → context budget → human approvals). Неполная
>   спека → **модель не запускается, правок/коммита нет** (Spec-First блокирует реализацию, а не только
>   доставку). Human-approval — настоящий `ApprovalRecord` (автор/scope/revision/причина), а не boolean;
>   доменные условия security исполняются.
> - **Positive-green доказан:** корректная QUICK и ENGINEERING (author+review+security) реально
>   достигают `ready_for_pr=true`. Нет ложного green: dry-run/недостаток evidence → честный
>   not-ready с названным блокером.
> - **Real Resume (v2.109):** продолжение поверх коммита (не рестарт). **Real Intent UX (v2.112/2.116):**
>   `onboard/status/health/plan/new/discuss/specify/review` — настоящие действия. **Sequential
>   WorkPackage Executor (v2.117):** крупная задача исполняется по пакетам (пакет→commit→evidence→
>   gates→handoff→следующий).
> - **Изоляция (v2.90/2.113):** контейнерный jail (read-only root, worktree-only, cap-drop); доставка
>   забирает ТОЛЬКО ветку текущего прогона.
>
> **v3.8.0 stable — фаза v3.8 (Product Bootstrap & Readiness Qualification) завершена (2026-07-31):**
> продуктовый контур ПРОИЗВЕДЁН и доказан live от намерения до доставки на greenfield + реальном
> brownfield (ИИ-Среда). Concurrent parallel-2 + governed fan-in (`tools/parallel_live.py`) доказаны
> live (no_checkout_damage); resume и fix-loop на реальной задаче доказаны; stack-aware integration
> (build/typecheck/vitest, не только pytest). ЦЕЛЕВЫЕ границы портфеля (не дефекты): человек на strict
> security #5; сильный writer на сложном full-stack. Дешёвый auto-close security-судья недостижим
> (prompt v2/v3 + fail-closed каскад) → future_opportunities; human #5 остаётся. См. CHANGELOG [3.8.0].
>
> Границы честности: shell не полностью песочница (полная FS/сеть-изоляция = контейнер,
> `docs/container-isolation.md`); прогон с пустым репо освобождает build/lint/test умным ослаблением.

**Начать здесь:** [Quickstart](docs/QUICKSTART.md) (первый день + типовые ошибки) ·
[Walkthrough](docs/WALKTHROUGH.md) (сквозной сценарий за 15 минут) ·
[Гайд внедрения по ролям](docs/adoption-guide.md) (CTO / PM / EM / QA / Platform) ·
[Downstream secret-scanning](docs/downstream-secret-scanning.md) (если сканер репо ложно блокирует обновление кита).

Куда идём — в [`VISION.md`](VISION.md) и [`ROADMAP.md`](ROADMAP.md).
Версия пакета — в [`VERSION`](VERSION), история — в [`CHANGELOG.md`](CHANGELOG.md).

## Что внутри

| Папка | Содержимое |
|---|---|
| `agents/` | 51 агент (core / product / engineering / quality / delivery / meta), включая команду AI-продукта |
| `registry/` | Машиночитаемые реестры: агенты, workflow, провайдеры, модели, среды, маршрутизация |
| `quality/` | Реестр quality gates (machine-readable контракт с revision-binding) |
| `workflows/`, `commands/`, `rules/`, `templates/` | Прозаические сценарии, команды, правила, шаблоны |
| `schemas/` | JSON Schema контракты (gate-result, route-decision, child-config, ...) |
| `security/` | 6 уровней разрешений, boundary model (managed/project/custom) |
| `openspec/` | Интеграция OpenSpec (опция): change-template, extension-схемы |
| `skills/` | Скиллы, поставляемые китом (opt-in), + каталог внешних скиллов (registry/skills-catalog.yaml) |
| `decisions/`, `knowledge/`, `governance/` | Decision Intelligence, Knowledge Integrity (claims/freshness), границы данных и постура безопасности |
| `runtime/` | Спека постоянного агента-ассистента (Robin), runtime-агностичная: контракт + duties + валидатор |
| `tools/` (Execution Engine) | `ai_ops_cli` (intent-UX), `ai_ops_run` (route→RunPlan→WorkItem→**preflight**→исполнение→отчёт), `preflight` (проверки до модели) + `approvals` (ApprovalRecord), `run_plan`, `context_compiler` (ContextBundle→payload в prompt), `spec_levels` (Spec-First), `atomic_planner` + `workpackage_executor` (декомпозиция→последовательное исполнение), `run_handoff` (resume), `review_branch` (read-only ревью ветки), `tool_broker`/`budget`/`orchestrator` |
| `installer/` | CLI `ai-ops`: init / status / diff / update / validate / doctor / migrate / verify-capabilities |
| `validation/` | Валидаторы (registry, workflows, providers, child-install, drift, guard) |
| `migrations/` | Механизм миграций между версиями |

## Команды (intent-based UX)

Снаружи движок управляется **намерениями**, а не флагами — система сама подбирает workflow, стадии и
нужные флаги (`--engine`/`--author`/`--review`/`--sandbox`/`--baseline-diff`) и показывает preview
до запуска:

```bash
python3 .ai/managed/tools/ai_ops_cli.py <intent> "<задача>" . [--feature NAME] [--execute]
```

| Intent | Что делает (реальное действие) |
|---|---|
| `onboard` | детектит стек, пишет `.ai/repository-profile.yaml` |
| `new` | каркас фичи: WorkItem + spec-заготовка |
| `discuss` | черновик discovery (`features/<id>/discovery-draft.md`) |
| `specify` | создаёт/валидирует реальную спецификацию нужной глубины (`features/<id>/spec.yaml`) |
| `plan` | пишет RunPlan + ContextBundle + SpecCoverage + WorkPackages (без правок кода) |
| `run --execute` | исполняет задачу движком (preflight → tool-loop → commit → evidence → гейты → draft PR); `--sequential` — крупную задачу по WorkPackages |
| `resume --execute [--force]` | продолжает прерванную работу поверх коммита (не рестарт) |
| `review [--provider … --model …]` | независимый read-only ревью действующей ветки (writer ≠ judge, без правок) |
| `status` / `health` | активная работа / Product Health Score |
| `preview <intent> …` | показать план действия без выполнения |

Низкоуровневый вход (`ai_ops_run.py run … --engine pipeline`) остаётся доступен — см. Quickstart §3b.

## Установка в репозиторий (child)

Из корня вашего репозитория:

```bash
python3 <путь-к-ai-ops-kit>/installer/ai_ops.py init .
# отредактируйте .ai-ops.yaml (project.name, providers)
python3 <путь-к-ai-ops-kit>/installer/ai_ops.py doctor
```

Создаётся `.ai/` (managed/project/custom/generated/runtime) + `.ai-ops.yaml`.
Управляемый слой защищён контрольными суммами: ручная правка обнаруживается,
обновление никогда не перезаписывает локальное молча.

## Обновление child

```bash
python3 <путь-к-ai-ops-kit>/installer/ai_ops.py status   # что установлено vs доступно
python3 <путь-к-ai-ops-kit>/installer/ai_ops.py diff     # что изменится
python3 <путь-к-ai-ops-kit>/installer/ai_ops.py update   # применить (отчёт + PR, не silent)
```

## Принципы

- Provider ≠ Model ≠ Runtime ≠ Tool protocol — независимые слои, adapters.
- Workflow не зависит от конкретной модели/среды; минимум — sequential mode.
- Writer и judge разделены; проверяющий read-only к проверяемому артефакту.
- Секреты в репозитории запрещены — только ссылки вида `env:NAME`.
- Обновления parent→child — только через проверяемый diff и PR.
- OpenSpec — опция (включена по умолчанию, opt-out), детерминированные validate/archive/sync.
- GigaChat — планируемый провайдер (включается конфигом, без переписывания).

Требования: Python **3.9+** (дефолтный python3 macOS подходит) и `pyyaml` для CLI/валидаторов;
Node.js — только для OpenSpec-опции. Совместимость с 3.9 проверяется в CI
(`validation/validate_python_compat.py`: union-аннотации `X | Y` допускаются лишь под
`from __future__ import annotations`). **Кросс-платформенность**: Windows/Linux/macOS —
пути в реестрах/`.checksums.json` нормализованы к POSIX (`/`), вывод CLI форсирует UTF-8.
