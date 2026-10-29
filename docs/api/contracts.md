# TypedDict Contracts

`ai_ops_kit/shared/contracts.py` — типизированные контракты для ключевых структур данных.

## UsageRecord

```python
from ai_ops_kit.shared.contracts import UsageRecord

record: UsageRecord = {
    "run_id": "run-001",
    "workitem_id": "wid-001",
    "role": "implementation",
    "provider": "openai-compatible",
    "model": "deepseek-chat",
    "input_tokens": 1000,
    "output_tokens": 500,
    "usage_status": "measured",  # measured | estimated | unavailable
    "cost": 0.05,
    "cost_status": "measured",
    "latency": 2.0,
    "trigger": "initial",
}
```

**Честность:** `usage_status=unavailable` → `input_tokens=None` (НЕ 0).

## PreflightResult

```python
from ai_ops_kit.shared.contracts import PreflightResult

result: PreflightResult = {
    "kind": "preflight",
    "ok": True,
    "blocked": False,
    "checks": {"classification": {"ok": True, "task_type": "QUICK"}},
    "reasons": [],
}
```

## GateResultV2

```python
from ai_ops_kit.shared.contracts import GateResultV2

gate: GateResultV2 = {
    "schema_version": 2,
    "gate": "security",
    "status": "pass",  # pass | warn | fail | not_applicable | abstain
    "blocking": True,
    "applicability": "applicable",
    "enforcement": "blocking",
    "owner": "security-reviewer",
    "review_mode": "read-only",
}
```

## RunReport

```python
from ai_ops_kit.shared.contracts import RunReport

report: RunReport = {
    "workitem_id": "wid-001",
    "run_id": "run-001",
    "task": "implement feature X",
    "overall_status": "done",
    "ready_for_pr": True,
    "checks": {},
    "gates": {"met": ["security"], "unmet": []},
}
```

## Полный список

| TypedDict | Модуль | Описание |
|-----------|--------|----------|
| `UsageRecord` | usage_ledger | Запись учёта модельного вызова |
| `PreflightResult` | preflight | Результат preflight-проверок |
| `PreflightCheck` | preflight | Одна проверка preflight |
| `GateResultV2` | gate_result_v2 | Результат quality gate v2 |
| `GateCheck` | gate_result_v2 | Одна проверка внутри gate |
| `RunReport` | execution_pipeline | Отчёт execution pipeline |
| `DeliveryIntent` | ai_ops_run | Намерение доставки (PR) |
| `DeliveryReceipt` | ai_ops_run | Подтверждение доставки |
| `ContextBundle` | context_compiler | Пакет контекста для WorkItem |
| `WorkItemState` | workitem | Состояние WorkItem |

## Строгая типизация: первый срез #1412

Штатный `python3 -m mypy` читает `pyproject.toml`: прежние `kernel/` и `shared/`
сохраняются в охвате, к ним добавлен `ai_ops_kit/engine/run_context.py`. Полный набор флагов
`--strict` закреплён для `kernel.ports`, `shared.contracts`, `shared.events` и
`engine.run_context`. В mypy 2.3.1 `strict=true` внутри module override меняет
глобальные настройки, поэтому флаги развёрнуты явно; `warn_redundant_casts` включён
глобально, поскольку это global-only опция. Проверка effective options сверяет их
с настоящим `--strict`, а конфигурационный ратчет запрещает сокращение охвата.
[Правила конфигурации mypy](https://mypy.readthedocs.io/en/stable/config_file.html).

`RunContext` остаётся существующим источником состояния: фабрика имеет типизированные
входы и результат, callbacks различают текст провайдера и словарь действия,
`max_steps`, модели и пути имеют конкретные типы. Внедрённые reviewer/author callbacks
могут вернуть строку либо уже разобранный словарь — оба варианта принимают существующие
парсеры; текстовый callback провайдера по-прежнему возвращает строку. Открытые payloads `signals`,
`model_resolution`, trust и `override` сохраняют явный `Any` в значениях:
полной статической проверки их содержимого этот срез не обещает. Подписчик событий
принимает словарь; его результат шина игнорирует, поэтому тип результата — `object`.

`follow_imports=silent` сохраняется: mypy видит экспортированные типы, но ошибки
в импортированных модулях вне targets не расширяют работу на весь пакет.
[Положительная и отрицательные пробы](../../tests/unit/test_strict_typing_probes.py)
проверяют настоящий импорт потребителем, а существующая джоба `lint` исполняет их
после установки закреплённого mypy. `py.typed` пока не добавлен. Роутер, runtime
adapters и остальные модели состояния остаются следующими срезами #1412.

### Решение по Pydantic v2

Решение этого среза: **не внедрять Pydantic**. Сравнение сделано с существующими
`schemas/workitem.schema.json` и `schemas/gate-result-v2.schema.json`; внешняя
JSON Schema остаётся источником формата, а TypedDict описывает используемые Python
представления, иногда частичные. `total=False` не доказывает наличие обязательных
полей внешнего документа и не заменяет runtime-валидацию схемы.

| Критерий | Текущий контракт | Pydantic v2 и цена перехода |
|---|---|---|
| Источник формата | Draft-07 JSON Schema: `required`, `const`, `enum`, `$ref` | Генерирует JSON Schema из Python-моделей; перенос авторства потребовал бы отдельного решения и сверки совместимости |
| WorkItem | `required` включает `paths`, `schema_version`, `kind`; статическое `WorkItemState` — частичная проекция | Модель надо получать из схемы либо переносить источник в Python; ручная копия станет второй истиной |
| GateResult v2 | `additionalProperties: false`, nullable override с обязательными `by`/`reason`, `scope` как массив строк | Понадобятся согласованные extra/strict/defaults/nullable-настройки; одна аннотация TypedDict не кодирует всё это |
| Значения входа | Схема задаёт допустимый формат, без добавленной нормализации | По умолчанию преобразует типы; strict снижает преобразования, но JSON-вход имеет отдельные оговорки |
| Зависимости и runtime | stdlib + PyYAML, обычные словари и dataclass | Новая runtime-зависимость и изменение границы создания объектов; для статического среза не нужны |

Возможность генерации схем — по [документации Pydantic](https://docs.pydantic.dev/latest/concepts/json_schema/),
преобразование значений и особенности strict JSON — по
[описанию strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/).
Это сравнение, а не выполненный эксперимент миграции: эквивалентность двух валидаторов
не измерялась. Перед возможным переходом нужен отдельный план с одним источником и
корпусом одинаковых positive/negative документов, включая missing/extra/null/enum,
вложенные поля и прежние совместимые документы; затем решение о зависимости.
