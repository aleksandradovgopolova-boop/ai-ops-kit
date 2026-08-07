# AI Ops Kit

**AI Product Operating System** — открытая система для продуктово-технологических команд.

AI сопровождает продукт на всём жизненном цикле: Discovery → Delivery → Release → Measurement → Insights → Discovery.

## Ключевые возможности

- **Execution Engine** — единый движок «задача → draft PR» с preflight-проверками, tool-loop, evidence collection и quality gates
- **Spec-First** — модель не запускается, пока спецификация не достаточна
- **Quality Gates** — 32 гейта с machine-readable контрактами
- **Provider-Agnostic** — работает с Anthropic, OpenAI, DeepSeek, Claude CLI, локальными моделями
- **Fail-Closed** — сбой блокирует, а не даёт ложный green
- **Usage Truth** — честный учёт стоимости: unavailable ≠ 0

## Быстрый старт

```bash
# Установка в репозиторий
python3 <path-to-ai-ops-kit>/installer/ai_ops.py init .

# Задача
python3 .ai/managed/tools/ai_ops_cli.py run "описание задачи" . --execute

# Ревью
python3 .ai/managed/tools/ai_ops_cli.py review
```

## Версия

Текущая: **v3.28.0 stable** (Verification Foundation II)
