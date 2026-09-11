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
│  Execution Layer (ai_ops_kit/)                   │
│  Движок: orchestrator → pipeline → delivery      │
├─────────────────────────────────────────────────┤
│  Quality Layer (quality/, ai_ops_kit/validation/)│
│  Гейты, валидаторы, evidence                     │
├─────────────────────────────────────────────────┤
│  Core Layer (registry/, schemas/, config/)       │
│  SoT: агенты, workflow, модели, провайдеры       │
└─────────────────────────────────────────────────┘
```

> Плоский слой `tools/` снят в 4.0 — движок целиком под пакетом `ai_ops_kit/`
> (см. `MIGRATION_GUIDE_4.0.md`). Корневого `validation/` нет с 3.34 — валидаторы
> под `ai_ops_kit/validation/`.

## Ключевые модули

Точные размеры не фиксируем здесь (дрейфуют — их сторожат size-ратчеты в CI), важна ответственность.

| Модуль | Ответственность |
|--------|-----------------|
| `ai_ops_kit/providers/orchestrator.py` | Провайдеры, HTTP, usage recording |
| `ai_ops_kit/engine/execution_pipeline.py` | Pipeline: detect → tool-loop → evidence → gates |
| `ai_ops_kit/gates/preflight.py` | Pre-execution проверки (spec, atomic, budget) |
| `ai_ops_kit/engine/tool_loop.py` | Tool-calling loop с writer≠judge |
| `ai_ops_kit/engine/tool_broker.py` | Policy Engine + executor |
| `ai_ops_kit/engine/ai_ops_run.py` | Unified task controller |
| `ai_ops_kit/cli/ai_ops_cli.py` | Intent-based UX |

## Разбитые модули

- `ai_ops_kit/providers/orchestrator.py` → `orchestrator_http.py` + `orchestrator_providers.py` + `orchestrator_usage.py`
- `ai_ops_kit/engine/execution_pipeline.py` → `pipeline_helpers.py` + `pipeline_failure.py` + `pipeline_git.py` + `pipeline_evidence.py` + `pipeline_readiness.py` + `pipeline_setup.py`

## Три кольца (v3.26.0)

1. **Kernel** — не зависит от Intelligence. Ядро execution engine.
2. **Intelligence** — читает события Kernel. Модели, провайдеры, роутинг.
3. **Governance** — соединяется по риску. Гейты, security, compliance.
