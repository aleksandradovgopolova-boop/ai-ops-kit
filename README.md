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
| **Quality Gates** | 34 гейта объявлено; на конкретной задаче оценивается её набор (QUICK — 3) |
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

**v3.36.7 stable** — Qualification Readiness · Clean Update

- онбординг заканчивается РАБОТОЙ, а не документацией: `ai-ops bootstrap` собирает направление и
  план из фактов аудита, и `ai-ops next` сразу советует, за что взяться и почему
- то, чего кит знать не может, помечено «нужно ваше слово», а не заполнено правдоподобным текстом
- репозиторий описывает СЕБЯ: где лежит план, какие пути считать сигналом — и какой сигнал кита
  снять, если он не про ваш проект (`entities/` во Frontend-Sliced Design — не модель данных)
- с человеком говорят ВСЕ команды, а не четыре: наружу выходит смысл, внутренние имена остаются
  в технических деталях — и «проверено» не путается с «проверять было некому»
- репозиторий знает, КУДА идёт: `ROADMAP.md` (четыре горизонта) стал проверяемым артефактом
- и что брать СЛЕДУЮЩИМ: `ai-ops next` отвечает на четыре вопроса — где мы, что идёт, что
  блокирует и чем, какую работу взять и ПОЧЕМУ, что можно вести одновременно и какими ролями
- «Установи AI Ops» стало сценарием: `ai-ops model` изучает репозиторий, определяет его класс,
  восстанавливает доказуемое и спрашивает недостающее ОДНИМ пакетом — только то, что не видно в коде
- у каждого утверждения есть статус и основание: увидел / вывел / спросил / не знаю — догадка не
  публикуется как факт
- нельзя закрыть работу, обновив компонент, если изменилась модель данных: гейт `contour_consistency`
  сверяет затронутые контуры с заявленным (advisory до обкатки)
- «не умею видеть» больше не выглядит как «не менялось»: `unknown` не сворачивается в `not_changed`
- кит говорит с владельцем продукта, а не логом: сначала смысл, техника — по запросу; при этом
  недоказанное называется недоказанным
- план называет РОЛЬ, а не исполнителя: смена Claude Code на Codex не переписывает план продукта

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
