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

## 6. Finding обкатки S10 (2026-07-18): `fixed` на уровне чека, не node-id — ✅ ПОФИКШЕНО (v2.122)

> **Статус: закрыто в v2.122.** `_diff_checks` теперь считает починенные узлы симметрично регрессиям
> (`fixed_ids = _failure_ids(baseline) − _failure_ids(after)` в ветке `fail→fail`; чек попадает в
> `fixed` при непустом множестве). Fail-safe: требуется непустой `after`-id (иначе не фабрикуем
> `fixed` на непарсибельном выводе); swap «починил один — сломал другой» по-прежнему уходит в
> `regressions`. Живой перепрогон S10 подтвердил `ready_for_pr=True`, `baseline.fixed=['test']`,
> `regressions=[]`. Ниже — исходный разбор finding (сохранён для истории).

Живой S10 (red base + `--require-fix`, DeepSeek, база v2.121) вскрыл **false-negative движка**.
Модель корректно починила профильный тест (узел `test_discount10` red→green), а непрофильный
пред-существующий `test_legacy_report` остался красным (как и задумано на красной базе). Ожидалось
(acceptance S10): `baseline.fixed` содержит починенное → `ready_for_pr=true`. Фактически: `fixed=[]`,
`ready_for_pr=false`, `other_blocking_unmet=[]` — ready держит **исключительно** пустой `fixed`.

Корень: `_diff_checks` (`tools/execution_pipeline.py:571`) считает `fixed` на уровне **чек-агрегата** —
`fixed.append(name)` только когда чек целиком `fail→pass`. Раз чек `test` остаётся `fail` (из-за
непрофильного узла), починенный профильный узел не засчитывается. Node-id (`_failure_ids`) используется
лишь в сторону регрессий, не фиксов — асимметрия против заявки v2.84 про «structured-id baseline-diff».

Практика чтения S10-отчёта (общая гигиена, уже не про баг): на красной базе всё равно полезно сверить
диф ветки (`git diff <baseline> ai-ops/<wid>`) — реально ли починен целевой узел — и глянуть финальный
`checks.test.output_tail` (какие узлы остались красными как задумано). Полный разбор фикса — в манифесте
(`fixed_v2_122...`) и CHANGELOG [2.122.0].

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

## 6c. Итог живой RC-квалификации (v2.125 → v3.0-rc1, 2026-07-20)

Живая квалификация (DeepSeek/Mac) закрыта; выпущен **v3.0-rc1** с узким честным claim: **QUICK —
trustworthy task → verified draft PR для supervised low-risk задач**. Что подтверждено живьём:
S1/S2/S6/S7/S9, S8 resume (`resumed=True`), canonical CLI без `--task-type` (тривиальная → QUICK),
approval negative/positive (ApprovalRecord binding), dependency-без-signal (security форсируется даже
в QUICK). Квалификация нашла и починила 2 бага в выпущенных фичах (→ v2.124.1): security проскакивал
в QUICK; ложный `scope-violation` на артефактах движка в sequential.

**Не в rc1-claim (→ v3.0 stable):** positive-green small/medium ENGINEERING на живой модели (DeepSeek
не доводит review/needs_review до pass и не всегда доделывает реализацию — движок честно блокирует, но
сценарий не «зелёный»); живой 3-пакетный sequential до `ready_all` + намеренный fail на package 2
(структура доказана детерминированно). Нужна более сильная модель / усиленные промпты + dogfood.

## 6d. Живая ENGINEERING-квалификация на сильной модели (kimi, 2026-07-20)

Прогон на **kimi/Moonshot** (base `https://api.moonshot.ai/v1/chat/completions` — ПОЛНЫЙ путь, как у
DeepSeek; модели: `kimi-k3`, `kimi-k2.6`, `kimi-k2.7-code`). Вывод: **kimi заметно сильнее DeepSeek** —
производит валидный `plan` + `specification` (openspec закрыт) и **реальный вердикт `code_review`**
(DeepSeek стабильно no-verdict). Движок при этом честен: невалидная/пустая author-спека → 0
implementation (P0.1 pre-authoring держится и на сильной модели).

**Блокер positive-green — нестабильность провайдера, не движок:** `kimi-k3` был server-overloaded
(`429 engine_overloaded`), `kimi-k2.7-code` интермиттентно отдаёт HTTP-200 с пустым content → author
флакает. Движок укреплён (rc6: устойчивый `_parse_yaml_block` + retry пустого 200 в `_openai_call`),
но при сильной перегрузке провайдера и ретраев мало. **Чтобы закрыть positive-green ENGINEERING:**
повторить, когда kimi-k3 разгрузится, ИЛИ поднять число ретраев, ИЛИ стабильный сильный провайдер
(Anthropic). Endpoint-config для OpenAI-совместимого провайдера — ПОЛНЫЙ URL до `/chat/completions`.

### 6d-bis. Полная ENGINEERING-цепочка отработала end-to-end (kimi-k3, rc7→rc11, 2026-07-20)

Живой полный ENGINEERING на разгрузившемся `kimi-k3` прошёл **насквозь** и вскрыл цепочку РЕАЛЬНЫХ
движковых дефектов (каждый чинился и релизился отдельно):

- **rc7** — reasoning-токены: `_MAX_TOKENS 2048→8192` (kimi тратил весь бюджет на reasoning до
  контента → пустой author-артефакт). После — `requirements`+`plan` валидны.
- **rc8** — spec-tasks с двоеточием («Написать тесты: A, B») YAML-парсились как mapping → нормализация
  → `specification` валидна. Все три author-артефакта зелёные.
- **rc9** — независимому ревьюеру **не передавали дифф** (`base_context=""`): `_run_reviews`/
  `_review_security` вызывали `run_review` с пустым контекстом → ревьюер честно fail'ил «нечего
  читать» (`reads=[]`), `code_review` был структурно НЕпроходим. Фикс: `_change_context` (git show
  --stat + unified-дифф) → ревьюер реально читает изменение (`reads=7`).
- **rc10** — reasoning-модель тратила весь read-бюджет и не успевала заключить → тихий `no-verdict`.
  Фикс: форс-ход вердикта после исчерпания чтений + `max_reads 6→10` → ревьюер выносит РЕАЛЬНЫЙ
  вердикт (`stopped=verdict`, `reviewed_revision=pass`).
- **rc11** — `warn` на блокирующем гейте блокировал БЕЗ обязанности назвать причину (асимметрия:
  blockers требовались только для `fail`). Фикс: `status∈{fail,warn}` обязан иметь непустой
  `blockers`; промпт — симметричная честность (не фабрикуй ни pass, ни блок).

**Итог:** на добротной реализации (kimi реально отрефакторил `discounts.py` — таблица ставок вместо
дублирующих веток, +92 строки тестов, `tests pass`, реальный коммит) движок отработал ВСЮ строгую
цепочку: валидные артефакты → реальный код → `security` **pass** → независимый `code_review` на
фактическом диффе с обоснованным вердиктом. `ready_for_pr=False` держался ЧЕСТНО из-за `code_review=warn`
(ревьюер не дал чистый pass). **Positive-green (`ready_for_pr=true`) теперь зависит исключительно от
чистого `pass` ревьюера по реальному коду — это model-quality вопрос, НЕ движковый дефект.** Все
движковые ложные блокеры (парсинг/доставка диффа/сходимость вердикта/обоснование блока) закрыты.

### 6e. Живой 3-пакетный sequential (S-SEQ): hard-stop на package 2 — ПОДГОТОВЛЕНО

Сценарий для оставшегося ROADMAP-пункта «живой sequential до `ready_all` + намеренный fail на
package 2 → стоп package 3». Структура транзакции уже доказана детерминированно
(`workpackage_executor --selftest`); здесь — живой прогон через **канонический CLI**.

**Фикстура** (генерится вне кита, `/tmp/qual-seq/eng`; НЕ коммитим). Три подсистемы →
`by-subsystem` даёт 3 пакета (`MAX_SUBSYSTEMS=2`), цепочка зависимостей pkg1→pkg2→pkg3:

| Пакет | scope / write_scope | Задача | База |
|---|---|---|---|
| pkg-1 `discounts` | `discounts/`, `tests/discounts/` | убрать дублирование веток в таблицу ставок | зелёная |
| pkg-2 `pricing` | `pricing/`, `tests/pricing/` | реализовать+покрыть `net_price` | **1 тест красный by-design** |
| pkg-3 `report` | `report/`, `tests/report/` | форматированная итоговая строка | зелёная |

**Механика намеренного fail на pkg-2 (не зависит от доброты модели):** красный тест
`tests/pricing/test_net_price_exists` требует `discounts.core.net_price` — а `discounts/` **вне
write_scope pkg-2**. Дилигентная модель попытается записать в `discounts/` → брокер отклонит →
`_hard_stop` = **`scope-violation`**; ленивая — оставит тест красным → `--review` даёт
**`reviewer-fail`** (rc11: ревьюер читает дифф и честно fail'ит с конкретикой). Любой исход →
цепочка стоп на pkg-2 → **pkg-3 (report) НЕ стартует**. Красный тест — runtime (импорт внутри
функции), не collection, чтобы не рушить сбор тестов pkg-1/pkg-3.

**Команда** (ключ провайдера — только в env, не в аргументах/отчётах):

```bash
bash prep_seq_fixture.sh /tmp/qual-seq/eng   # собрать фикстуру (генератор вне кита)
OPENAI_COMPATIBLE_BASE_URL="…/chat/completions" OPENAI_COMPATIBLE_API_KEY="…" \
python3 tools/ai_ops_cli.py run \
  "Отрефактори расчёт скидок по подсистемам: discounts — таблица ставок; pricing — реализуй net_price из discounts; report — форматированная строка" \
  /tmp/qual-seq/eng \
  --signals '{"task_type":"ENGINEERING","size":"large","risk":"low","affected_areas":["discounts","pricing","report"]}' \
  --execute --sequential --provider openai-compatible --model kimi-k3 \
  --feature seqdemo --max-steps 60
```

Авто-флаги ENGINEERING (проверено `preview`): `sandbox`+`baseline_diff`+`review`+`author`.

**Приёмка (структурная, честная — не «зелёный любой ценой»):**
- `SEQUENCE seqdemo: ready_all=false · stopped_at=seqdemo-pkg-2-pricing`;
- pkg-1 `executed`/`ready`, коммит есть; pkg-2 `stop_reason ∈ {scope-violation, reviewer-fail, regression}`;
- **pkg-3 отсутствует в исполненных** (не стартовал — hard-stop истинный, не строим поверх сломанного);
- `work-packages/<pid>/` per-package lifecycle-снимки на месте; `sequence-plan.yaml` с `plan_hash`.
- Опц. happy-path (без красного теста в pkg-2) → `ready_all=true` — упирается в ту же флакость
  провайдера (kimi author flaky), что и одиночный ENGINEERING; движковая часть не блокирует.

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
