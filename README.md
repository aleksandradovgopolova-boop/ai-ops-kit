# AI Ops Kit

Открытая **AI Product Operating System** для продуктово-технологических команд:
AI сопровождает продукт на всём жизненном цикле — Discovery → Delivery → Release →
Measurement → Insights → снова Discovery. Агенты (включая независимых ревьюеров всех
зон), workflow-контракты, quality gates, Feature Blueprint, единый продуктовый путь
(WorkItem), генераторы артефактов, Knowledge Graph, Product Health, Decision Intelligence,
постура безопасности, provider/runtime маршрутизация и управляемые обновления
дочерних репозиториев.

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
