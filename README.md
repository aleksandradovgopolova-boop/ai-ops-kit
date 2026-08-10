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
| **Quality Gates** | 33 гейта объявлено; на конкретной задаче оценивается её набор (QUICK — 3) |
| **Agents** | 51 роль объявлена в реестре; движок вызывает по имени 10, остальные — контракты владения и ревью |
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

**v3.33.3 stable** — Пакет стал пакетом

- остаточный `.pth`-пояс кита в site-packages виден: `ai-ops doctor` блокирует и говорит, чем убрать
- `ai_ops_kit` импортируется как пакет — проверено настоящей установкой в venv, 95 модулей из 95
- установка не правит `sys.path` чужих процессов: пакет не пишет `.pth` в ваше окружение
- инвариант трёх колец проверяется: ядро не зависит от аналитики (пакет `intelligence` слоем выше)
- границы 13 пакетов имеют силу: направления зависимостей проверяются по реальному графу импортов
- код движка живёт в `ai_ops_kit/` — 95 модулей, 13 пакетов; плоские имена остались алиасами
- прогон установки в чистом окружении: кит проверяется там, где нет ни кита, ни pytest, ни `PYTHONPATH`
- в продакшн-модулях не осталось ни строки `selftest()`: 26% → 0, поставка 3.01 → 2.52 МиБ
- контур проверки — одна команда `./scripts/check-full.sh`: чеклист 205 команд → 0, группы CI 7 → 4
- правка подтверждается тестом, который падает на коде ДО неё, — не только «ничего не сломалось» (v3.30.0)
- все 71 валидатор имеют внешний тест (глубина разная: контракт функции / рантайм / штучные)
- честный первый запуск, полнота intake до старта, worktree от текущей ветки (v3.29.0)
- валидаторы стартуют без `PYTHONPATH` — то есть в child-репозитории, а не только в CI
- 1519 pytest тестов (unit + contract + property-based)

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
