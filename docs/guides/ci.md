# CI Configuration

AI Ops Kit держит CI в двух слоях: быстрый путь на каждый PR и полный набор на non-draft PR
и push в main. Ниже — **канонический, аудируемый список обязательных статус-проверок защиты
ветки** (то, что GitHub называет *required status checks* в branch protection), плюс что из
проверок advisory, почему тяжёлое не гоняется на каждом PR и где живёт ночное.

## Обязательные статус-проверки защиты main

Настройка branch protection живёт в GitHub и в репозитории не видна — поэтому её декларация
хранится как данные в `quality/required-contexts.yaml`, а валидатор
`ai_ops_kit/validation/validate_required_contexts.py` сверяет этот список с реальными job в
`.github/workflows/*` (объявлен контекст, а job нет — красное; job есть, а не объявлен —
warning, не всякая job обязана блокировать). Таблица ниже — тот же список в читаемом виде;
источник истины — `required-contexts.yaml`, а не эта страница.

| Контекст (workflow / job) | Workflow | Что проверяет |
|---------------------------|----------|---------------|
| `pr-smoke / smoke` | `pr-smoke.yml` | Быстрый critical path (~2 мин): contract-тесты, ключевые валидаторы, формат заголовка PR |
| `package-quality / lint` | `package-quality.yml` | ruff класса «поломка» (F821/F811/B023/F841), битые `# noqa`, towncrier, `cz check` |
| `package-quality / quality (fast)` | `package-quality.yml` | Быстрая группа pytest (`.github/ci-groups/fast.sh`) |
| `package-quality / quality (selftests-a)` | `package-quality.yml` | Группа selftests-a (`selftests-a.sh`, `-m "slow and not nightly"`) |
| `package-quality / quality (selftests-m)` | `package-quality.yml` | Группа selftests-m (`selftests-m.sh`) |
| `package-quality / quality (contracts)` | `package-quality.yml` | Contract-группа pytest (`contracts.sh`) |
| `package-quality / clean-install` | `package-quality.yml` | Установка в чистый репозиторий, где кита нет рядом |
| `package-quality / upgrade-path` | `package-quality.yml` | Обновление предыдущий выпуск → рабочее дерево |
| `package-quality / pipeline-e2e (3.12)` | `package-quality.yml` | 20 process-contract тестов (инварианты процессов WP2–WP5) на Python 3.12 |
| `package-quality / security-scan` | `package-quality.yml` | Детерминированный скан диффа PR: секреты, неодобренные зависимости, injection-surface |
| `docs / build` | `docs.yml` | Сборка документации |

Эти десять контекстов должны стоять в required status checks защиты main. Из них
`clean-install`, `upgrade-path`, `pipeline-e2e` и `security-scan` — именно те проверки, что
защищают **дочерний** репозиторий: они гоняют установку/обновление кита в чистое окружение и
скан диффа, то есть ловят регресс до того, как тег доедет до дочки.

### Оговорки по событиям (капкан статусов)

- `security-scan` идёт только на событии `pull_request` (ей нужна база `origin/main` для diff)
  и в `merge_group` не запускается — как и `docs / build`. Пока merge queue не включён, это
  неважно; **перед** включением очереди этим job надо дать исход в `merge_group`, иначе
  обязательный пропущенный статус повесит очередь навсегда.
- Группы `quality (*)` не запускаются на **draft**-PR: условие
  `github.event_name != 'pull_request' || github.event.pull_request.draft == false`. Форма
  записана именно так (а не `== false`), потому что в `merge_group`/`push` события
  `pull_request` нет: `null == false` в выражениях Actions ложно, и джоба молча скипалась бы —
  обязательный контекст в очереди слияния не отдавался бы никогда.

## Advisory-гейты (не блокируют слияние)

Обкатываются non-blocking по политике dp-002 — печатают отчёт, но в required status checks не
внесены; перевод в блокирующие — осознанное решение владельца после обкатки.

| Job | Workflow | Статус |
|-----|----------|--------|
| `parallel-safety` | `pr-smoke.yml` | `--strict` (краснеет на PR, смешавшем код с координационным файлом — `planning/plan.yaml`, `history/plan-history.yaml`, `decisions/registry.yaml`, `registry/release-claims.yaml`), но пока **не** в required — красный виден, слияние не блокирует |
| `pr-size` | `pr-smoke.yml` | Advisory (без `--strict`): «одна работа = один малый PR», потолки из `quality/pr-budget.yaml`; только печатает отчёт |

Оба job идут только на `pull_request` (`if: github.event_name == 'pull_request'`) — тот же
капкан статусов: в `merge_group` PR-диффа нет.

## Draft PR

На draft-PR гоняется быстрый путь (`pr-smoke`), но не тяжёлые группы `package-quality`
(см. фильтр draft выше). Полный набор включается, когда PR выходит из draft.

## Nightly (вне пути PR)

Тяжёлое снято с обратной связи каждого PR (замер #462: два теста держали стену — мутационный
гейт ~6 мин и агрегатный bench ~2.5 мин). Помечено `-m nightly` и гоняется ночью, на push в
main и вручную (`workflow_dispatch`), а не блокирует PR — но остаётся исполняемым и обязательным.

| Workflow | Job | Когда | Что |
|----------|-----|-------|-----|
| `nightly-quality.yml` | `heavy-gates` | cron ~03:37 UTC, push в main, вручную | Мутационный гейт + агрегатный bench (`-m nightly`) |
| `nightly-coverage.yml` | `coverage` | cron ~03:17 UTC, push в main, вручную | Покрытие с порогом-ратчетом (пол 70%); снято с обязательных 2026-09-03 — держало ~10.8 мин на каждом PR |

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
Оба условия охраняет контракт-тест `tests/contracts/test_gate_measures_merge_result.py`.

Регресс к ручному опросу или снятие `merge_group` — это возвращение оплаченного дефекта,
а не упрощение.

## Release

Автоматический GitHub Release при изменении VERSION в main.

```yaml
# .github/workflows/release.yml
on:
  push:
    branches: [main]
    paths: [VERSION]
```

## Локальный запуск

```bash
# Группы package-quality
bash .github/ci-groups/fast.sh
bash .github/ci-groups/selftests-a.sh
bash .github/ci-groups/selftests-m.sh
bash .github/ci-groups/contracts.sh

# Только тесты
python3 -m pytest tests/ -v
```
