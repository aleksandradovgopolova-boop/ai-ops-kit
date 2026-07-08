# OpenSpec integration (spec-протокол)

Интеграция OpenSpec как **технического ядра spec-протокола** (Вариант B, см.
`audit/ai-ops-target-v2/OPENSPEC_INTEGRATION_DECISION.md`). Подключается **как опция,
включённая по умолчанию** — при необходимости выключается, и текущий task-lifecycle
продолжает работать без неё.

## Что это даёт
- `openspec/specs/` — «как есть сейчас» (источник истины по требованиям);
- `openspec/changes/<name>/` — предлагаемые изменения (дельты);
- дельта-секции `ADDED / MODIFIED / REMOVED / RENAMED Requirements`;
- **детерминированные** `validate / archive / sync` выполняет сам OpenSpec CLI — не ИИ.

## Зависимость (как это работает)
- Инструмент: `@fission-ai/openspec`, диапазон версий **`>=1.5.0 <2.0.0`** (проверено на 1.5.0).
- Тип связи: **CLI + формат файлов**, НЕ импорт библиотеки. Мы вызываем бинарь `openspec`
  и читаем/пишем markdown. Наши слои (workflows, gates, agents) лежат сверху и не зависят
  от внутренностей OpenSpec.
- Требует Node.js (в проекте/CI). Для не-Node репозиториев — через контейнер/вложенный CLI.
- Установка — на этапе `ai-ops init` дочернего репо (Ф8/Ф10), не в parent.

## Опция (включено по умолчанию)
Включено по умолчанию (профиль `core`, схема `spec-driven`); выключается в дочернем
репо флагом `openspec.enabled: false` в `.ai-ops.yaml`. Пока флаг выключен — OpenSpec
не используется, работает прежний lifecycle.

## Детерминированные операции vs LLM
- **OpenSpec CLI (детерминированно):** `validate`, `archive` (влить дельту в specs),
  `sync` (синхронизировать без архивации).
- **LLM (содержание):** пишет proposal/requirements/delta specs/design/tasks.
Применение изменений в источник истины — только CLI (принцип «не поручать LLM критический sync»).

## Наш слой поверх OpenSpec
- `change-template/` — расширенный change-пакет: OpenSpec-часть (proposal/requirements/specs/
  design/tasks) + наши `execution/` (task-lifecycle), `gates/`, `decisions/`, `learning/`, `verification.md`.
- `schemas/` — наши расширения для неинженерных типов (product/research/...).
- **parallel-merge guard** (`02_tools/ci/validate_openspec_change.py`) — закрывает известный
  баг OpenSpec: два un-archived change на одном требовании блокируются (иначе archive
  второго молча теряет детали первого).

## Fallback (если OpenSpec станет несовместим)
Зависим от **формата**, не от реализации: 1) закрепить версию; 2) форкнуть (MIT);
3) наш валидатор уже читает тот же дельта-формат и может проверять его без бинаря openspec.

## Проверено
Пример `examples/openspec-demo/` проходит реальный `openspec validate --all --strict`
(2 passed, 0 failed на 1.5.0). Guard проверяется в CI на этом же примере.
