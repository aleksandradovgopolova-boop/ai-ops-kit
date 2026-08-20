# Лента 5 — AI Product Operations (Фаза 4). + капстоун Фазы 5 позже.

Прочитай `../OS-LANES.md` и `docs/PRODUCT-REQUIREMENTS.md` (PR-12..PR-22, и PR-23 автономный цикл).
Ветка `lane-5-work`. У цели `ai-product-operations` есть ИСХОДЫ, но НЕТ работ — сначала декомпозируй.

## Первый ход — ДЕКОМПОЗИЦИЯ фазы в план

Заведи в `planning/plan.yaml` (goal `ai-product-operations`) работы под исходы:
- `drift_detected_between_artifacts` (PR-22) — расхождения: документация↔код, roadmap↔backlog,
  backlog↔delivery, Passport↔факт. Тот же принцип, что уже есть в ките (`repo_graph`,
  `detect_drift`) — переиспользуй, не дублируй.
- `risks_identified_with_mitigation` (PR-16) — риски (product/delivery/tech/dependency/resource/
  strategic) + предложение действия.
- `team_status_auto_generated` (PR-12) — авто-статус: прогресс milestone, изменения, блокеры,
  риски, ближайшие задачи, delivery forecast. Команда не собирает вручную.
- `ai_decisions_logged_with_rationale` (PR-18) — AI Decision Log: что решено, почему, на каких
  данных, результат, менял ли человек. В ките УЖЕ есть `decisions/registry.yaml` — расширь его на
  решения AI, а не заводи второй.
- Плюс health (PR-13/14/15): product/tech/delivery **Green/Yellow/Red С ОБЪЯСНЕНИЕМ** причин;
  policy engine (PR-19: Suggest→Prepare→Execute→Require approval); human override (PR-20: override —
  сигнал на будущее, не ошибка).

## Территория
`ai_ops_kit/intelligence/health_*`, `intelligence/drift_*`, `intelligence/risk_*`,
`intelligence/team_sync*`, `ai_ops_kit/governance/` (policy). Decision log — расширение
`decisions/registry.yaml` через `ai_ops_kit/` (согласуй, файл общий).

## Границы
- Health — ВСЕГДА с объяснением (Green/Yellow/Red + почему). Цвет без причины бесполезен.
- Drift переиспуй существующее (`repo_graph`, `architecture_baseline`, `detect_drift`) — dp-001:
  дубли уже построенного отклоняем.
- Policy/override — это про исполняемое поведение (Suggest→…→Require approval); правило без
  исполнения — пожелание.

## Первый ход по коду
Product Health (PR-13) из `ai_ops_kit/intelligence/health_product.py`: Green/Yellow/Red с
названными причинами, читает состояние репо/CI/тестов. Health считается сразу, без зависимости от
других лент. Тесты на фикстурах.

## Фаза 5 (автономный цикл) — потом
Observe→Understand→Plan→Prioritize→Execute→Evaluate→Learn→Replanning (PR-23) собирается, когда
health/risk/drift/decision-log готовы. Пока — только декомпозируй в план как заблокированные работы.
