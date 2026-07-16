# AI Ops Kit

Открытая **AI Product Operating System** для продуктово-технологических команд:
AI сопровождает продукт на всём жизненном цикле — Discovery → Delivery → Release →
Measurement → Insights → снова Discovery. Агенты (включая независимых ревьюеров всех
зон), workflow-контракты, quality gates, Feature Blueprint, единый продуктовый путь
(WorkItem), генераторы артефактов, Knowledge Graph, Product Health, Decision Intelligence,
постура безопасности, provider/runtime маршрутизация, **единый execution-движок**
(`ai-ops run --engine pipeline`: worktree-изоляция → детектор стека → tool-loop → commit →
evidence на точном SHA → RunPlan-гейты → draft PR) и управляемые обновления дочерних репозиториев.

> **Честный статус движка (аудит исполнения, 2026-07-16):** единый движок «задача → draft PR»
> **собран, подключён к контроллеру (`ai-ops run --engine pipeline`) и экспериментально
> подтверждён живьём на ОГРАНИЧЕННОМ QUICK-сценарии** до `ready_for_pr` (DeepSeek через
> `openai-compatible`; изоляция в worktree, commit на ветке, evidence на точном SHA). Дифф прошёл
> adversarial-review (6 дефектов, включая security, исправлены — v2.63). Trust boundary усилена
> (v2.66): shell-timeout + честная граница «shell не песочница», валидация WorkItem ID и
> containment worktree-путей, полный SHA + проверка чистоты дерева, строгий `ready_for_pr`,
> рабочие `print_human`/exit-code для pipeline.
>
> **Канонический путь для РЕАЛЬНЫХ child-репозиториев ещё не готов** — остаток в `p0_backlog`:
> полный jail shell (контейнер), standalone-движок внутри child (не внешний клон), постадийное
> исполнение треков RunPlan, живой draft PR (нужен GITHUB_TOKEN), квалификация на 3–5 реальных
> задачах против обычного Claude Code. Детали — `manifest → execution_engine.execution_audit_2026_07_16`,
> решение `ep-2026-07-16-execution-audit`.
>
> Границы честности: shell не полностью песочница (FS/сеть-изоляция вне репо = контейнер, в
> p0_backlog); прогон с пустым репо освобождает build/lint/test умным ослаблением (штатно).

**Начать здесь:** [Quickstart](docs/QUICKSTART.md) (первый день + типовые ошибки) ·
[Walkthrough](docs/WALKTHROUGH.md) (сквозной сценарий за 15 минут) ·
[Гайд внедрения по ролям](docs/adoption-guide.md) (CTO / PM / EM / QA / Platform).

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
| `tools/` (Execution Engine) | `ai_ops_run` (route→RunPlan→WorkItem→исполнение→отчёт), `run_plan` (base_workflow + треки), `tool_broker` (Policy решает, модель предлагает), `budget` (потолок вызовов), `orchestrator` (sequential + провайдеры anthropic/openai/openai-compatible) |
| `installer/` | CLI `ai-ops`: init / status / diff / update / validate / doctor / migrate / verify-capabilities |
| `validation/` | Валидаторы (registry, workflows, providers, child-install, drift, guard) |
| `migrations/` | Механизм миграций между версиями |

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

Требования: Python 3.10+ и `pyyaml` для CLI/валидаторов; Node.js — только для OpenSpec-опции.
