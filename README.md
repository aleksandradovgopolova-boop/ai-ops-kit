# AI Ops Kit

Открытая **AI Product Operating System** для продуктово-технологических команд.

AI сопровождает продукт на всём жизненном цикле: Discovery → Delivery → Release → Measurement → Insights.

## Quick Start

```bash
# Установка в репозиторий
python3 installer/ai_ops.py init /path/to/project

# Задача
python3 .ai/managed/tools/ai_ops_cli.py run "описание задачи" . --execute

# Статус
python3 .ai/managed/tools/ai_ops_cli.py status .
```

## Что внутри

| Слой | Содержимое |
|------|-----------|
| **Execution Engine** | `ai-ops run` — единый движок «задача → draft PR» |
| **Quality Gates** | 32 гейта с machine-readable контрактами |
| **Agents** | 51 AI-агент с независимыми ревьюерами |
| **Registry** | Модели, провайдеры, workflow — machine-readable SoT |
| **Security** | 12 доменов, детерминированный scan, human-in-the-loop |
| **Observability** | Метрики стоимости, задач, доставки, моделей |

## Ключевые свойства

- **Spec-First** — модель не запускается, пока спека не достаточна
- **Fail-Closed** — сбой блокирует, не даёт ложный green
- **Writer ≠ Judge** — ревьюер не может закрыть свой гейт
- **Usage Truth** — unavailable ≠ 0, честный учёт стоимости
- **Provider-Agnostic** — Anthropic, OpenAI, DeepSeek, Claude CLI, локальные модели

## Версия

**v3.29.0 stable** — Field Findings

- честный первый запуск: `run --execute` сам поднимает живого провайдера, а не молча уходит в mock
- полнота intake проверяется ДО старта прогона, а не вердиктом после
- worktree режется от текущей ветки — последовательные задачи строятся друг на друге
- lifecycle не помечает работу `done` при `NOT_READY`
- 1019 pytest тестов (unit + contract + property-based)
- CI matrix: 7 параллельных групп
- Performance benchmarks + changelog automation

## Документация

- [Architecture](docs/architecture/overview.md)
- [Execution Engine](docs/architecture/execution-engine.md)
- [Quality Gates](docs/architecture/quality-gates.md)
- [Installation Guide](docs/guides/installation.md)
- [Child Repository](docs/guides/child-repo.md)
- [CI Configuration](docs/guides/ci.md)
- [API Reference](docs/api/contracts.md)

## Для разработчиков

```bash
# Установка для разработки
pip install -e ".[dev]"
pre-commit install

# Тесты
python3 -m pytest tests/ -v

# Coverage
python3 -m pytest tests/ --cov=tools --cov-report=term-missing

# Benchmarks
python3 tools/bench_performance.py --update-baseline

# Observability
python3 tools/kit_observability.py .
```

## Лицензия

MIT
