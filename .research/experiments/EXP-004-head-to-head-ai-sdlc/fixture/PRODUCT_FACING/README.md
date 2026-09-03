# fixture-events-cli

Маленький CLI на stdlib: команда `list-events` печатает события из `events.json`
(поля `id`, `title`, `date` в формате `YYYY-MM-DD`).

```
python -m events_cli list-events
```

## Разработка

```
python -m pytest
```

## Задача

См. выданный контракт: добавить в `list-events` флаг `--since <date>`.
Требования, границы и определение готовности — в контракте задачи (task-spec).
