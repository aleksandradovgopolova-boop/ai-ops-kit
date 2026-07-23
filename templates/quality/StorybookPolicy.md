# StorybookPolicy — UI-evidence вместо субъективного ревью (v3.1.7)

## Зачем

Находка Phase B: reviewer-false-fail сконцентрирован в 4 UI-review-гейтах
(`ux_review`, `design_system_usage`, `accessibility_review`, `visual_regression`) — их вешает разом
трек VISUAL по одному булеву `ui_changed`, и все четыре blocking. Любой `warn`/сомнение/молчание
модели по одному гейту блокирует всю правку (см. `tools/bench_lite.py`, `tools/gate_policy.py`).

Правильный путь снижения false-fail — **не «довериться модели», а заменить часть субъективного
ревью проверяемым UI-evidence.** Storybook + локальные test-artifacts дают факты, по которым часть
UI-гейтов закрывается детерминированно, а ревьюер остаётся только там, где нужен смысл (flow, copy,
семантика доступности), а не механическая проверка.

## Границы (решение владельца)

- **Без внешнего SaaS и без MCP** для enforcement. Источник истины — локальные manifests и
  test-artifacts child-репо. Storybook MCP подключается позже (v3.6) как **интерфейс для агентов**,
  а не как зависимость ядра.
- **AI Ops Kit сам не становится React-приложением.** Это адаптер для child-продуктов с UI.
- **Fail-closed сохраняется.** Нет артефакта → `status=not_run` → гейт НЕ считается закрытым
  (падает в ревью), «нет данных» никогда не выдаётся за «чисто».

## Контракт

- Схема: `schemas/ui-evidence-bundle.schema.json` (`UIEvidenceBundle`).
- Сборка: `tools/storybook_adapter.py --build <child_root> [--changed a.tsx,b.tsx] [--sha SHA]`.
- Валидация: `validation/validate_storybook_evidence.py <bundle.json>` (структура + семантика:
  статус нельзя разойтись с цифрами — нельзя фабриковать `pass`).

### Артефакты child-репо, которые агрегирует адаптер

| Секция bundle | Источник (первый существующий) | Норма |
|---|---|---|
| `storybook` | `storybook-static/index.json` (v7) / `stories.json` (v6); `.storybook/` | detected + build_status + story_count |
| `state_coverage` | story index (имена историй: Default/Loading/Empty/Error/Restricted) | покрытие обязательных состояний |
| `interaction_tests` | `.ai/ui-evidence/interaction.json` или vitest `--reporter=json` | pass/fail/not_run + total/passed |
| `accessibility` | `.ai/ui-evidence/a11y.json` или axe raw (`violations[].impact`) | blocking = critical/serious |
| `visual_regression` | `.ai/ui-evidence/visual.json` | pass/fail/not_run + changed |
| `design_system` | `.ai/ui-evidence/design-system.json` | reused vs new + обоснование новых |

Fallback-каталоги evidence: `.ai/ui-evidence/`, `test-results/`, `.ui-evidence/`.

## Маппинг evidence → UI-гейт → `evidence_mode`

Связка с `gate_policy.GatePolicyDecision.evidence_mode` (deterministic / ai_review / hybrid / human).
Диагностику даёт `storybook_adapter.evidence_for_gate(bundle)` (пока **shadow**, не enforcement):

| Гейт | Детерминированная часть (из bundle) | Остаточное ревью | evidence_mode |
|---|---|---|---|
| `visual_regression` | `visual_regression.status` (скриншот-дифф) | — | **deterministic** |
| `design_system_usage` | `design_system.status` (reused vs new) | обоснование НОВЫХ компонентов | **hybrid** |
| `accessibility_review` | `accessibility.blocking_violations` (axe critical/serious) | семантическая доступность | **hybrid** |
| `ux_review` | `state_coverage.complete` + `interaction_tests.status` | flow / copy / tone | **hybrid** |

`not_run` в детерминированной части → гейт остаётся за ревьюером (fail-closed), не закрывается сам.

## Что НЕ меняется (safety)

Эти гейты остаются blocking и НЕ ослабляются никаким UI-evidence:
`security`, `code_review`, auth/authz, обработка секретов, dependency approval, целостность данных,
разрушительные действия. Для user-facing изменений реальные визуальные регрессии и критические
a11y-нарушения по-прежнему блокируют (см. матрицу `gate_policy.candidate_policy`).

## Статус и маршрут

- **v3.1.7 (этот инкремент):** bundle только **собирается и валидируется** — shadow, enforcement нет.
- **v3.1.8 — Calibrated UI Enforcement:** `GateResult v2` (+`not_applicable`, reviewer `abstain`) +
  миграционный адаптер; часть UI-гейтов закрывается детерминированно по bundle. Промоушен-критерий:
  `false_green==0`, `known_good_block_rate ≤ 0.10` (или −70%), 0 safety-регрессий, user-facing a11y и
  реальные визуальные регрессии по-прежнему блокируют.
- Дальше: v3.6 Storybook MCP (интерфейс агентов), v3.7 Product Bootstrap (авто-установка Storybook/
  MSW/interaction·a11y CI), v3.8 Readiness Qualification (реальный UI-сценарий через Storybook).

## Настройка UI-CI в child-репо (ориентир для v3.7)

```
storybook build -o storybook-static           # -> storybook-static/index.json
vitest run --reporter=json > .ai/ui-evidence/interaction.json
axe ... > .ai/ui-evidence/a11y.json
<visual-tool> ... > .ai/ui-evidence/visual.json
<ds-lint/codemod> ... > .ai/ui-evidence/design-system.json
```
