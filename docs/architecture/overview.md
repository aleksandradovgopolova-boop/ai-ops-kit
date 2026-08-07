# Architecture Overview

AI Ops Kit — модульная система с чётким разделением ответственности.

## Слои

```
┌─────────────────────────────────────────────────┐
│  Installer (installer/ai_ops.py)                │
│  Устанавлиет пакеты в child-репозитории          │
├─────────────────────────────────────────────────┤
│  Product Layer (agents/, templates/, skills/)    │
│  AI-агенты, шаблоны, навыки                      │
├─────────────────────────────────────────────────┤
│  Execution Layer (tools/)                        │
│  Движок: orchestrator → pipeline → delivery      │
├─────────────────────────────────────────────────┤
│  Quality Layer (quality/, validation/)           │
│  Гейты, валидаторы, evidence                     │
├─────────────────────────────────────────────────┤
│  Core Layer (registry/, schemas/, config/)       │
│  SoT: агенты, workflow, модели, провайдеры       │
└─────────────────────────────────────────────────┘
```

## Ключевые модули

| Модуль | Строк | Ответственность |
|--------|-------|-----------------|
| `orchestrator.py` | 606 | Провайдеры, HTTP, usage recording |
| `execution_pipeline.py` | 3210 | Pipeline: detect → tool-loop → evidence → gates |
| `preflight.py` | 372 | Pre-execution проверки (spec, atomic, budget) |
| `tool_loop.py` | 682 | Tool-calling loop с writer≠judge |
| `tool_broker.py` | 689 | Policy Engine + executor |
| `ai_ops_run.py` | 2180 | Unified task controller |
| `ai_ops_cli.py` | 887 | Intent-based UX |

## Разбитые модули (v3.28.0)

- `orchestrator.py` → `orchestrator_http.py` + `orchestrator_providers.py` + `orchestrator_usage.py`
- В процессе: `execution_pipeline.py` → `pipeline_helpers.py` + `pipeline_failure.py` + `pipeline_git.py` + `pipeline_evidence.py`

## Три кольца (v3.26.0)

1. **Kernel** — не зависит от Intelligence. Ядро execution engine.
2. **Intelligence** — читает события Kernel. Модели, провайдеры, роутинг.
3. **Governance** — соединяется по риску. Гейты, security, compliance.
