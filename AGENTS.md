# AGENTS.md — инструкция для AI-агентов, работающих с этим репозиторием

Это **AI Ops Kit** — переиспользуемый пакет (parent) AI-first операционной системы для
команд: агенты, workflow-контракты, quality gates, маршрутизация, управляемые обновления
child-репозиториев. Здесь разрабатывается сам пакет; в продуктовые репозитории он
устанавливается через `installer/ai_ops.py init`.

## Карта репозитория

| Зона | Что это | Менять можно? |
|---|---|---|
| `registry/` | Машиночитаемые реестры: агенты, workflow-контракты, провайдеры, модели, среды, capability-index, routing-policy | Да, но только синхронно с файлами, на которые они ссылаются |
| `agents/` | 51 агент (markdown) | Да; новый/изменённый агент требует записи в `registry/agents.yaml` и eval-кейсов в `evaluations/agents/` |
| `quality/gates.yaml` | Реестр quality gates | Да, blocking-гейтов MVP ≤ 8 |
| `workflows/`, `commands/`, `rules/`, `templates/`, `context/`, `memory/` | Прозаический слой | Да |
| `schemas/` | JSON Schema контрактов | Осторожно: это публичные контракты, breaking — только major |
| `validation/`, `tools/` | Валидаторы и инструменты (Python, только pyyaml) | Да, каждому инструменту — selftest |
| `installer/ai_ops.py` | CLI `ai-ops` для child-репозиториев | Да |
| `manifest/ai-ops-manifest.yaml` | Центральный манифест пакета | `package_version` — только при релизе |
| `packages/` | Декларации границ 5 пакетов 3.0 (файл→пакет, зависимости) — БЕЗ переноса файлов (3.0-срез 0) | Синхронно с `validate_package_boundaries.py` |
| `qualification/` | Пакет живых сценариев для квалификации движка (данные) | Синхронно с `validate_qualification.py` |
| `containers/` | Эталонный контейнер изоляции движка (P0.2 jail): Dockerfile + run-sandboxed.sh | Синхронно с `validate_container_assets.py` |
| `VERSION`, `CHANGELOG.md` | Версия и история (SemVer) | Только при релизе |

Полный аннотированный список файлов — в `FILE_INDEX.md`.

## Ключевые инварианты

Валидаторы их проверяют, но знать заранее дешевле:

- **Registry — источник истины.** Файл агента без записи в `registry/agents.yaml` (и наоборот) — ошибка.
- **Capability-декларации честные.** В `registry/runtimes.yaml` и `capability-index.yaml`
  нельзя объявлять возможности, не реализованные в коде; для планов — `status: unsupported` + note "planned".
- **Writer ≠ judge.** В workflow-контрактах стадия с `review_mode: read-only` не может быть writer'ом.
- **Стадии ссылаются только на существующие agent id и gate id.**
- **Никаких новых зависимостей** без явного решения: Python-инструменты работают на stdlib + pyyaml.
- **Язык документации — русский**, идентификаторы и ключи — английские.
- **Три кольца** (owner-review 2026-07-30, см. `qualification/bootstrap/v3.8.0-plan.yaml` → `architecture_rings`).
  Kernel (Task→Context→Execution→Evidence→Decision→Delivery) НЕ зависит от Intelligence (research/
  product-learning/аналитика); Intelligence зависит от Kernel и ЧИТАЕТ его события. Governance подключается
  ПО РИСКУ, не на каждой задаче. Изменение продукта не должно требовать заполнения исследовательской онтологии.
- **Runtime через адаптер, не замена.** AI Ops управляет исполнителем (Claude Code/Codex/OpenHands SDK/…)
  через адаптер; workflow/approvals/evidence не переписываются при смене runtime. Свой tool-loop не наращиваем,
  если внешний runtime делает это надёжно.
- **Capability_freeze (3.8): СНЯТ — 3.8 stable достигнут.** В 3.9 аддитивно добавлены first-class Claude Code
  executing adapter + complexity-aware routing (доказаны live). Новые концепт-возможности — ПО ДАННЫМ реальных
  прогонов (3.10 Real-Product Qualification), а не по красоте; точечно и аддитивно.

## Перед коммитом — обязательно

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS. Полный список команд — в
[docs/agent-guides/pre-commit-checklist.md](docs/agent-guides/pre-commit-checklist.md).

Кратко: все `validation/*.py` и `tools/*.py` с флагом `--selftest`, плюс
`python3 -m pytest tests/contracts/ -v --tb=short`.

## Инженерный цикл

Полная версия — в [docs/agent-guides/engineering-cycle.md](docs/agent-guides/engineering-cycle.md).

Кратко:
1. **Change Brief ДО кода** — шаблон в `templates/quality/ChangeBrief.md`.
2. **Три теста на capability** — positive, fail-closed, side-effect proof.
3. **Один свежий review до merge** — AI-сессия без авторского контекста, ≤5 находок.
4. **Не гонять полный цикл после каждой правки** — целевой selftest → core smoke → полный CI один раз.
5. **Рефакторинг — правило третьего изменения.**

## Релизный процесс

1. Обновить `VERSION`, `manifest/ai-ops-manifest.yaml -> ai_ops.package_version`
   и добавить раздел `## [X.Y.Z] — дата` в `CHANGELOG.md`.
2. Коммит `release: AI Ops Kit vX.Y.Z` в `main`.
3. Тег `vX.Y.Z` и GitHub Release создаёт автоматически `.github/workflows/release.yml`
   (по изменению VERSION в main; текст — раздел CHANGELOG). Руками теги не создавать.
