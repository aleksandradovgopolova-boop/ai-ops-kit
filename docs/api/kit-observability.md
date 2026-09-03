# Kit Observability

`ai_ops_kit/devtools/kit_observability.py` — метрики эффективности самого кита.

## CLI

```bash
# Человекочитаемый отчёт
python3 ai_ops_kit/devtools/kit_observability.py <child_root>

# JSON-формат
python3 ai_ops_kit/devtools/kit_observability.py <child_root> --json
```

## Метрики

### Cost

- `total_cost_usd` — общая стоимость всех вызовов
- `total_calls` — число вызовов моделей
- `avg_cost_per_call` — средняя стоимость вызова
- `avg_cost_per_workitem` — средняя стоимость на задачу
- `by_task_type` — разбивка по типу задачи (QUICK/ENGINEERING/PRODUCT)
- `by_provider` — разбивка по провайдеру
- `by_role` — разбивка по роли (implementation/review/fix_loop)
- `cost_complete` — True если все вызовы имеют известную стоимость

### Workitems

- `total` — число задач
- `by_status` — разбивка по статусу (draft/done/blocked)
- `by_lifecycle` — разбивка по стадии жизненного цикла
- `by_workflow` — разбивка по workflow

### Delivery

- `total` — число попыток доставки
- `sha_verified` — доставлено с верифицированным SHA
- `merged` — PR смержены
- `success_rate` — доля успешных доставок

### Models

- `by_provider` — число вызовов по провайдеру
- `by_model` — число вызовов по модели
- `measured_calls` — вызовы с известным usage
- `unavailable_calls` — вызовы без usage data

## Честность

- `unavailable` cost НЕ считается как $0 — показывается отдельно
- Пустой репозиторий → "Нет данных", не нулевые метрики
- Все метрики вычисляются детерминированно из файлов
