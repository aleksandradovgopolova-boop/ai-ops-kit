# Architecture Overview

AI Ops Kit — модульная система с чётким разделением ответственности.

## Слои

Пакеты движка `ai_ops_kit/` лежат в пяти слоях; зависимость разрешена только вниз
(источник истины — `packages/layering.yaml`, проверка — `validate_layering.py`):

```
entrypoints   cli · devtools · validation          точки входа
intelligence  intelligence                          аналитика, читает события ядра
capabilities  context · providers · lifecycle · gates · engine · delivery · engops · planning
primitives    security · ui · integrations · governance · checks
foundation    shared · kernel                       пути, контракты, порты ядра
```

Вокруг движка: `installer/ai_ops.py` ставит кит в дочку, `registry/` и `schemas/` — источник
истины (агенты, workflow, модели), `agents/`, `templates/`, `skills/` — прозаический слой.

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
2. **Intelligence** — читает события Kernel. Аналитика, product-learning, ночные обзоры.
3. **Governance** — соединяется по риску. Гейты, security, compliance.
