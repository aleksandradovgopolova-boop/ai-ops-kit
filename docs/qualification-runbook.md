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

## 6. Finding обкатки S10 (2026-07-18): `fixed` на уровне чека, не node-id

Живой S10 (red base + `--require-fix`, DeepSeek, база v2.121) вскрыл **false-negative движка**.
Модель корректно починила профильный тест (узел `test_discount10` red→green), а непрофильный
пред-существующий `test_legacy_report` остался красным (как и задумано на красной базе). Ожидалось
(acceptance S10): `baseline.fixed` содержит починенное → `ready_for_pr=true`. Фактически: `fixed=[]`,
`ready_for_pr=false`, `other_blocking_unmet=[]` — ready держит **исключительно** пустой `fixed`.

Корень: `_diff_checks` (`tools/execution_pipeline.py:571`) считает `fixed` на уровне **чек-агрегата** —
`fixed.append(name)` только когда чек целиком `fail→pass`. Раз чек `test` остаётся `fail` (из-за
непрофильного узла), починенный профильный узел не засчитывается. Node-id (`_failure_ids`) используется
лишь в сторону регрессий, не фиксов — асимметрия против заявки v2.84 про «structured-id baseline-diff».

Практика чтения S10-отчёта, пока не пофикшено: не доверяй `ready_for_pr` на красной базе вслепую —
сверь диф ветки (`git diff <baseline> ai-ops/<wid>`), реально ли починен целевой узел, и глянь финальный
`checks.test.output_tail` (какие узлы остались красными). Честно-консервативно (ложного green нет), но
легитимный фикс на красной базе под `--require-fix` блокируется. Полный разбор + направление фикса —
в ROADMAP, раздел «Осталось до v3.0-rc1».

## 6b. Finding S4 (ENGINEERING/DeepSeek): движок ✓, модель ✗

Подтверждён в нескольких живых прогонах (2 сессии): на S4 (`--review --author --task-type
ENGINEERING`) **движок отрабатывает верно** — `ready_for_pr=false` держится ровно когда должен:
артефакт-гейты (`requirements`/`specification`/`plan_readiness`) требуют валидных артефактов,
`code_review` требует вердикт (writer≠judge: ревью — отдельный read-only вызов, его `no-verdict`
**блокирует**, не маскируется зелёной реализацией), `security` — явный pass. **Слабость в модели:**
DeepSeek уходит в написание spec-бумаги и геймит кратчайший зелёный путь (чинит единственный
тривиальный падающий тест), целевой модуль часто остаётся нетронутым; `implementation_verification=
pass` лишь потому, что нет краснеющего теста. Какой авторский артефакт (`plan` vs
`requirements`/`specification`) приходит битым — **плавает** от прогона к прогону; `code_review`
`no-verdict` — стабильно. Вывод: S4-класс (small/medium ENGINEERING) на DeepSeek не готов — нужен
контраст на более сильной модели (Anthropic) или усиление author/review-промптов под слабую модель.
Читая S4-отчёт: всегда сверяй `git diff <baseline> ai-ops/<wid>` — тронут ли реальный целевой файл,
а не только починен ли тривиальный тест.

## 7. Готчи прогона (из живой обкатки)

- **Фикстура обязана нести pytest-сигнал.** Детектор (`project_detector.py:119`) выводит `test=pytest`
  только если строка «pytest» есть в `pyproject.toml`/`requirements` ИЛИ существует каталог `tests/`.
  Минимальный `pyproject.toml` без `[tool.pytest.ini_options]`/dev-зависимости pytest → `test=not_run`
  (undetermined) → env не квалиф. → ложный not-ready. Это дефект фикстуры, не движка (движок сообщает
  честно). Клади в фикстуру `[tool.pytest.ini_options]` или каталог `tests/`.
- **`--open-pr` без `GITHUB_TOKEN`** — движок честно отказывается на старте (PR не имитируется). Для S9
  нужен токен в env **и** реальный throwaway-remote (origin → GitHub).
- **Контейнер (S7):** образ `ai-ops-engine` не ставит dev-зависимости child (напр. `pytest`) → внутри
  env не квалиф. → доставленная ветка может быть пустой. Изоляция при этом доказуема (основной checkout
  байт-в-байт, ветка через доверенный fetch), но для зелёной доставки в контейнере ставь dev-deps.
- **`--sequential`** запускает package-executor только если планировщик делит задачу
  (`decomposition_advised=true`); атомарную задачу он честно исполняет обычным прогоном.
- **Канонический CLI** авто-классифицирует и часто грейдит простые задачи как ENGINEERING (spec-first
  блок). Для QUICK-пути используй `qual_run --task-type QUICK` или подай спеку/`--author`.
