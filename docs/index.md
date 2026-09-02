# AI Ops Kit

**AI Product Operating System** — открытая система для продуктово-технологических команд.

AI сопровождает продукт на всём жизненном цикле: Discovery → Delivery → Release → Measurement → Insights → Discovery.

> **START HERE.** Единая точка входа — [QUICKSTART.md](QUICKSTART.md): полный канонический путь
> `init → doctor → onboard → specify → plan → run --execute`. Начинайте отсюда; команды ниже —
> сокращённая выжимка того же потока.

## Ключевые возможности

- **Execution Engine** — единый движок «задача → draft PR» с preflight-проверками, tool-loop, evidence collection и quality gates
- **Spec-First** — модель не запускается, пока спецификация не достаточна
- **Quality Gates** — 35 <!-- claim:gates-total --> гейта с machine-readable контрактами
- **Provider-Agnostic** — работает с Anthropic, OpenAI, DeepSeek, Claude CLI, локальными моделями
- **Fail-Closed** — сбой блокирует, а не даёт ложный green
- **Usage Truth** — честный учёт стоимости: unavailable ≠ 0

## Быстрый старт

```bash
# Установка в репозиторий
python3 <path-to-ai-ops-kit>/installer/ai_ops.py init .

# Задача
./ai-ops run "описание задачи" --execute

# Ревью
./ai-ops review
```

## Версия

Текущая: **v3.39.4 qualification** — канал `qualification`, а не `stable`: `stable` требует полевых
доказательств на живых дочках для этой версии и проверяется машиной
(`registry/release-claims.yaml`).
