# Installation

## Требования

- Python 3.9+
- Git
- (Опционально) Node.js 22+ для OpenSpec

## Установка в репозиторий

```bash
# Клонировать AI Ops Kit
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
cd ai-ops-kit

# Установить в ваш проект
python3 installer/ai_ops.py init /path/to/your/project
```

## Установка для разработки

```bash
# Клонировать
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
cd ai-ops-kit

# Установить как editable package
pip install -e ".[dev]"

# Установить pre-commit hooks
pre-commit install

# Запустить тесты
python3 -m pytest tests/ -v
```

## Проверка установки

```bash
# Проверить статус
python3 .ai/managed/installer/ai_ops.py status .

# Проверить capabilities
python3 .ai/managed/installer/ai_ops.py verify-capabilities .
```

## Обновление

```bash
# Обновить managed-пакет
python3 .ai/managed/installer/ai_ops.py update .
```
