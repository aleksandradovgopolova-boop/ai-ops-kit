# Миграция со старой структуры агентов

## Что сохраняется

Содержательно сохраняются роли бизнес-аналитика, продуктового аналитика, системного аналитика, архитектора, frontend/backend/fullstack-разработчиков, тестировщика, security/accessibility reviewer, DevOps, release manager и documentation steward.

## Что меняется

1. Дубли `repository-explorer` и `reviewer` заменяются одной канонической версией.
2. `Development Orchestrator` больше не проектирует решение сам: план создаёт `Task Planner`, интеграцию выполняет `Implementation Integrator`.
3. Добавляется централизованное состояние задачи и обязательный handoff.
4. Линейная цепочка заменяется адаптивными workflows по типу и риску задачи.
5. Review разделяется на code, requirements, security, accessibility, performance и финальную проверку цели.

## Рекомендуемый порядок внедрения

### Этап 1. Основа

Подключить:

- `Context Builder`;
- `Task Planner`;
- `Final Verifier`;
- `TaskBrief`, `TaskState`, `TaskHandoff`, `VerificationEvidence`;
- `ContextManagement`, `ScopeControl`, `EvidencePolicy`, `DefinitionOfDone`.

### Этап 2. Оркестрация

Подключить команды `ai-start-task`, `ai-plan-task`, `ai-review`, `ai-verify`, `ai-finish-task` и три workflow: feature, bug fix, integration change.

### Этап 3. Специализация

Подключать database, integration, observability, regression и performance роли только при наличии реальных задач.

### Этап 4. Самоулучшение

Добавить evaluations, repository memory и регулярный аудит агентов.

## Совместимость

Файлы написаны vendor-neutral. Платформенные инструкции вынесены отдельно, поэтому роли можно использовать в Claude Code, Codex, Roo Code, ZCode и других средах без переписывания их основной логики.

## Миграция 1.x -> 2.0

Breaking-изменений нет: все контракты остаются schema_version 1, обновление —
штатный `ai-ops update`. Мажорная версия отмечает завершение платформы
AI Product Operating System (roadmap Ф1-Ф4), а не слом совместимости.

Новое в 2.0 (всё опционально для child):
- Knowledge Graph: словарь registry/entities.yaml; граф проекта — knowledge/graph.yaml
  (валидатор validate_knowledge_graph.py);
- Product Health: tools/product_health.py + schemas/product-health.schema.json;
- workflow INSIGHTS (данные после релиза -> инсайты -> гипотезы следующего Discovery).
