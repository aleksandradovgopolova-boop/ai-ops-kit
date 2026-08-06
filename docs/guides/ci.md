# CI Configuration

AI Ops Kit использует двухслойный CI.

## Слои

### 1. PR Smoke (~2 мин)

Запускается на каждый PR. Быстрая проверка critical path.

```yaml
# .github/workflows/pr-smoke.yml
- Contract tests (critical_path)
- Selftest wrappers (critical modules)
- Key validators
```

### 2. Package Quality (7 параллельных групп)

Запускается на non-draft PR и push в main.

```yaml
# .github/workflows/package-quality.yml
matrix:
  group: [core, execution, quality-product, culture-ops, context-security, validation, contracts]
```

Каждая группа — отдельный job на `ubuntu-latest`.

## Группы

| Группа | Содержание |
|--------|-----------|
| `core` | Registry, workflow, config, observability, changelog |
| `execution` | Orchestrator, pipeline, tool-loop, budget, gates |
| `quality-product` | Storybook, ADR, quality, context, cost |
| `culture-ops` | Session, delegation, commit, branch, deploy |
| `context-security` | Regression, loop-trace, security, parallel |
| `validation` | Python-compat, event-catalog, security-posture |
| `contracts` | Pytest contracts + validators |

## Локальный запуск

```bash
# Все группы последовательно
for g in .github/ci-groups/*.sh; do bash "$g" || exit 1; done

# Одна группа
bash .github/ci-groups/core.sh

# Только тесты
python3 -m pytest tests/ -v
```

## Release

Автоматический GitHub Release при изменении VERSION в main.

```yaml
# .github/workflows/release.yml
on:
  push:
    branches: [main]
    paths: [VERSION]
```
