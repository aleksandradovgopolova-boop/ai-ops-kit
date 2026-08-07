# Invariants Catalog

`tools/invariants.py` — каталог критических инвариантов с machine-checkable свойствами.

## Overview

19 инвариантов в 5 категориях, верифицируются property-based тестами (hypothesis).

## Preflight Invariants

| ID | Инвариант | Severity |
|----|-----------|----------|
| INV-PREFLIGHT-001 | blocked=True → reasons непустой | critical |
| INV-PREFLIGHT-002 | ok=False → blocked=True | critical |
| INV-PREFLIGHT-003 | ENGINEERING/PRODUCT/CRITICAL без спеки → blocked | critical |
| INV-PREFLIGHT-004 | reevaluate_only → skip build-preconditions | warning |
| INV-PREFLIGHT-005 | classification всегда в checks | critical |

## Pipeline Invariants

| ID | Инвариант | Severity |
|----|-----------|----------|
| INV-PIPELINE-001 | run_pipeline возвращает обязательные ключи | critical |
| INV-PIPELINE-002 | ready_for_pr=True → overall_status="done" | critical |
| INV-PIPELINE-003 | security not met → ready_for_pr=False | critical |
| INV-PIPELINE-004 | changed_files всегда list | warning |

## Delivery Invariants

| ID | Инвариант | Severity |
|----|-----------|----------|
| INV-DELIVERY-001 | sha_verified=True → remote_sha не None | critical |
| INV-DELIVERY-002 | status="reconciled" → sha_verified=True | critical |
| INV-DELIVERY-003 | DeliveryIntent имеет commit_sha и branch | critical |

## Usage Honesty Invariants

| ID | Инвариант | Severity |
|----|-----------|----------|
| INV-USAGE-001 | unavailable → tokens=None | critical |
| INV-USAGE-002 | measured → хотя бы один токен не None | critical |
| INV-USAGE-003 | cost_status=measured → cost не None | critical |
| INV-USAGE-004 | cost ≥ 0 | critical |

## Budget Invariants

| ID | Инвариант | Severity |
|----|-----------|----------|
| INV-BUDGET-001 | model_calls ≤ max_model_calls | critical |
| INV-BUDGET-002 | remaining = max - spent | critical |
| INV-BUDGET-003 | BudgetExceeded iff at ceiling | critical |

## Usage

```python
from invariants import check_invariant, ALL_INVARIANTS

# Проверить один инвариант
ok = check_invariant("INV-PREFLIGHT-001", blocked=True, reasons=["spec missing"])

# Список всех инвариантов
for inv in ALL_INVARIANTS:
    print(f"{inv['id']}: {inv['description']}")
```
