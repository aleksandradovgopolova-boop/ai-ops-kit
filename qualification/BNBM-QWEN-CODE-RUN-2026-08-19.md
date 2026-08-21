# Прогон на втором brownfield через Qwen Code: `bolshe-ne-budu-menshe`, 19.08.2026

Прогон через Qwen Code (не `ai-ops run`, а AI-агент в сессии Qwen Code). Режим: на своей копии,
PR в репозиторий владельца не открываем. `verified PR = 0` — условие режима.

## Что сделано

Задача: `describe-planning-execution` — описать контур Planning & Execution.

Результат: создан документ `planning/planning-execution-contour.md` (50+ строк).

## Что описано в документе

1. **Что брать следующим** — `ai-ops next` с условиями допуска (deps_done, no_human_decision,
   capabilities_ready, within_budget) и детерминированным ранжированием.

2. **Что можно выполнять одновременно** — критерии параллельной безопасности (непересекающиеся
   write_scope, нет зависимости, нет общих контрактов) + реестр active_work с conflict forecast +
   multi-package execution (parallel_live.py).

3. **Кто должен делать** — принцип «роль, а не исполнитель» (owner_role), роутер в момент запуска
   выбирает runtime из .ai-ops.yaml.

4. **Связи между уровнями** — ROADMAP → plan.yaml → ai-ops run, с quality gates и execution pipeline.

5. **Текущее состояние** — describe-planning-execution единственный элемент без human_decision и без
   зависимостей, его можно брать прямо сейчас. describe-system-architecture зависит от него.
   Остальные шесть ждут решения владельца.

## Отличие от формального прогона кита

Это НЕ `ai-ops run`:
- Нет worktree (работа в основном дереве)
- Нет commit на ветке ai-ops/*
- Нет evidence (build/lint/test)
- Нет gate checks

Это работа AI-агента (Qwen Code) над репозиторием. Для формального закрытия `second-brownfield-run`
нужен прогон от владельца с `ai-ops run` и verified PR.

## Статус работы `second-brownfield-run`

Частичный результат: brownfield получил реальный документ. Формальное закрытие требует:
- Прогон от владельца (не AI-оператор)
- `ai-ops run` с evidence
- Verified PR (или снятие условия режима)
