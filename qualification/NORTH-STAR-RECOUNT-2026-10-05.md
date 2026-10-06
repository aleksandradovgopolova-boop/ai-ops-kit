# Снимок пересчёта главной метрики

Содержимое исходного снимка сохранено без изменения.

```json
{
  "period": {
    "start": "2026-09-08",
    "end": "2026-10-05",
    "grain": "calendar dates, inclusive; current day partial"
  },
  "rows": [
    {
      "repo": "ii-sreda",
      "sha": "23c61f600f73b527131f75443b8c733373056b11",
      "registered_features": 9,
      "readouts_in_window": 1,
      "documented_cycles": 1,
      "actual_cycles": "unknown: only repository evidence inspected"
    },
    {
      "repo": "ai-ops-cockpit",
      "sha": "3633db0b33b175683f9b1334fc51b39fd090be6f",
      "registered_features": 0,
      "readouts_in_window": 0,
      "documented_cycles": 0,
      "actual_cycles": "unknown: only repository evidence inspected"
    },
    {
      "repo": "bolshe-ne-budu-menshe",
      "sha": "044b61d8d3ae0b89a655654a63e5263e416cd1a1",
      "registered_features": 0,
      "readouts_in_window": 0,
      "documented_cycles": 0,
      "actual_cycles": "unknown: only repository evidence inspected"
    },
    {
      "repo": "niti",
      "sha": "d14c2bf00a813a1c68399c71598cba964b6ed217",
      "registered_features": 0,
      "readouts_in_window": 0,
      "documented_cycles": 0,
      "actual_cycles": "unknown: only repository evidence inspected"
    }
  ],
  "candidates": [
    {
      "repo": "ii-sreda",
      "feature": "analytics-visit-tracking",
      "measurement_date": "2026-09-21",
      "decision_recorded_date": "2026-09-24",
      "value": 19,
      "target_met": "no",
      "registered_candidate": true,
      "source_path": "features/analytics-visit-tracking/outcome-readout.yaml"
    }
  ],
  "documented_cycles": 1,
  "predeclared_numeric_contract_cycles": 0,
  "classification": "one candidate manually corroborated with original spec, review verdict, approved merged PR963, and kit field report; numeric contract created after implementation; no causal effect or raw production data independently verified"
}
```
