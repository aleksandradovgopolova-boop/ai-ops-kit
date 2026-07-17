# Qualification Runbook (v2.84)

Как прогнать живую квалификацию движка на **реальном** child-репозитории с тулчейном и живой
моделью. Харнесс (`tools/qual_run.py`) и пакет сценариев (`qualification/scenarios.yaml`) готовы;
живой прогон делается на вашей машине (Mac/Linux), где есть модель и стек.

Честно: пройдёт ли **модель** конкретный сценарий — вопрос модели. Задача квалификации — убедиться,
что **движок честно отражает результат**: реальный коммит + evidence на точном SHA, никаких ложных
`ready_for_pr`, containment реально ограничивает, независимый ревьюер закрывает только то, что
проверил.

## 1. Окружение (ключи — только в env, не в аргументах и не в чат)

```bash
export OPENAI_COMPATIBLE_BASE_URL="https://api.deepseek.com/chat/completions"
export OPENAI_COMPATIBLE_API_KEY="…"        # ваш ключ, из менеджера секретов
# движок уже установлен в child: .ai/managed/ (v2.82 standalone — клон кита не нужен)
```

Проверка, что движок на месте: `ai-ops doctor` (строка «движок (standalone)») или
`python3 .ai/managed/validation/validate_standalone_engine.py .`.

## 2. Запуск одного сценария

Каждый сценарий из `qualification/scenarios.yaml` кладётся одной строкой в tasks-файл и гоняется
через харнесс. Пример (S1, node/python-репо, sandbox):

```bash
echo "добавь функцию форматирования цены с разделителями тысяч и покрой её тестом" > /tmp/s1.txt
python3 .ai/managed/tools/qual_run.py . --tasks /tmp/s1.txt \
  --provider openai-compatible --model deepseek-chat --sandbox --out qual-reports
```

Флаги по сценариям (см. `scenarios.yaml → flags`):

| Сценарий | Флаги | Что доказывает |
|---|---|---|
| S1 greenfield | `--sandbox` | task → проверяемый коммит на зелёном стеке |
| S2 fix true-green | `--sandbox --require-fix` | ловит «не сломал, но и не починил» |
| S3 regression-guard | `--sandbox` | structured-id baseline-diff ловит новый провал |
| S4 engineering-review | `--sandbox --review --task-type ENGINEERING` | независимый ревью + честный блок артефакт-гейтов |
| S5 containment | `--sandbox` | brokered-containment реально ограничивает петлю |

## 3. Как читать отчёт (`qual-reports/*.json`)

Ключевые поля (полная форма — `ai-ops run --json`):

- `ready_for_pr` — итог. **Не должен быть true**, если гейты блокируют или есть регрессии.
- `commit.sha` (40 hex), `commit.evidence_on_exact_sha=true` — evidence собран на том, что закоммичено.
- `baseline.regressions` / `baseline.fixed` — что правка сломала/починила (S2, S3).
- `gates.unmet` / `gates.gate_results` — какие гейты не пройдены и почему (S4: requirements/spec/plan
  честно блокируют без артефактов).
- `reviews` — вердикты независимого ревьюера (S4): `gate`, `status`, что читал, что отклонено.
- `containment` — `sandbox`, `shell_mode`, `block_push`, `allow_network` (S5).
- `loop.denied_reasons` — что брокер отклонил (S5: push/сеть/вне allowlist).

Приёмка каждого сценария — в `scenarios.yaml → acceptance`.

## 4. Матрица ОС/стеков

Минимум для квалификации: **S1–S5 на node(npm) и python(poetry) под macOS**.
Полная матрица — все стеки × обе ОС:

- **ОС:** macOS, Linux
- **Стеки:** node(npm+lock), node(pnpm workspaces/monorepo), python(poetry), python(pip+requirements),
  go(go.mod), java(gradle wrapper `./gradlew`)

Детектор (v2.84) предпочитает wrapper'ы (`./gradlew`, `./mvnw`) глобальным бинарям (иначе exit 127
на машине без установленного gradle/mvn) и помечает монорепо в `undetermined` — per-package покрытие
подтверждается вручную.

## 5. Что квалификация НЕ покрывает (честная граница)

- Полный контейнерный jail (лимиты ресурсов, изоляция ФС/сети на уровне runtime) — вне брокера.
- Артефакт-гейты requirements/specification/plan_readiness закрываются только реальными артефактами
  (product-authoring) — сейчас честно блокируют; это ожидаемый not-ready, а не провал движка.
- Полная независимость судьи (другая модель/человек) сильнее, чем тот же класс модели в роли ревьюера.
