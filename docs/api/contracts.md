# TypedDict Contracts

`tools/contracts.py` — типизированные контракты для ключевых структур данных.

## UsageRecord

```python
from contracts import UsageRecord

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
from contracts import PreflightResult

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
from contracts import GateResultV2

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
from contracts import RunReport

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
