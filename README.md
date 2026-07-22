# AI Ops Kit

Открытая **AI Product Operating System** для продуктово-технологических команд:
AI сопровождает продукт на всём жизненном цикле — Discovery → Delivery → Release →
Measurement → Insights → снова Discovery. Агенты (включая независимых ревьюеров всех
зон), workflow-контракты, quality gates, Feature Blueprint, единый продуктовый путь
(WorkItem), генераторы артефактов, Knowledge Graph, Product Health, Decision Intelligence,
постура безопасности, provider/runtime маршрутизация, **единый execution-движок**
(`ai-ops run --engine pipeline`: worktree-изоляция → детектор стека → tool-loop → commit →
evidence на точном SHA → RunPlan-гейты → draft PR) и управляемые обновления дочерних репозиториев.

> **Честный статус движка (v3.0.x stable):** единый движок «задача → draft PR» **квалифицирован
> вживую** на claude-sonnet-5 — доказаны настоящий single-run ENGINEERING → draft PR и 3-пакетный
> sequential → `aggregate_ready` → draft PR (reviewer-block hard-stop, trusted retry recovery,
> contained provider-сбои). Механика по-прежнему **проверяется ДЕТЕРМИНИРОВАННО в CI** (91+ проверок,
> PQ1–PQ9). Идёт dogfood на реальных репозиториях; находки выходят патчами `3.0.x`. Точная текущая
> версия — в `VERSION`/CHANGELOG. Ключевые свойства (без живой модели):
> - **Preflight Truth (v2.115):** проверки идут ДО запуска модели (classification → ContextPayload →
>   spec достаточна → атомарна/декомпозиция подтверждена → context budget → human approvals). Неполная
>   спека → **модель не запускается, правок/коммита нет** (Spec-First блокирует реализацию, а не только
>   доставку). Human-approval — настоящий `ApprovalRecord` (автор/scope/revision/причина), а не boolean;
>   доменные условия security исполняются.
> - **Positive-green доказан:** корректная QUICK и ENGINEERING (author+review+security) реально
>   достигают `ready_for_pr=true` (PQ7/PQ8). Нет ложного green: dry-run/недостаток evidence → честный
>   not-ready с названным блокером.
> - **Real Resume (v2.109):** продолжение поверх коммита (не рестарт). **Real Intent UX (v2.112/2.116):**
>   `onboard/status/health/plan/new/discuss/specify/review` — настоящие действия. **Sequential
>   WorkPackage Executor (v2.117):** крупная задача исполняется по пакетам (пакет→commit→evidence→
>   gates→handoff→следующий).
> - **Изоляция (v2.90/2.113):** контейнерный jail (read-only root, worktree-only, cap-drop); доставка
>   забирает ТОЛЬКО ветку текущего прогона.
>
> **v3.0 stable квалифицирован (2026-07-21):** обе строгие цепочки (single ENGINEERING и sequential)
> доведены живьём до настоящего draft PR; негативные пути закрыты детерминированными тестами. Дальше —
> dogfood на 2–3 реальных репо (Python → TS/Node → sequential). См. `docs/qualification-runbook.md`.
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
