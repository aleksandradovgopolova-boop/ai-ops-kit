# AI Ops — Продуктовые требования к дальнейшему развитию

> Сформулированы владельцем 20.08.2026.
> Добавлены в `planning/plan.yaml` как цели `product-operating-layer` .. `autonomous-product-loop`.
> Это требования к AI Ops как к **операционной системе управления продуктовой разработкой**, а не к набору инструментов.

---

## PR-1. Цель

AI Ops должен превращать Git-репозиторий в стандартизированную AI-managed product workspace.

Система должна самостоятельно организовывать продуктовую работу: понимать состояние продукта, поддерживать обязательные артефакты, управлять backlog, формировать и актуализировать roadmap, контролировать delivery, выявлять риски и синхронизировать участников команды.

Человек задаёт стратегию, цели и ограничения. AI Ops управляет операционной частью продуктовой работы.

---

## PR-2. Основной принцип

AI Ops строится вокруг цикла:

**Strategy → Roadmap → Backlog → Prioritization → Delivery → Release → Feedback → Replanning**

AI Ops должен поддерживать этот цикл непрерывно и обеспечивать согласованность всех его элементов.

---

## PR-3. Product Operating Layer

Каждый подключённый репозиторий должен иметь стандартный Product Operating Layer.

Минимальный обязательный набор:

```text
.ai-ops/
├── PRODUCT_PASSPORT.md
├── ROADMAP.md
├── DELIVERY.md
├── POLICY.yaml
└── templates/
```

AI Ops должен:
- определять наличие обязательных артефактов;
- создавать отсутствующие артефакты;
- проверять структуру;
- проверять актуальность;
- валидировать содержимое;
- отслеживать изменения;
- обновлять артефакты;
- мигрировать их при изменении версии шаблона.

---

## PR-4. Artifact Registry

AI Ops должен иметь реестр стандартных артефактов.

Для каждого артефакта должны определяться:
- ID, название, назначение, обязательность;
- путь в репозитории, версия шаблона;
- структура, обязательные поля, допустимые значения;
- правила валидации, правила обновления;
- источник данных, владелец;
- AI actions.

---

## PR-5. Templates

Для каждого стандартного артефакта должен существовать официальный шаблон.

Требования: единая структура, обязательные разделы и поля, версия шаблона с возможностью обновления, обратная совместимость либо миграция, машинная валидация.

AI Ops должен уметь определить: **Missing → Invalid → Outdated → Valid** и самостоятельно исправлять состояние, если это разрешено политикой.

---

## PR-6. Product Passport

AI Ops должен автоматически создавать и поддерживать Product Passport.

Passport должен содержать: название, описание, аудиторию, Problem / JTBD, repository, production / demo, owner, team, статус, зрелость, здоровье продукта/технологий/разработки, версию, последний релиз, ключевые метрики, текущий milestone, прогресс, следующий milestone, риски, зависимости.

---

## PR-7. Roadmap Management

Roadmap описывает направления и ожидаемые результаты, а не дублирует backlog.

Минимальная структура: **Now / Next / Later**

AI Ops должен: создавать roadmap, декомпозировать направления на outcomes, связывать roadmap ↔ milestones ↔ backlog, отслеживать прогресс, выявлять отклонения, автоматически актуализировать.

---

## PR-8. Backlog Management

GitHub Issues — операционная единица работы.

Типы: feature, bug, research, improvement, technical debt, experiment, infrastructure.

Атрибуты: type, priority, status, area, milestone, impact, urgency, effort, confidence, strategic alignment, dependencies.

AI Ops должен: собирать, классифицировать, находить дубликаты и устаревшие, декомпозировать крупные, связывать с roadmap, отслеживать зависимости.

---

## PR-9. AI Prioritization

Приоритет рассчитывается на основе: влияния, срочности, стоимости, стратегического соответствия, уверенности, зависимостей, влияния на milestone, влияния на пользователей, технического риска.

Для каждой рекомендации AI объясняет **почему задача получила такой приоритет**. Человек может переопределить — AI учитывает это в дальнейшем.

---

## PR-10. Delivery Management

AI Ops превращает backlog в исполнимый delivery plan: выбирает задачи для milestone с учётом зависимостей и capacity, определяет последовательность, выявлять блокеры, отслеживает прогресс, прогнозирует deadline, выявляет delivery risk.

---

## PR-11. GitHub Integration

GitHub — основной operational source of truth. AI Ops взаимодействует с Issues, PR, Milestones, Labels, Projects, Releases, Actions.

---

## PR-12. Team Synchronization

AI Ops автоматически формирует: текущий статус, прогресс milestone, изменения, блокеры, риски, ближайшие задачи, delivery forecast. Команда не должна собирать это вручную.

---

## PR-13. Product Health

AI Ops автоматически рассчитывает здоровье продукта: **Green / Yellow / Red** — с объяснением причин.

---

## PR-14. Tech Health

Отдельно — здоровье технологий: CI/CD, тесты, ошибки, технический долг, зависимости, security, deployment, архитектурные риски.

---

## PR-15. Delivery Health

Отдельно — здоровье delivery: выполнение milestone, velocity, blocked/overdue tasks, PR cycle time, release frequency, отклонение от плана.

---

## PR-16. Risk Management

AI Ops автоматически выявляет риски (product, delivery, technical, dependency, resource, strategic) и предлагает действие.

---

## PR-17. Dependency Management

AI Ops строит граф зависимостей между задачами, milestones, PR, компонентами, артефактами, внешними сервисами. Выявляет блокирующие задачи, критический путь, скрытые зависимости.

---

## PR-18. AI Decision Log

AI Ops сохраняет значимые решения AI: что решено, почему, на основании каких данных, результат, было ли изменено человеком.

---

## PR-19. Policy Engine

AI Ops имеет политики, определяющие допустимое поведение: **Suggest → Prepare → Execute → Require approval**.

---

## PR-20. Human Override

Человек всегда может изменить приоритет, roadmap, статус, отклонить рекомендацию. AI Ops воспринимает override как сигнал для будущих решений, а не как ошибку.

---

## PR-21. Continuous Product Audit

AI Ops периодически проводит аудит: артефакты, backlog, roadmap, delivery, tech, риски, policy. Результат — машиночитаемый отчёт.

---

## PR-22. Drift Detection

AI Ops обнаруживает расхождения между документацией и кодом, roadmap и backlog, backlog и delivery, Passport и фактическим состоянием.

---

## PR-23. Autonomous Product Loop

Конечная цель: **Observe → Understand → Plan → Prioritize → Execute → Evaluate → Learn → Replanning**. Переход от AI assistant к AI operator при сохранении human control.

---

## PR-24. Фазы развития

| Фаза | Название | Содержание |
|---|---|---|
| 1 | Product Operating Layer | Артефакты, templates, registry, passport, bootstrap, validation |
| 2 | Backlog Intelligence | GitHub Issues, классификация, дедупликация, приоритизация, зависимости |
| 3 | Roadmap & Delivery | Roadmap, milestones, delivery planning, forecasting, blockers |
| 4 | AI Product Operations | Auto-update, audit, drift detection, risk management, team sync, decision log |
| 5 | Autonomous AI Ops | Autonomous prioritization, replanning, auto-create tasks, learning from overrides |

---

## PR-25. Критерий успеха

> **AI Ops можно считать работающим, если команда после подключения репозитория не должна вручную поддерживать продуктовую операционку.**

Если человек перестал на несколько дней вручную обновлять backlog, roadmap и статусы — система не должна развалиться. Она должна сама обнаружить рассинхронизацию и восстановить актуальное состояние.

---

## Связь с планом

Цели в `planning/plan.yaml`:
- `product-operating-layer` — Phase 1 (6 работ)
- `backlog-intelligence` — Phase 2 (2 работы)
- `roadmap-and-delivery` — Phase 3
- `ai-product-operations` — Phase 4
- `autonomous-product-loop` — Phase 5

Все цели помечены `freeze_relation: extension` — встанут в очередь после снятия заморозки.
