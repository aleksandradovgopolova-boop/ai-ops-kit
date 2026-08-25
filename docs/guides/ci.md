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

## Слияние: родной merge queue (v3.38)

Зелёный PR вливается **родным GitHub merge queue** (кнопка «Merge when ready» / auto-merge),
а не ручным интегратором. Почему (разбор 20.08.2026): ручной polling-цикл падал на таймаутах
`gh`, отчитывался «влито» по факту запуска команды и сверял SHA с пустой строкой; а гейты,
меряющие ветку PR, пропускали дрейф main (490→498 файлов тихо).

Что даёт очередь:

- **Пороги меряются против итога слияния** (`gate-measures-merge-result`): очередь строит
  временный merge-коммит и требует все обязательные контексты НА НЁМ. Coverage, footprint и
  ратчеты не могут уехать «между» зелёными ветками.
- **DIRTY не возникает**: очередь сама батчит и ребейзит.

Механика в workflow: оба файла (`package-quality.yml`, `pr-smoke.yml`) объявляют триггер
`merge_group:`, а условие draft-фильтра сформулировано как
`github.event_name != 'pull_request' || ...` — иначе в merge_group событие `pull_request`
отсутствует, `null == false` ложно, джоба тихо скипается и обязательный контекст не отдаётся
никогда — очередь висит (капкан статусов, уже прожитый 20.08 с удалённой джобой).
Оба условия охраняет контрактный страж (добавляется работой `gate-measures-merge-result`).

Регресс к ручному опросу или снятие `merge_group` — это возвращение оплаченного дефекта,
а не упрощение.
