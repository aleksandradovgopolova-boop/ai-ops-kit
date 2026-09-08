# AI Ops Kit

**AI Product Operating System** — открытая система для продуктово-технологических команд.

AI сопровождает продукт на всём жизненном цикле: Discovery → Delivery → Release → Measurement → Insights → Discovery.

## С чего начать: четыре уровня

Документация разложена по четырём уровням — по тому, что вы сейчас делаете, а не по тому, как
устроен кит внутри. Найдите свою строку и идите по ссылкам в ней. Чтобы начать, читать
`AGENTS.md` не нужно — он для тех, кто уже внутри кита (уровень **EXTEND**).

| Уровень | Вы сейчас | Начать с |
|---------|-----------|----------|
| **START** | Ставите кит и делаете первый прогон | [QUICKSTART.md](QUICKSTART.md) |
| **USE** | Работаете каждый день: команды владельца, уровни общения | [WALKTHROUGH.md](WALKTHROUGH.md) |
| **EXTEND** | Расширяете кит: свои гейты, валидаторы, реестры | [architecture/registry.md](architecture/registry.md) |
| **ARCHITECT** | Проектируете вглубь: слои, инварианты, направление | [architecture/overview.md](architecture/overview.md) |

---

### START — первый день

Установка и один счастливый путь: от пустого репозитория до первого вердикта. Больше здесь читать
не нужно, чтобы попробовать кит.

- [QUICKSTART.md](QUICKSTART.md) — **точка входа.** Канонический путь целиком:
  `init → doctor → onboard → specify → plan → run --execute`.
- [ONBOARDING.md](ONBOARDING.md) — что кит даёт и зачем, простым языком, без терминов.
- [WALKTHROUGH.md](WALKTHROUGH.md) — сквозной сценарий: от обычной фразы до вердикта.
- [guides/installation.md](guides/installation.md) — установка подробно, требования и варианты.

### USE — каждый день

Ежедневная работа владельца: какие команды звать, как читать ответы, как устроены каналы и
параллельные сессии.

- **Команды владельца.** Отдельного справочника команд нет намеренно: каждый интент
  самоописывается (`./ai-ops <команда>`), а разбор потока — в [WALKTHROUGH.md](WALKTHROUGH.md).
  Владельческие команды: `status` (что идёт сейчас), `next` (что взять следующим и почему),
  `explain` (что с моей задачей прямо сейчас), `inbox` (что ждёт моего решения одной очередью),
  `run` / `plan` / `specify` (спецификация → план → исполнение).
- **Уровни общения.** Как кит разговаривает с человеком (product / technical / debug) — задаётся
  в `.ai-ops.yaml` и в `registry/communication-policy.yaml`; краткая памятка — в `CLAUDE.md`
  репозитория.
- [adoption-guide.md](adoption-guide.md) — гайд внедрения по ролям.
- [platform-model.md](platform-model.md) — модель платформы на одном экране.
- [release-channels.md](release-channels.md) — каналы релиза и как зарабатывается `stable`.
- [parallel-work.md](parallel-work.md) — параллельная работа над одним репозиторием без «беговой дорожки».
- [parallel-sessions.md](parallel-sessions.md) — несколько сессий в одном репозитории.
- [qualification-runbook.md](qualification-runbook.md) — runbook живой квалификации на дочках.
- [guides/child-repo.md](guides/child-repo.md) — как кит живёт в дочернем репозитории.
- [guides/ci.md](guides/ci.md) — настройка CI.

### EXTEND — расширяете кит

Когда вы добавляете к киту своё: новый гейт, валидатор, скилл, запись в реестр. Реестр — источник
истины; writer ≠ judge; capability-декларации честные.

- [architecture/registry.md](architecture/registry.md) — реестр как источник истины.
- [architecture/quality-gates.md](architecture/quality-gates.md) — как устроены гейты и их контракты.
- [agent-guides/engineering-cycle.md](agent-guides/engineering-cycle.md) — инженерный цикл для контрибьютора.
- [agent-guides/pre-commit-checklist.md](agent-guides/pre-commit-checklist.md) — обязательные проверки перед коммитом.
- [container-isolation.md](container-isolation.md) — изоляция рантайма движка.
- [downstream-secret-scanning.md](downstream-secret-scanning.md) — secret-scanning в дочках без блокировки обновлений.
- [dogfooding-metrics.md](dogfooding-metrics.md) — как метрики обкатки закрываются сами.
- Полные инструкции для агентов, работающих над самим китом, — в
  [AGENTS.md](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/AGENTS.md)
  (карта репозитория, инварианты, релизный процесс).

### ARCHITECT — проектируете вглубь

Глубокий дизайн: как разложены слои, какие инварианты держат систему, куда движется продукт.

- [architecture/overview.md](architecture/overview.md) — обзор архитектуры.
- [architecture/execution-engine.md](architecture/execution-engine.md) — движок исполнения.
- [architecture/ARCHITECTURE_CONSTITUTION.md](architecture/ARCHITECTURE_CONSTITUTION.md) — архитектурная конституция.
- [architecture/DEPENDENCY_DAG.md](architecture/DEPENDENCY_DAG.md) — граф зависимостей слоёв.
- [architecture/REFACTORING_MAP.md](architecture/REFACTORING_MAP.md) — карта рефакторинга монолитов.
- [api/invariants.md](api/invariants.md) — инварианты, машинно проверяемые.
- [engineering-standard-requirements.md](engineering-standard-requirements.md) — инженерный стандарт как продукт кита.
- [PRODUCT-REQUIREMENTS.md](PRODUCT-REQUIREMENTS.md) — продуктовые требования владельца к развитию.
- Направление и горизонты —
  [VISION.md](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/VISION.md) и
  [ROADMAP.md](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/ROADMAP.md)
  (в корне репозитория).

### Справочник и записи о прошлом

Не входит в четыре уровня: API-справочник (техническая опора) и записи о прошлом — журнал версий,
change-brief'ы, отчёты аудита, ретроспективы. Записи о прошлом описывают день, когда изменение
задумывалось, и намеренно не переписываются под сегодняшнее дерево.

- **API-справочник:** [api/contracts.md](api/contracts.md) · [api/public-surface.md](api/public-surface.md) · [api/kit-observability.md](api/kit-observability.md)
- **Журнал версий:** [changelog/roadmap-history.md](changelog/roadmap-history.md) · [changelog/v3.0-v3.19.md](changelog/v3.0-v3.19.md) · [changelog/v2.md](changelog/v2.md) · [changelog/v0-v1.md](changelog/v0-v1.md)
- **Change-brief'ы:** [change-briefs/README.md](change-briefs/README.md)
- **Аудиты и ретро:** [audit-report.md](audit-report.md) · [audit-2026-08-25/README.md](audit-2026-08-25/README.md) · [parallel-execution-retro.md](parallel-execution-retro.md) · [3.0-design.md](3.0-design.md)

---

## Ключевые возможности

- **Execution Engine** — единый движок «задача → draft PR» с preflight-проверками, tool-loop, evidence collection и quality gates
- **Spec-First** — модель не запускается, пока спецификация не достаточна
- **Quality Gates** — 35 <!-- claim:gates-total --> гейта с machine-readable контрактами
- **Provider-Agnostic** — работает с Anthropic, OpenAI, DeepSeek, Claude CLI, локальными моделями
- **Fail-Closed** — сбой блокирует, а не даёт ложный green
- **Usage Truth** — честный учёт стоимости: unavailable ≠ 0

## Быстрый старт

```bash
# Установка в репозиторий
python3 <path-to-ai-ops-kit>/installer/ai_ops.py init .

# Задача
./ai-ops run "описание задачи" --execute

# Ревью
./ai-ops review
```

## Версия

Текущая: **v4.0.0 qualification** — канал `qualification`, а не `stable`: `stable` требует полевых
доказательств на живых дочках для этой версии и проверяется машиной
(`registry/release-claims.yaml`).
