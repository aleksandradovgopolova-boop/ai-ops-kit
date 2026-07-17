# CHANGELOG — AI-first система (пакет)

Формат: [SemVer](https://semver.org/lang/ru/). Версия пакета — в `VERSION`.

## [2.85.0] — 2026-07-17 — Containment hardening (адверсарный ре-ревью v2.81–2.84)

Независимый адверсарный ре-ревью только что выпущенного trust-кода (writer ≠ judge, применённый
к собственной работе) нашёл реальные дыры — включая **ложный green**. Закрыты все находки.

### Fixed
- **Ложный green (самый острый): `_diff_checks` пропускал потерю покрытия.** `pass→warn` и
  `fail→warn` не считались регрессией. Модель могла «починить» красный тест, **удалив** его
  (`tests_absent` → `warn`) → `no_regressions=true` → `ready_for_pr=true`. Теперь исчезновение
  вердикта (`pass`/`fail` → `warn`/`not_run`) = регрессия.
- **Shell allowlist обходился chaining/pipe/substitution.** Проверялся только первый токен, так что
  `pytest && curl …`, `x | nc …`, `echo $(curl …)` проходили. Теперь allowlist проверяется
  **посегментно** (split по `;`/`&&`/`||`/`|`), подстановка команд (`$()`/`` ` ``/`<()`) в
  allowlist-режиме запрещена, а сырые `bash`/`sh` убраны из `SANDBOX_SHELL_ALLOWLIST`.
- **`block_push` и сетевой денай обходились quote-обфускацией** (`git pu""sh`, `cu"r"l`). Матч теперь
  по нормализованной (снятые кавычки) команде. Claim честно понижен с «всегда» до **best-effort**:
  переменные/eval не ловятся — жёсткая гарантия недоставки лежит в окружении (нет push-credentials).
- **Reviewer `warn` на блокирующем гейте** раньше тихо его закрывал (evidence-проверка только для
  `pass`). Теперь `warn` на блокирующем ai-review гейте = блок.
- **`security`/`ai_red_team` больше не отдаются авто-ревью той же модели** (`NO_SELF_REVIEW`) —
  self-attestation недопустима для security-критичных гейтов; нужна независимость/человек.
- **`output_tail` shell 400 → 4000.** Сводка теста / список упавших node-id для structured-id
  baseline-diff часто не попадали в 400-символьное окно (fail-open) → регрессии терялись.

### Changed
- **`rules/ai/ToolBrokerPolicy.md`** — правила 6–8 и секция ревьюера приведены в соответствие с
  фактическими (теперь корректными) гарантиями; явные честные границы (best-effort, не jail).

## [2.84.0] — 2026-07-17 — Qualification: точнее ловим регрессии, крепче детект, пакет сценариев

Завершающая фаза аудит-плана. Две проверяемых офлайн доработки движка + готовый пакет живой
квалификации (сам прогон — на машине пользователя с моделью).

### Changed
- **baseline-diff по СТРУКТУРНЫМ id падений** (`_failure_ids`). Раньше «починил один тест, сломал
  другой» проходило как «нет регрессии» (число падений 1→1). Теперь появление **нового** id
  падения = регрессия, даже без роста числа. Best-effort по pytest/jest/vitest/tsc/rust; неизвестный
  формат → fallback на счётчик (v2.77).
- **Детектор стека крепче.** Предпочитает wrapper'ы `./gradlew`/`./mvnw` глобальным бинарям (иначе
  `exit 127` без установленного gradle/mvn). Монорепо-маркеры: `pnpm-workspace.yaml`, `lerna.json`,
  `turbo.json`, `nx.json`, несколько `package.json` в `apps/`/`packages/`. При монорепо — честный
  `undetermined`-note (корневые команды могут не покрывать все пакеты) + `monorepo_reason` в профиле.

### Added
- **`qualification/scenarios.yaml`** — 5 канонических live-сценариев (greenfield, fix-true-green,
  regression-guard, engineering-review, containment) с флагами и **критериями приёмки** (какие поля
  отчёта доказывают успех) + матрица ОС/стеков.
- **`docs/qualification-runbook.md`** — как прогнать квалификацию на реальном child: env, команды на
  сценарий, чтение JSON-отчёта, матрица, честная граница.
- **`validation/validate_qualification.py`** — согласованность пакета (форма сценариев, `task_type`
  из workflows, известные флаги, матрица). В AGENTS.md checklist и `package-quality.yml`.
- **`managed_set`** += `qualification/**/*` — пакет сценариев едет в child.

### Boundary (честно)
- Сам живой прогон 5 сценариев × матрица ОС/стеков требует машины пользователя с моделью и стеком
  (из cloud-сессии egress закрыт). Харнесс, сценарии, приёмка и runbook готовы; прогон — за
  пользователем.

## [2.83.0] — 2026-07-17 — Full RunPlan: постадийный независимый ревью (аудит v2.79, P0.4)

RunPlan-гейты ai-review больше не блокируют «просто потому что»: движок гоняет **независимого
ревьюера** (writer ≠ judge), который читает изменение и выносит структурный вердикт. Честно:
только то, что судья МОЖЕТ проверить — артефакт-гейты и human-approval остаются блокирующими.

### Added
- **Постадийный ревью в `execution_pipeline`** (`--review`). Для каждого ai-review гейта плана
  (code_review, ux_review, security-non-human, ...) без evidence движок запускает ОТДЕЛЬНЫЙ вызов
  модели под **read-only Policy** — судья читает ревизию и возвращает `reviewer-result`
  (валидируется `validate_reviewer_result`). pass закрывает `required_evidence` (дисциплина
  ai-review), fail блокирует. Трейс — в `report.reviews`.
- **`tool_loop.make_reviewer_proposer` / `run_review`** — механика независимого ревью: read-only
  цикл, судья может только читать (write/shell брокер отклоняет), обязан вернуть структурный
  вердикт. Полностью тестируется offline scripted-ревьюером.
- **Флаг `--review`** в `ai-ops run` и `qual_run`; независимый ревьюер — отдельный экземпляр
  провайдера (writer ≠ judge на уровне вызова).

### Boundary (честно)
- **Детерминированные артефакт-гейты** (requirements/specification/plan_readiness) ревьюер словом
  НЕ закрывает — им нужны артефакты + запускаемые валидаторы (product-authoring, отдельная фаза);
  без артефактов они честно блокируют.
- **human-approval** (security при privileged/destructive/secret_boundary) требует человека.
- Та же базовая модель как судья — более слабая независимость, чем другой судья/человек; capability
  (read-only) и роль (отдельный вызов) разделены, но полная независимость сильнее.

## [2.82.0] — 2026-07-17 — Standalone Child (аудит v2.79, P0.3)

Движок теперь **самодостаточен внутри child**: `ai-ops run` работает БЕЗ внешнего `git clone`
parent-кита. И это **доказано прогоном**, а не задекларировано.

### Changed
- **`update_policy.managed_set`** += `tools/**/*.py`, `validation/**/*.py`, `config/**/*`,
  `VERSION`. Движок (инструменты + валидаторы + их данные) едет в `.ai/managed/`; PKG движка
  резолвится как `Path(__file__).parents[1]` == `.ai/managed/`, а `registry`/`quality`/`security`
  уже там. Пакетный фильтр как обычно: без выбора `packages` (дефолт) ставится всё; выбор без
  `ai-ops-execution` — осознанный opt-out (движок не ставится).
- **`ai-ops doctor`** сообщает наличие движка в `.ai/managed`.
- **`worktree` прогресс → stderr.** `WORKTREE:`/`ОШИБКА` больше не пишутся в stdout —
  `ai-ops run --json` выдаёт чистый машиночитаемый JSON (данные на stdout, прогресс на stderr).

### Added
- **`validation/validate_standalone_engine.py`** — ДОКАЗЫВАЕТ самодостаточность: строит managed
  из `managed_set` и гоняет движок **отдельным процессом** из `.ai/managed/tools/ai_ops_run.py`
  с чистым окружением (parent не на `PYTHONPATH`, cwd = временный child). Scripted-proposer пишет
  файл → движок коммитит на `ai-ops/*`, собирает evidence на точном SHA, `ready_for_pr=True`.
  Плюс completeness-проверка рантайм-замыкания: пропажа файла движка из `managed_set` роняет тест.
  Включён в AGENTS.md checklist и `package-quality.yml`.
- **`ai-ops-execution/package.yaml`** += `tools/execution_pipeline.py` (был неназначенным).

### Boundary (честно)
- child-CI валидатор (`ai-ops-validate.yml`) по-прежнему клонирует parent по тегу — это отдельный
  контур (пин версии для проверки установки), не путь исполнения движка. Standalone здесь — про
  `ai-ops run`, не про CI-валидатор.

## [2.81.0] — 2026-07-17 — Containment (аудит v2.79, P0.2)

Модель больше **не доставляет сама и не гоняет произвольный shell**. Это enforceable-подмножество
изоляции на уровне брокера — **честно НЕ полный jail**: полная ФС/сеть/ресурс-изоляция остаётся
задачей контейнерного runtime, и это прямо объявлено в отчёте и в правилах.

### Added
- **`tool_broker.Policy` — контроль изоляции.** Новые параметры: `block_push` (git push из
  tool-loop запрещён — доставку делает только движок через `pr_open`), `shell_mode`
  (`unrestricted` | `allowlist` | `off`), `shell_allowlist`, `allow_network` (денай частых сетевых
  бинарников `curl`/`wget`/`nc`/`ssh`/…). Первый токен команды берётся с учётом `VAR=val`-префиксов.
- **`tool_broker.sandbox_policy()`** — готовый усиленный профиль для недоверенной живой модели:
  shell по allowlist dev-инструментов (`SANDBOX_SHELL_ALLOWLIST`) + `block_push`.
- **Флаг `--sandbox`** в `ai-ops run` и `qual_run` — включает sandbox-профиль для прогона.
- **Блок `containment` в отчёте движка** — честная декларация действующей политики
  (`sandbox`, `shell_mode`, `block_push`, `allow_network` + note про контейнер).

### Changed
- **Дефолт движка теперь `block_push=True`.** Модель не может отправить незачтённую работу мимо
  гейтов; ветку/PR доставляет только доверенный delivery-слой. (Аддитивно: явная `policy=` уважается
  как есть; поведение вне движка не меняется.)
- **`qual_run --max-steps`** теперь реально прокидывается в раннер (был объявлен, но не применялся).
- **`rules/ai/ToolBrokerPolicy.md`** — правила 6–8 (block_push / shell_mode / allow_network),
  секция sandbox-профиля и честная граница «enforceable-подмножество ≠ контейнерный jail».
- **manifest** — P0.2 sandbox отмечен `done_v2_81`; `package_version` → 2.81.0.

## [2.80.0] — 2026-07-17 — Trust Correctness (ответ на внешний аудит v2.79)

Внешний аудит (~5/10) верно вскрыл класс проблем корректности доверия. Закрыты пять contained-
дефектов (код, проверяются селфтестами); sandbox/standalone/full-RunPlan честно оставлены
отдельными фазами (нужен контейнер/инфра).

### Fixed
- **P0.1 (самый острый — наш регресс): baseline-diff обходил ВСЕ блокирующие гейты.** Было
  `ready = base_ok and no_regressions` — без проверки `gates.blocked`. Задача с незакрытыми
  `security`/`code_review`/`requirements` могла стать `ready`. Теперь baseline-осведомлён **только**
  `implementation_verification`; **все прочие блокирующие гейты обязательны** (`other_blocking_unmet`).
  Ложный `ready_for_pr` устранён.
- **P0.4: `--open-pr` мог провалиться, а прогон = успех.** Разделены `ready_for_pr` и `delivery`;
  `overall_status=delivery-failed`, если PR запрошен, но не открыт; `exit_code` это учитывает.
- **P0.6: подготовка окружения могла загрязнить AI-коммит.** `npm ci`/baseline меняли tracked-файлы
  (lock/снапшоты), а `git add -A` их втягивал. Теперь tracked-изменения подготовки откатываются
  **до** работы модели; провал install → `prepare_ok=False` → не `ready`.
- **P0.3: повторный запуск мог снести предыдущую работу.** Guard: если на ветке `ai-ops/<feature>`
  есть коммиты не в HEAD и нет `--discard` → honest error (работа не теряется); `--discard` для
  явной перезаписи. qual-харнесс — disposable, discard по умолчанию.
- **Evidence/аудит:** в отчёт добавлены полный `gate_results` + `tested_revision` (раньше
  выбрасывались) — видно, чем закрыт каждый гейт и к какой ревизии.

### Added
- **`ai-ops run` / `qual_run`** — флаг `--discard`.

### Changed
- **manifest** — `execution_engine.external_audit_2026_07_17_v2_79` (fixed_v2_80 + честный
  remaining_backlog: P0.2 sandbox → v2.81, standalone → v2.82, full RunPlan → v2.83, квалификация
  → v2.84). `package_version` → 2.80.0.

## [2.79.0] — 2026-07-17

**Больше шагов tool-loop (reasoning-модели упирались в бюджет, не в потолок).** Трейс
`deepseek-reasoner` на fix-задаче: `applied=2`, но **8 shell + 5 read**, и обе записи пришлись на
шаги 17 и 19 — модель честно исследовала (shell) и правила, но уткнулась в `max_steps=20` прямо
перед завершением. Это тесный бюджет, а не потолок модели.

### Changed
- **`tools/execution_pipeline.py`** — дефолт `max_steps` 20 → **40** (reasoning-моделям нужен
  запас на цикл понять→починить→проверить→done; read-cap не даёт флудить чтением).
- **`ai-ops run` / `qual_run`** — флаг **`--max-steps`** (по умолчанию 40) для ручной подстройки.
- **manifest** — `package_version` → 2.79.0.

## [2.78.0] — 2026-07-17

**Свежий worktree на каждый прогон (не грязное переиспользование).** Повторный запуск того же
feature падал `ОШИБКА: каталог worktree уже есть` ЛИБО молча переиспользовал worktree прошлого
прогона — то есть новый прогон шёл поверх грязного состояния (нечистый baseline). Ещё один
finding живой обкатки.

### Fixed
- **`tools/execution_pipeline.py`** — при `isolate=True`, если worktree/ветка `ai-ops/<wid>` уже
  есть от прошлого прогона, движок теперь **удаляет их и создаёт worktree заново от HEAD** —
  каждый прогон стартует с чистой базы. Повторный прогон одного feature больше не падает и не
  тянет прежнее состояние.

### Changed
- **manifest** — `package_version` → 2.78.0.

## [2.77.0] — 2026-07-17

**КРИТИЧНО: baseline-diff пропускал ухудшение внутри уже-красной проверки (ложный зелёный).**
Живой прогон fix-задачи: read-cap (v2.76) сработал — DeepSeek стал писать (5 правок), — но фикс
был НЕВЕРНЫМ: 1 падавший тест превратился в 8. При этом `test`-check как был `fail`, так и
остался, и baseline-diff на уровне check выдал `regressions=[], ready=True` — **ложный PASS
поверх ухудшения**. Это дефект критерия, пойманный именно живой обкаткой (не тестами).

### Fixed
- **`tools/execution_pipeline.py` `_diff_checks`** — регрессия внутри уже-красной проверки:
  `_failure_signal` парсит число `failed`/`errors` из вывода; если при `fail→fail` оно ВЫРОСЛО
  (1→8) — это регрессия, даже если статус check не изменился. Ложный зелёный на ухудшении
  устранён. (Best-effort: строка-итог должна попасть в `output_tail`.)

### Added
- **`--require-fix`** (`ai-ops run`, `qual_run`) — для fix-задач `ready_for_pr` требует, чтобы
  правка РЕАЛЬНО починила падавшую проверку (`fixed` непустой), а не только «не сломала».
  `ready_criterion` → `no-regressions+require-fix`.
- **`qual_run` сводка** теперь показывает `fixed=[...]`/`regressions=[...]` по каждой задаче —
  «пустой» PASS (ничего не починил) виден сразу.

### Changed
- **manifest** — `package_version` → 2.77.0.

## [2.76.0] — 2026-07-17

**Анти-флейл петли: read-cap.** Трейс (v2.75) вскрыл корень провала fix-задач: DeepSeek делал
**20 чтений подряд, 0 записей** — «читал по кругу», не решаясь писать. Не предел «понять код», а
зацикливание.

### Fixed
- **`tools/tool_loop.py`** — после `max_consecutive_reads=5` чтений подряд без записи следующее
  `read` **отклоняется на уровне петли** с требованием вернуть `write`/`done` (счётчик
  сбрасывается на любом не-read действии). Нормальный поток `read→write→done` не задет. Плюс
  усилен промпт `make_model_proposer`: «читай 1-2 файла, не перечитывай уже прочитанное, сразу
  вноси правку».

### Changed
- **manifest** — `execution_engine.live_qual_green_2026_07_17.fix_task_flail_v2_76`.
  `package_version` → 2.76.0.

## [2.75.0] — 2026-07-17

**Наблюдаемость петли: трейс в отчёте.** На fix-задаче петля упиралась в `max_steps`, но по
отчёту нельзя было понять ПОЧЕМУ (модель флудит read? denied? bad-json?). Отчёт движка теперь
включает компактный трейс шагов и причины denied.

### Added
- **`tools/execution_pipeline.py`** — `loop.transcript` (шаг/op/allowed/ok/done/reason, до 40) и
  `loop.denied_reasons` в отчёте. Диагностика живого прогона без догадок.

### Changed
- **manifest** — `package_version` → 2.75.0.

## [2.74.0] — 2026-07-17

**Первый ЗЕЛЁНЫЙ qual-прогон на реальном child + два finding'а с задач-починок.** README-задача
на ii-sreda (DeepSeek, baseline-diff) дала `[PASS] 1/1, ready_for_pr=True` — полный путь
`detect → tool-loop (живая модель) → npm ci → commit в worktree → evidence на точном SHA →
baseline-diff` подтверждён живьём. Две задачи-починки вскрыли ещё два дефекта.

### Fixed
- **`tools/orchestrator.py`** — `_http_post_json` ретраит **транзиентные** сетевые сбои
  (SSL-handshake timeout оборвал задачу) и `5xx`/`429` с бэкоффом (1s/2s/4s); `4xx` (кроме 429)
  не ретраится (это ошибка запроса, не транзиент).
- **`tools/execution_pipeline.py`** — на fix-задаче модель крутилась до `max_steps` с 0 правок,
  потому что не знала, ЧТО чинить. Теперь в контекст tool-loop подаётся **фактический вывод
  падающих проверок базы** (`_baseline_failure_summary`: команда + exit + stderr/stdout) — модель
  видит реальную ошибку (напр. «expected 'Вчера' got 'Сегодня'») и может её таргетить.

### Changed
- **manifest** — `execution_engine.live_qual_green_2026_07_17` (первый зелёный прогон + findings
  задач-починок + честный остаток: слабая модель может не сходиться даже с выводом ошибок).
  `package_version` → 2.74.0.

## [2.73.0] — 2026-07-17

**Устойчивость к битому JSON модели + кросс-платформенность (Windows).** Два независимых
finding'а: живой прогон споткнулся о невалидный JSON от DeepSeek, а внешний отчёт установки на
Windows 11 вскрыл непереносимость путей и падение вывода в консоли.

### Fixed
- **`tools/tool_loop.py`** — живая модель недетерминирована: иногда отдаёт невалидный JSON, и
  ОДНА кривая реплика обрывала весь прогон (`bad-proposal: bad-json`). Теперь до
  `max_bad_proposals=3` подряд **корректирующих переспросов** (модели показывают её ошибку и
  просят чистый JSON); счётчик сбрасывается на любом валидном действии. Прогон переживает
  случайные срывы парсинга.
- **Кросс-платформенность путей (Windows ↔ POSIX)** — 18 сайтов `str(Path.relative_to())`
  (давали `a\b` на Windows) → `.relative_to().as_posix()` в `installer/ai_ops.py`,
  `validation/*` (registry/boundaries/freshness/stale-gates/checksums), `tools/*`
  (generate_runtime/orchestrator/execution_pipeline). Устранён ложный провал валидатора реестра
  и ложный дрейф managed-слоя. `detect_drift` нормализует старые `\`-ключи `.checksums.json` при
  чтении — миграция уже установленных child-репо без ложного дрейфа (sha256 не меняются).
- **Кодировка вывода на Windows-консоли** — `installer/ai_ops.py` печатал рамки/галочки/кириллицу
  → `UnicodeEncodeError` на cp1251/cp866. Добавлен `_force_utf8_stdio()` (reconfigure stdout/stderr
  в UTF-8, `errors=replace`) в начале `main()`.

### Changed
- **selftest `installer/ai_ops.py`** — ассерты кросс-ОС: ключи checksums только `/`;
  Windows-стиль `\`-ключей не даёт ложного дрейфа.
- **manifest** — `execution_engine.self_audit_2026_07_17.fixed_v2_73` + `cross_platform_2026_07_17`.
  `package_version` → 2.73.0.

## [2.72.0] — 2026-07-17

**Третий finding живого прогона: baseline-diff (регрессии vs пред-существующие провалы).** С
установленными зависимостями движок прогнал реальные build/typecheck/test на ii-sreda — и они
красные **сами по себе** (коллизия регистра `Markdown.ts`/`markdown.ts` рушит build+typecheck;
1 из 532 тестов — `recentTimeGroup` про даты). Движок честно не дал `ready_for_pr` поверх
красного репо. Но требовать «всё зелёное» от правки в уже-красном репозитории неверно — правку
судят по тому, не внесла ли она **новых** провалов.

### Added
- **`tools/execution_pipeline.py`** — `baseline_diff` (param): прогон проверок на БАЗЕ до правок
  модели, затем `_diff_checks` вычисляет `regressions` (было pass → стало fail) и `fixed`
  (fail → pass). Критерий `ready_for_pr` в этом режиме — **no-regressions** (пред-существующие
  красные проверки репо не блокируют; чинятся отдельно). Отчёт: `baseline` (статусы на базе +
  regressions/fixed/no_regressions), `ready_criterion` (`all-green` | `no-regressions`).
- **`tools/ai_ops_run.py`** — флаг `--baseline-diff`.
- **`tools/qual_run.py`** — baseline-diff **по умолчанию** (реальные репо редко all-green);
  `--strict-green` возвращает критерий «всё зелёное». `evaluate_report` теперь доверяет
  вердикту движка `ready_for_pr` (учитывает критерий) и собирает диагностику при не-готовности.

### Changed
- **manifest** — `self_audit_2026_07_17.live_qual_run_2026_07_17.fixed_v2_72` +
  `qualification_status` (движок подтверждён end-to-end на реальном child; верификация настоящая —
  вскрыла 3 реальных бага ii-sreda). `package_version` → 2.72.0.

## [2.71.0] — 2026-07-17

**Второй finding живого прогона: установка зависимостей в изолированном worktree.** На QUICK-классе
движок дошёл до реального прогона build/lint/test на ii-sreda, но они упали `exit 127`
(`vite/tsc/vitest: command not found`) — в свежем git-worktree нет `node_modules`. Движок честно
не засчитал (не подделал pass), но канонический путь физически не мог верифицироваться без
установки зависимостей.

### Added
- **`tools/project_detector.py`** — поле `install_command` для стеков: node → `npm ci`
  (с lockfile) / `npm install`, yarn/pnpm аналогично; python → `poetry install` / `uv sync` /
  `pip install -r requirements.txt` / `pip install -e .`.
- **`tools/execution_pipeline.py`** — шаг подготовки `_install_dependencies`: перед сбором
  evidence ставит зависимости стека через Broker **только в изолированном worktree** (основное
  дерево пользователя не трогаем — `npm ci` там снёс бы `node_modules`). Результат — в отчёте
  (`prepare`). `node_modules` в `.gitignore` → дерево остаётся чистым для evidence-на-SHA.
  Параметр `install_deps=True` (по умолчанию вкл. при `isolate`).

### Changed
- **manifest** — `self_audit_2026_07_17.live_qual_run_2026_07_17.fixed_v2_71`.
  `package_version` → 2.71.0.

## [2.70.0] — 2026-07-17

**Первый живой прогон движка на реальном child (ii-sreda, DeepSeek) — и честный класс задачи.**
После фикса 3.9 движок реально отработал на ii-sreda: создал изолированный worktree, прошёл
петлю. Для ENGINEERING-класса гейты честно заблокировали (`requirements/specification/
plan_readiness/code_review` без evidence — движок не подделывает pass). Это подтверждает
backlog P0.4 (постадийное исполнение RunPlan ещё не реализовано), а не баг.

### Fixed
- **`tools/qual_run.py`** — харнесс по умолчанию завышал класс задачи до `ENGINEERING`, из-за
  чего любая задача упиралась в гейты, для которых pipeline пока не производит evidence. Дефолт
  → **`QUICK`** (реально поддерживаемый сегодня класс: tool-loop + `intake` +
  `implementation_verification`) + флаг **`--task-type`** для осознанного выбора класса.

### Changed
- **manifest** — `execution_engine.self_audit_2026_07_17.live_qual_run_2026_07_17` (результат
  первого живого прогона + honest_boundary: квалифицируется QUICK-путь; полный ENGINEERING/
  PRODUCT — до P0.4). `package_version` → 2.70.0.

## [2.69.0] — 2026-07-17

**Portability — первый реальный finding квалификационного харнесса (Python 3.9).** Попытка
живого qual-прогона с Mac упала ещё до вызова модели: `python3` из macOS CommandLineTools —
это 3.9, а два модуля использовали `X | None` (PEP 604) в аннотациях без future-import, из-за
чего весь движок падал `TypeError` при импорте. То есть харнесс сработал по назначению —
поймал портируемость-дефект на реальной машине.

### Fixed
- **`tools/generate_artifacts.py`, `tools/run_report.py`** — добавлен `from __future__ import
  annotations` (PEP 563: аннотации становятся ленивыми, `str | None` не вычисляется при
  импорте). Движок (`ai_ops_run → workitem → run_report → generate_artifacts`) теперь грузится
  на Python 3.9.

### Added
- **`validation/validate_python_compat.py`** — AST-guard: union-аннотация `X | Y` без
  `from __future__ import annotations` = ERROR в CI. Класс «падает на <3.10» больше не пройдёт.
  Offline `--selftest`. Wired в AGENTS.md + CI (`package-quality.yml`).

### Changed
- **README** — документированный floor Python 3.10+ → **3.9+** (честно: дефолтный `python3`
  macOS подходит), со ссылкой на compat-валидатор.
- **manifest** — `execution_engine.self_audit_2026_07_17.fixed_v2_69`;
  `knowledge_integrity.python_compat_validator`. `package_version` → 2.69.0.

## [2.68.0] — 2026-07-17

**Квалификационный харнесс — `tools/qual_run.py`.** Инструмент для последнего реального пункта
`p0_backlog`: прогнать 3–5 обычных задач через собранный движок на child-репо с тулчейном и
получить объективный вердикт «дошло до проверяемого draft PR или нет».

### Added
- **`tools/qual_run.py`** — гоняет список задач через `ai-ops run --engine pipeline --execute`,
  складывает JSON-отчёт на каждую задачу + `summary.json`, печатает сводку pass/fail по
  критериям квалификации (`status≠error`, `loop.stopped=done`, `denied=0`, `commit` на точном
  SHA, `gates.blocked=false`, `ready_for_pr=true`). Ключ/токен — только из env; в отчёты не
  попадают (`scrub_env`). Код возврата 0/1/2 (успех/провал/конфиг). Offline `--selftest`
  проверяет логику вердикта, серию и запись отчётов на mock-раннере без сети. Русские задачи
  транслитерируются в уникальные slug (workitem_id/имя отчёта не коллизируют).
- **`examples/qual-tasks.example.txt`** — шаблон списка задач.

### Changed
- **AGENTS.md + CI (`package-quality.yml`)** — добавлен `qual_run.py --selftest`.
- **manifest** — `p0_backlog`: пункт квалификации уточнён (харнесс готов; остаётся живой прогон
  с Mac). `package_version` → 2.68.0.

## [2.67.0] — 2026-07-17

**Contract Integrity — собственный аудит на соответствие видению.** После закрытия внешних
аудитов прогнан свой аудит `VISION.md`/`ROADMAP.md` vs код (агент-ревьюер + ручная
верификация). Найдены и исправлены orphan-гейт и доковый дрифт; введён guard, чтобы этот
класс не повторился. Решение — `ep-2026-07-17-vision-audit`.

### Fixed
- **P0 orphan-гейт (`quality/gates.yaml`, `registry/workflows.yaml`)** — `spec_synchronization`
  (один из 8 MVP-blocking) и `archive_readiness` были *применимы* по `applicability`, но не
  запускались НИ в одном workflow/треке — гарантия «8 MVP-blocking» была ложной (реально 7/8).
  Честная модель: оба — детерминированные OpenSpec-гейты, enforced OpenSpec CLI +
  `validation/validate_openspec_change.py` в CI. Зафиксировано полем `gate.enforced_by:
  openspec-ci-guard`.
- **orphan-guard (`validation/validate_workflow_gates.py`)** — валидатор стал **track-aware**
  (перестал сыпать ложными WARN про гейты, что даёт RunPlan-трек: ux_review/ai_eval/…) и
  **enforced_by-aware**; недостижимый MVP-blocking гейт теперь **ERROR** (был WARN) — дрифт
  «8 blocking, а реально 7» больше не пройдёт CI. `gate.applicability` на несуществующий
  workflow — тоже ERROR (ловит класс `security → INCIDENT`).
- **P1 `intake_completeness` → ENGINEERING** — per-run гейт реально пропускался в ENGINEERING
  (QUICK/PRODUCT/VISUAL/… его имели). Добавлен.
- **P1 счётчик gates** — `ROADMAP.md` говорил «26 gates», фактически 28. Исправлено и
  **запиннено** claim'ами `gate-count`(28)/`mvp-blocking-count`(8) — для этого в
  `validate_claims.py` добавлен тип claim **`count`** (регексом считает и сверяет с ожидаемым;
  дрифт числа теперь виден в CI).
- **P2 `security.applicability`** ссылалась на несуществующий workflow `INCIDENT` — убран
  (инциденты идут через CRITICAL).
- **P2 `documentation_drift`** развёрнут из one-liner в полную форму (`stage`/`purpose`) как у
  соседних гейтов.

### Changed
- **manifest** — `execution_engine.self_audit_2026_07_17` (fixed_v2_67 + kept_deliberately +
  clean_areas); `quality_gates.enforced_by_ci_guard` и `count_pinned_by_claims`.
  `package_version` → 2.67.0.
- **decisions** — эпизод `ep-2026-07-17-vision-audit`: OpenSpec-гейты не пихаем в per-task
  quality_gates; phase-3 non-blocking гейты оставлены non-blocking до стабильного зелёного на
  ≥2 child (критерий промоушена).

## [2.66.0] — 2026-07-16

**Trust Boundary — contained-фиксы следующего аудита (P0.1, P0.2-contained, P0.5, P1.1).**
Аудит указал на реальные дефекты канонического пути. Исправлены те, что закрываются в коде;
overclaim'ы честно понижены; остаток (полный jail, standalone-движок в child, постадийный
RunPlan, квалификация на реальных задачах) чётко разложен в `p0_backlog`.

### Fixed
- **P0.1 контроллер (`tools/ai_ops_run.py`)** — `print_human` ветвится по `kind`: pipeline-отчёт
  (loop/commit/checks/gates/ready_for_pr) больше НЕ роняет `KeyError` на ключах controller-отчёта.
  CLI получил `--engine pipeline`, `--model`, `--open-pr`; добавлен `exit_code()` — `2` при
  `status=error`, `1` при `not ready_for_pr`/`blocked`, `0` при ready/planned — CI/скрипты видят
  провал, а не считают любой прогон успешным.
- **P0.2 shell trust boundary (contained, `tools/tool_broker.py`)** — `subprocess.run(timeout=…)`
  (`SHELL_TIMEOUT_DEFAULT=300`, `action.timeout` переопределяет): shell не висит вечно. Честный
  module-comment: shell — **НЕ** security boundary (`write_scope`/`protected_paths` только для
  read/write; полный jail = контейнер, в backlog).
- **P0.5 evidence ↔ ревизия (`execution_pipeline.py`, `evidence_collector.py`, `tool_broker._revision`)**
  — полный SHA (не `--short`); `git status --porcelain` до/после проверок (`tree_clean_*`);
  `ready_for_pr` ТРЕБУЕТ реального коммита + evidence на точном SHA + чистого дерева. Dry-run
  (`commit=False`) теперь НИКОГДА не `ready_for_pr` — нет ревизии для draft PR.
- **P1.1 path safety (`run_plan.py`, `worktree.py`)** — `validate_workitem_id` (slug
  `^[a-z0-9][a-z0-9._-]{0,63}$`, без `../`, `/`, `\`, абсолютных) в `build_plan`; `worktree.add/remove`
  — `_safe_target` с containment строго внутри `<root>/<wt_dir>` (traversal `../` и абсолютные пути
  отвергнуты, файл вне каталога worktree не создаётся).

### Changed
- **manifest** — `execution_audit_2026_07_16.fixed_v2_66`; `honest_status` и `engine_status`
  понижены до честной формулировки аудита («собран + подтверждён на ограниченном QUICK-сценарии;
  канонический путь для реальных child ещё не готов»); `p0_backlog` переразложен (P0.2-full/P0.3/
  P0.4/P1.2/P1.4 + живой PR + квалификация). `package_version` → 2.66.0.

## [2.65.0] — 2026-07-16

**README синхронизирован с реальностью движка (drift-fix).** В v2.53 README честно говорил
«единый движок НЕ собран»; за v2.54–2.64 движок собрали, подключили и подтвердили живьём —
и README устарел в обратную сторону. Приведён в соответствие с кодом.

### Changed
- **README.md** — «компоненты исполнения / движок не готов» → «единый execution-движок собран,
  подключён (`ai-ops run --engine pipeline`) и подтверждён на живой модели end-to-end до
  `ready_for_pr`»; сохранены честные границы (эмпирический остаток: живой PR + 3 реальные
  задачи; shell не полная песочница; пустой репо освобождает проверки). `package_version` → 2.65.0.

## [2.64.0] — 2026-07-16

**Движок подтверждён ЖИВЬЁМ end-to-end — до `ready_for_pr: True`.** Полный единый pipeline
прогнан на реальном DeepSeek (`openai-compatible`) с мака: `detect → tool-loop (живая модель) →
commit в изолированном worktree → evidence на точном SHA → RunPlan-гейты → ready_for_pr`.
Результат: `loop.stopped=done, applied=2, denied=0, isolation=.ai/worktrees/slugify,
commit fc87de5 on_exact_sha=True, gates.blocked=False, ready_for_pr=True`. Это закрывает
центральную цель эпика аудита («собрать само исполнение») — собрано, подключено к контроллеру
и подтверждено на живой модели.

### Changed
- **manifest** — `execution_audit_2026_07_16.live_pipeline_verified_v2_64` (evidence прогона +
  честная оговорка); `engine_status: ПОДТВЕРЖДЁН ЖИВЬЁМ END-TO-END`; из p0_backlog убран
  «живой предложитель на pipeline» (закрыт этим прогоном); `package_version` → 2.64.0.

**Честная оговорка:** репо прогона был пустой (без тулчейна) → все build/lint/typecheck/tests
ОСВОБОЖДЕНЫ умным ослаблением (штатное поведение). Подтверждена МЕХАНИКА всей цепи и сходимость
к `ready_for_pr`, но НЕ прохождение реальных build/lint/test — это эмпирика на репо С тулчейном
(остаток p0_backlog: живой draft PR + 3 реальные задачи против обычного Claude Code).

## [2.63.0] — 2026-07-16

**Adversarial-review всего диффа аудита -> 6 подтверждённых дефектов исправлены.** Прогнал
workflow-ревью диапазона `efeab38..HEAD` (3 ревьюера: security/correctness/honesty, каждую
находку проверял отдельный скептик по реальному коду). Из 10 заявленных — 6 подтверждены и
закрыты (в т.ч. security-дыра, которую внёс я сам).

### Fixed (security)
- **tools/tool_broker.py — scrub_env: denylist → ALLOWLIST.** Прежний фильтр по именам пропускал
  целые классы секретов (голый `_KEY`: STRIPE_KEY/GEMINI_KEY/…; `DATABASE_URL`/DSN/JWT/PAT) —
  они доходили до shell-команды, предложенной моделью. Теперь в подпроцесс идёт ТОЛЬКО
  allowlist безопасного env + явный `passthrough`; любой секрет режется. Побочно: не-секретный
  GitHub-контекст (GITHUB_SHA/REF/…) сохранён, токены — нет.

### Fixed (correctness)
- **tools/evidence_collector.py** — pytest exit 5 в полиглот-репо ронял весь test-check
  (`all(...)`); теперь по-руново: реальный проходящий тест рядом с pytest-exit5 засчитывается.
- **tools/execution_pipeline.py** — `isolate=True` при сбое `worktree.add` МОЛЧА уходил в
  основное дерево (правки+коммит в main вопреки изоляции); теперь честная ошибка, прогон остановлен.
- **tools/ai_ops_run.py** — `engine="pipeline"` (`ai-ops run --engine pipeline`): собранный движок
  подключён к контроллеру (был доступен только из selftest).
- **tools/pr_open.py** — мусор `type('e',(),{})` в сообщении об ошибке push → `rc={code}`.

### Fixed (honesty)
- **decisions/CHANGELOG/manifest** — «профиль подтверждает человек» уточнено: освобождение
  опирается на ДЕТЕКТИРОВАННЫЙ (draft) профиль (детерминизм манифестов, не слово модели);
  подтверждение человеком рекомендуется, но кодом pipeline не enforced.
- **manifest** — `engine_status`: «собрана И подключена к контроллеру» (не только selftest);
  `adversarial_review_v2_63` (журнал ревью+фиксов); `package_version` → 2.63.0.

**Замечание:** shell FS/сеть-изоляция (чтение/запись вне репо самой командой) остаётся известным
ограничением (нужен контейнер) — в p0_backlog, не имитируется.

## [2.62.0] — 2026-07-16

**P0-эпик, срезы 9–10: worktree-изоляция + механизм draft PR — цепь движка замкнута.** Теперь
единый pipeline проходит весь путь: `[worktree] → detect → tool-loop → commit на ветке →
evidence на SHA → гейты → [draft PR]`.

### Added
- **tools/pr_open.py** (+ selftest) — `open_draft_pr(root, branch, title, body, base)`: push
  ветки + POST в GitHub REST (`/pulls`, `draft:true`), токен ТОЛЬКО из env; нет токена/remote →
  honest `unavailable` (PR не имитируется). Чистый `_pr_payload` тестируется offline.
- **tools/execution_pipeline.py** — `isolate=True`: весь прогон в `.ai/worktrees/<id>` на ветке
  `ai-ops/<id>` (основное дерево не тронуто); `open_pr=True`: вызывает механизм draft PR при
  `ready_for_pr`. Отчёт: `isolation.worktree`, `draft_pr`. Selftest: изоляция (файл в worktree,
  не в корне), open_pr без токена → unavailable.
- **CI + AGENTS.md + FILE_INDEX** — шаг `tools/pr_open.py --selftest`.

### Changed
- **manifest** — `fixed_v2_62`; `engine_status: ПОЛНАЯ цепочка собрана`; p0_backlog теперь =
  только эмпирический остаток (живой предложитель, живой PR, 3 реальные задачи); `package_version` → 2.62.0.

**Честная граница:** механизмы worktree/commit/evidence-на-SHA/draft-PR — код-полны и
offline-проверены; сам живой PR и «3 реальные задачи против Claude Code» — эмпирическая
обкатка на стороне child (нужен токен/egress), не имитируется.

## [2.61.0] — 2026-07-16

**P0-эпик, срез 8: «умное ослабление» implementation_verification.** Требование ВСЕХ четырёх
проверок (build+lint+typecheck+tests) делало гейт недостижимым для репо без линтера/тайпчекера —
ложный контроль, приучающий обходить гейты (предупреждение аудитора). Теперь гейт освобождает
проверки, для которых инструмента нет в ПОДТВЕРЖДЁННОМ стеке — честно и с записью.

### Changed
- **tools/evidence_collector.py** — возвращает `not_applicable` (флаги без команды в стеке) и
  `tests_absent`.
- **tools/gate_executor.py** — `evaluate(..., not_applicable=...)` / `evaluate_gate`: флаг из
  not_applicable считается покрытым ПО ОСВОБОЖДЕНИЮ и ЗАПИСЫВАЕТСЯ в `warnings` («освобождено:
  нет инструмента в стеке») — не фабрикуется pass. Объявленная-но-упавшая проверка блокирует.
- **tools/execution_pipeline.py** — `run_pipeline(..., allow_missing_tests=True)`:
  build/lint/typecheck освобождаются автоматически; tests — по умолчанию тоже + громкий
  `tests_warn`; `allow_missing_tests=False` → отсутствие тестов блокирует. Отчёт: `exemptions`, `tests_warn`.
- **decisions/registry.yaml** — `ep-2026-07-16-smart-loosening` (осознанное послабление планки,
  two-way, с защитами от халявы); **manifest** `fixed_v2_61`; `package_version` → 2.61.0.

**Защиты от халявы:** освобождается только то, что ДЕТЕРМИНИРОВАННО отсутствует в манифестах
стека (project_detector, не слово модели); освобождение видно в warnings; объявленная проверка
не освобождается. Честно: в offline-pipeline профиль детектированный (draft), подтверждение
человеком рекомендуется, но кодом не enforced (adversarial-review finding).

## [2.60.0] — 2026-07-16

**P0-эпик, срез 7: ЖИВОЙ прогон движка подтверждён end-to-end + 2 находки прогона.** Первый
живой прогон единого execution-pipeline на DeepSeek (`openai-compatible`) в ии-среде: реальная
модель провела `detect → правки → commit на ветке ai-ops/<id> → evidence на ТОЧНОМ SHA`.
`loop.stopped=done, applied_writes=1, denied=0, evidence_on_exact_sha=True`. Движок НЕ соврал:
гейты честно заблокировали (`ready_for_pr=False`), потому что нет тестов и intake-evidence.

### Changed (по находкам живого прогона)
- **tools/execution_pipeline.py** — `_intake_evidence(signals)`: `intake_completeness`
  закрывается evidence из сигналов (классификация task_type/size/risk уже произошла — это
  реальный evidence, не фабрикация).
- **tools/evidence_collector.py** — pytest exit 5 («нет собранных тестов») → `warn`, не `fail`:
  `tests_passed` не выдаётся (тестов не было), но и hard-fail не ставится (нечему падать).
- **manifest** — `execution_audit_2026_07_16.live_verified_v2_60` (evidence прогона) +
  `engine_status: spine+commit/reverify ПОДТВЕРЖДЁН ЖИВЬЁМ`; `package_version` → 2.60.0.

**Итог:** ядро P0-эпика («собрать само исполнение») собрано И подтверждено на живой модели.
Осталось (нужен live/GitHub, не offline): открытие draft PR, worktree-изоляция прогона,
установимый CLI с движком в child, проверка на 3 реальных задачах.

## [2.59.0] — 2026-07-16

**P0-эпик, срез 6: commit + reverify evidence на точном SHA.** Аудит: evidence бился о
pre-change HEAD, а тесты шли по грязному дереву — «revision есть, но не идентифицирует
проверенное состояние». Теперь pipeline коммитит и собирает evidence на зафиксированном SHA.

### Changed
- **tools/execution_pipeline.py** — `run_pipeline(..., commit=True)`: применённые изменения
  коммитятся на рабочей ветке `ai-ops/<workitem>` (НЕ в main), затем evidence собирается на
  чистом дереве -> `commit.evidence_on_exact_sha`. `ready_for_pr` теперь требует совпадения
  ревизии evidence с зафиксированным SHA. Selftest: коммит на ветке, evidence на точном SHA,
  main не тронут.
- **manifest** — `fixed_v2_59`; пункт про evidence-на-SHA убран из p0_backlog; пункт про
  единый pipeline уточнён (осталось live: draft PR, живой предложитель, worktree-изоляция);
  `package_version` → 2.59.0.

**Осталось в P0 (нужен live/GitHub, НЕ offline):** открытие draft PR (GitHub API), живой
предложитель (swap провайдера), worktree-изоляция прогона, установимый CLI с движком в child,
проверка на 3 реальных задачах.

## [2.58.0] — 2026-07-16

**P0-эпик, срез 5: единый execution-pipeline (spine) — сборка исполнения в ОДИН движок.**
Аудит: «перестать достраивать вокруг исполнения и собрать само исполнение». Компоненты (detect,
tool-loop, evidence collector, RunPlan-гейты) теперь соединены в одну цепочку, а не живут порознь.

### Added
- **tools/execution_pipeline.py** (+ selftest) — `run_pipeline(task, signals, root, proposer,
  policy, budget)`: detect стек → tool-loop (модель применяет изменения, Policy+Broker) →
  evidence collector (реальный прогон build/lint/test) → RunPlan-гейты (base+треки, с сигналами) →
  единый отчёт (`ready_for_pr`, `not_yet`). Offline-проверено mock-предложителем: петля до done,
  write применён/вне-scope отклонён, профиль определён, evidence собран, гейты оценены.
- **CI + AGENTS.md + FILE_INDEX** — шаг `execution_pipeline.py --selftest`.

### Changed
- **manifest** — `fixed_v2_58`; пункт p0_backlog про единый pipeline уточнён: SPINE готов,
  осталось git-worktree в прогоне + commit/reverify на точном SHA + draft PR + живой предложитель;
  `package_version` → 2.58.0.

**Честная граница:** spine доводит до «изменения применены + evidence собран + гейты оценены».
commit на точном SHA, reverify и открытие draft PR — ещё НЕ здесь (нужны git-commit шаг и живой
прогон); помечено в `not_yet`, не имитируется.

## [2.57.0] — 2026-07-16

**P0-эпик, срез 4: structured reviewer.json от оркестратора.** Аудит: gate_executor умел читать
`stage-*.reviewer.json` как источник истины, но оркестратор писал только `stage-*.md` — система
откатывалась на regex по прозе. Теперь judge-стадии дают структурный вердикт.

### Changed
- **tools/orchestrator.py** — judge-промпт (read-only) просит вернуть JSON reviewer-result
  (schema); `_write_reviewer_json` извлекает его, валидирует через `validate_reviewer_result.check`
  и пишет `stage-<sid>.reviewer.json` (иначе — фолбэк на markdown-regex, как раньше). Selftest:
  judge с JSON-вердиктом -> валидный reviewer.json создан.
- **manifest** — `fixed_v2_57`; пункт про отсутствие reviewer.json убран из p0_backlog;
  `package_version` → 2.57.0.

## [2.56.0] — 2026-07-16

**P0-эпик, срез 3 (security): shell-команды больше не видят секреты.** Аудит: `shell=True`
исполнял строку с ПОЛНЫМ окружением процесса — модель-предложитель могла прочитать любые
токены. Теперь Broker скрабит секреты из env перед запуском команды.

### Fixed (security)
- **tools/tool_broker.py** — `scrub_env()`: удаляет переменные-секреты по имени
  (TOKEN/SECRET/PASSWORD/API_KEY/PRIVATE_KEY/CREDENTIAL/… + префиксы AWS_/GH_/GITHUB_/OPENAI_/
  ANTHROPIC_/GIGACHAT_/SSH_/GPG_/PYPI_); функциональный env (PATH/HOME/NODE_ENV/LANG) сохранён,
  сборка/тесты не ломаются. `execute()` запускает shell/git с этим env. Selftest: секрет из
  env не виден команде (`TOK=[]`), PATH сохранён, `scrub_env` чистит по имени.

### Changed
- **manifest** — `fixed_v2_56`; shell-пункт p0_backlog уточнён: env-скраб сделан, полный
  FS/сеть-jail (контейнер) — честно НЕ сделано; `package_version` → 2.56.0.

**Честная граница:** это НЕ полный sandbox. Запрет чтения/записи вне worktree через shell,
отключение сети и allowlist команд требуют контейнера/namespace — заявлено в p0_backlog как
не сделанное, не имитируется.

## [2.55.0] — 2026-07-16

**P0-эпик, срез 2: условный human_approval больше не блокирует безусловно.** Аудит: гейт
`security` объявляет `human_approval: {required_when: [privileged, destructive,
secret_boundary_change]}`, но классификатор считал любой непустой human_approval безусловным —
и обычная ENGINEERING-задача ложно требовала ручного security-одобрения (это приучает обходить гейты).

### Changed
- **tools/gate_executor.py** — `_approval_required(gate, signals)` + `classify(gate, signals)`:
  условный approval становится human-approval ТОЛЬКО когда условие активно в сигналах задачи
  (`secret_boundary_change` ~ `security_surface_changed`). Без сигналов условный гейт → ai-review
  (required_evidence всё ещё требуется — security не исчезает, просто не требует человека зря).
  `evaluate`/`evaluate_gate` пробрасывают `signals`.
- **tools/orchestrator.py**, **tools/ai_ops_run.py** — прокидывают `signals` задачи в оценку.
- **manifest** — `fixed_v2_55`; пункт про условный approval убран из p0_backlog;
  `package_version` → 2.55.0.

Selftest: security без сигналов → не human-approval; при `security_surface_changed`/`destructive`
→ human-approval; безусловный `human_approval: true` → всегда human-approval.

## [2.54.0] — 2026-07-16

**P0-эпик, срез 1: RunPlan-гейты исполняются в прогоне.** Аудит назвал это «главной
интеграционной ошибкой»: `ai-ops run` планировал треки (VISUAL/ANALYTICS/SECURITY/DOCS) и их
гейты, но прогон оценивал только гейты `base_workflow`. Теперь прогон проверяет ТО, ЧТО
спланировал.

### Changed
- **tools/gate_executor.py** — `evaluate(..., gate_ids=None)`: при переданном списке оценивает
  именно его (агрегированные гейты RunPlan), иначе — гейты контракта (обратная совместимость).
  Selftest: трековый `ux_review` попадает в оценку и без evidence блокирует прогон.
- **tools/orchestrator.py** — `run_workflow(..., gate_ids=None)` пробрасывает список в evaluate.
- **tools/ai_ops_run.py** — orchestrated-прогон передаёт `plan['gates']` (base + треки).
- **manifest** — `execution_audit_2026_07_16.fixed_v2_54`; пункт про неоцениваемые треки убран
  из p0_backlog; `package_version` → 2.54.0.

## [2.53.0] — 2026-07-16

**Аудит исполнения: contained-фиксы (security + tool-loop) + честный разворот к P0.** Внешний
аудит исполнения (main 2.50) верно показал: компоненты есть, но не собраны в один движок;
generic-путь гоняет doc-оркестратор, не tool-loop; child не получает сам движок; Policy не
была настоящей security boundary. Все дефекты проверены по коду — подтвердились. Фичи
заморожены, открыт один P0-эпик: обычная задача → проверяемый draft PR.

### Fixed (security/correctness)
- **tools/tool_broker.py — path traversal (SECURITY).** `decide()` запрещает `..`-escape и
  абсолютный путь для read/write; `execute()` — containment-guard (resolve под root, ловит и
  симлинки). Selftest: `../`/absolute → deny; execute не создаёт файл вне корня.
- **tools/tool_loop.py — слепота петли.** Содержимое `read` и вывод `shell` (`output_tail`)
  теперь возвращаются в контекст модели, а не только `OK/FAILED`. Selftest: модель видит
  содержимое прочитанного файла (sentinel).

### Changed (честность — снят overclaim)
- **README** — «исполняющее ядро» → «компоненты исполнения» + блок честного статуса: единый
  движок task→PR НЕ готов, generic-путь = doc-оркестратор, движок не ставится в child.
- **manifest** — `execution_engine.execution_audit_2026_07_16`: honest_status, fixed_v2_53,
  `frozen` (фичи), `p0_epic`, `p0_backlog` (8 подтверждённых по коду, НЕ сделанных пунктов);
  `package_version` → 2.53.0.
- **decisions/registry.yaml** — эпизод `ep-2026-07-16-execution-audit` + outcome (заморозка
  фич, P0-эпик, критерий успеха 2/3 задачи → draft PR с зелёным CI без переписывания).

**P0-backlog (честно, НЕ сделано):** единый pipeline вместо двух движков; RunPlan-гейты в
прогоне (сейчас берутся из base_workflow — треки планируются, но не оцениваются); установимый
CLI с движком в child (managed_set без tools/validation); shell-sandbox (allowlist/сеть/env);
условный human_approval (сейчас блокирует безусловно); evidence на точный commit SHA;
reviewer.json от оркестратора; проверка на 3 реальных задачах.

## [2.52.0] — 2026-07-16

**Находки обкатки 4 и 6 закрыты.** Из отчёта обкатки в ии-среде.

### Changed
- **validation/ai_route.py (finding 4)** — неизвестный `task_type` больше не тянет слепо
  тяжёлый ENGINEERING: при `size` xs/small и не-высоком риске → QUICK (мелкая правка не
  получает 13 гейтов); medium/high риск и большой размер → ENGINEERING (честный default);
  `risk: critical` по-прежнему → CRITICAL. Selftest: два новых кейса (small→QUICK, large→ENGINEERING).
- **validation/validate_feature_blueprint.py (finding 6)** — `feature.status: released` требует
  хотя бы один артефакт со `status: done`; released при нуле done → fail («reality/blueprint
  дрейф: выпущено, а сделанного нет»). Кит не видит код произвольного репо — это честный
  прокси через artifact-evidence. Selftest: released без done → fail; с done → ок.
- **manifest** — `execution_engine.dogfood_findings_2026_07_16` (findings 4/5/6 → закрыты
  v2.51/2.52); `package_version` → 2.52.0.

**Итог по отчёту обкатки:** находки 1–3 закрыты ранее (2.37/2.39), 4–6 — сейчас (2.51/2.52).
Наблюдение 6 (о продукте) стало проверкой кита. Остаток отчёта (North Star/baseline) —
накапливается эксплуатацией, не код.

## [2.51.0] — 2026-07-16

**Находка обкатки 5 + честность дока: привязка WorkItem к именованной фиче.** Отчёт обкатки
в ии-среде (кит проведён 2.26→2.50, `baseline_ready` достигнут на 6 фичах) вскрыл: в
claude-code задача идёт на ad-hoc `wi-<hash>`, поэтому срез истории падает на новую фичу с
1 срезом и **baseline не двигается**. Плюс мой же `docs/dogfooding-metrics.md` (v2.50)
переоценивал: «автозапись вшита в стадии» верно только для generic-orchestrator.

### Added
- **tools/ai_ops_run.py** — `run(..., feature=...)` + CLI `--feature <имя>`: WorkItem
  привязывается к именованной фиче (`build_plan(workitem_id=feature)`), срезы копятся на неё.
  Selftest: без `--feature` → `wi-<hash>`; с `--feature library-view` → WorkItem на фиче.

### Changed
- **docs/dogfooding-metrics.md** — ЧЕСТНО: полностью автоматичная запись — только
  generic-orchestrator; в claude-code срез пишется на стадии `finish` (`run_report --record`),
  на ИМЕНОВАННОЙ фиче; ad-hoc `wi-<hash>` baseline не двигает. (Исправлен overclaim v2.50.)
- **commands/task/ai-finish-task.md** + генерируемый `ai-run` — требование именованной фичи
  и явной записи среза в `finish`; «автозаписи за стадию» в claude-code нет.
- **manifest** — `effect_metrics.by_runtime` (честная разница generic vs claude-code) +
  `auto_record.feature_binding`; `package_version` → 2.51.0.

Прочие находки обкатки: #4 (мис-роутинг `task_type: None → ENGINEERING` для мелкой UI-правки)
и #6 (drift-гейт «released ⇒ код присутствует») — на следующий срез. Находки 1–3 уже закрыты
ранее (2.37/2.39).

## [2.50.0] — 2026-07-16

**Чеклист обкатки: как метрики закрываются сами.** Короткий док для child о том, что North Star
(`autonomous_reviewable_pr_rate`) и baseline набираются не вручную, а прогоном реальных задач
через `/ai-run`: автозапись срезов вшита в стадии, порог `baseline_ready` — 3 фичи × ≥3 среза.

### Added
- **docs/dogfooding-metrics.md** — чеклист: обновление кита, запуск задач через `/ai-run`,
  проверка прогресса через `effect_metrics.py`, что закрывается попутно (golden-repo/lifecycle,
  interaction-log). Кладётся под руку в каждой сессии child.

### Changed
- **FILE_INDEX** — ссылка на новый док; **manifest** `package_version` → 2.50.0.

## [2.49.0] — 2026-07-16

**3.0 — additive-complete; физразнос дерева отложен до 3.1 (осознанное решение).** При
подготовке к срезу 3 (физический перенос файлов в `packages/<name>/`) вскрылся жёсткий
блокер: перенос ломает CI-контракт **уже установленных** child. Их `ai-ops-update.yml` и
`ai-ops-validate.yml` хардкодят `/tmp/ai-ops-kit/installer/ai_ops.py` и
`.../validation/validate_ai_ops_child.py` — после переноса апдейт сломается, а починить
можно только апдейтом (замкнутый круг). Плюс 33 файла с PKG-путями и remap `managed_set`.
При этом польза «пакетов» (гранулярная установка) уже дана срезами 0–2 без переноса.

### Changed
- **decisions/registry.yaml** — эпизод `ep-2026-07-16-tree-split` + outcome: физразнос → 3.1
  (при раздельной дистрибуции пакетов и миграции child-CI на путь-агностичный вызов);
  reversibility two-way.
- **manifest** — `release_3_0.additive_complete: true`, `physical_split_deferred_to: "3.1"`
  + `deferral_reason`; `not_yet` = 3.1-разнос; `package_version` → 2.49.0.
- **docs/3.0-design.md + ROADMAP.md** — срез 3 помечен отложенным до 3.1 с обоснованием;
  добавлен блок «Статус 3.0: additive-complete».

**Что это значит:** 3.0 как набор ФИЧ поставлен и обкатываем (границы+валидатор, `ai-run`
канонический, по-пакетная установка) — без единого сломанного child. Формально-breaking
разнос дерева делается в 3.1 отдельным супервизируемым заходом с миграцией child-CI.

## [2.48.0] — 2026-07-16

**3.0-срез 2: по-пакетная установка — аддитивно, дефолт = все.** Installer научился ставить
подмножество пакетов: `.ai-ops.yaml -> packages: [ai-ops-core, ...]` фильтрует managed_set по
границам из `packages/*/package.yaml`. Обратная совместимость железная: поля нет → ставится
всё (footprint как раньше); существующие child ничего не замечают.

### Added
- **installer/ai_ops.py** — `package_ownership` (файл→пакет из деклараций), `selected_packages`
  (читает `.ai-ops.yaml -> packages`, дефолт None=все), `filter_by_packages` (чистая функция
  фильтра). `managed_set()` применяет фильтр. Selftest: ownership резолвит декларации, выбор
  `[ai-ops-core]` оставляет core-файлы и отсекает product, неназначенный файл ставится всегда,
  `None` → всё.

### Changed
- **manifest** — `release_3_0.slice2_done: true` + `per_package_install` (config_field, rule);
  `remaining_slices` = [physical-tree-split, migration-guide]; `package_version` → 2.48.0.
- **docs/3.0-design.md** — срез 2 помечен ✅ (v2.48).

**Инвариант честности:** файл, не назначенный ни одному пакету, ставится ВСЕГДА — пока дерево
физически не разбито (срез 3), частичная установка не должна ронять неразмеченные файлы.
Оставшиеся срезы 3–4 (физразнос + MIGRATION_GUIDE) — breaking, по явному решению с обкаткой.

## [2.47.0] — 2026-07-16

**3.0-срез 1: `ai-run` — канонический вход; `ai-start-task` — совместимый алиас.** Единый
контроллер (`tools/ai_ops_run.py`: route → RunPlan → WorkItem → preflight → active-work →
исполнение → отчёт) становится основным путём запуска задачи. `ai-start-task` не удаляется —
остаётся алиасом той же спины (снятие — не раньше 4.0). Ничего у существующих child не
ломается: обе команды ведут к одному потоку.

### Added
- **tools/generate_runtime.py** — `render_ai_run`: генерирует `ai-run` в раннтайм для каждого
  runtime (тонкий адаптер к контроллеру); selftest проверяет генерацию + канонические токены.

### Changed
- **commands/task/ai-run.md** — помечена каноническим входом (3.0-срез 1), снят хедж «цель 3.0».
- **commands/task/ai-start-task.md** + генерируемый шаблон — нота «канонический вход — ai-run;
  это совместимый алиас той же спины».
- **README/QUICKSTART/ROADMAP** — вход описан через `ai-run` (алиас `ai-start-task` рядом).
- **manifest** — `release_3_0.slice1_done: true` + `canonical_entry`/`alias_retained`;
  `remaining_slices` = [per-package-install, physical-tree-split, migration-guide];
  `package_version` → 2.47.0.

**Честная граница:** канонизация входа не удаляет старый путь и не трогает установочный
контракт — это безопасный, обратимый срез. Оставшиеся срезы 2–4 (по-пакетная установка,
физический разнос дерева, MIGRATION_GUIDE) — breaking, запускаются по явному решению с обкаткой
на child.

## [2.46.0] — 2026-07-16

**3.0-срез 0: границы 5 пакетов объявлены и стерегутся — БЕЗ переноса файлов.** Первый
безопасный шаг к 3.0 (`docs/3.0-design.md`): декларируем, какой файл к какому пакету
относится и как пакеты зависят друг от друга, и добавляем валидатор, который эту структуру
охраняет. Ничего не ломается (аддитивно), но будущий физический сплит теперь опирается на
проверенную непротиворечивую карту.

### Added
- **packages/{ai-ops-core,ai-ops-quality,ai-ops-execution,ai-ops-product,ai-ops-installer}/package.yaml** —
  декларации границ: `name`, `description`, `depends_on`, `includes` (glob'ы файлов). Зависимости
  однонаправленные: core ← quality ← execution, core ← product, installer → все.
- **validation/validate_package_boundaries.py** (+ selftest) — проверяет: форму package.yaml;
  существование зависимостей без self-dep; ацикличность графа (DAG); резолв каждого include-glob
  (нет висячих деклараций); непересечение границ (файл не в двух пакетах); отчёт покрытия.
  На реальном ките: 308 файлов назначено, границы не пересекаются, граф ацикличен.

### Changed
- **CI + AGENTS.md** — шаг `validate_package_boundaries.py` (+ карта репозитория: зона `packages/`).
- **manifest** — `execution_engine.release_3_0` (design, packages_declared, boundary_validator,
  `slice0_done: true`, remaining_slices); `not_yet` теперь = breaking-срезы 1–4 (по явному решению);
  `package_version` → 2.46.0.

**Честная граница:** это ДЕКЛАРАЦИЯ границ, не сам сплит. Файлы на местах; канонизация
`ai-ops run`, по-пакетная установка и физический разнос дерева — срезы 1–4, запускаются по
явному решению владельца с обкаткой на child (docs/3.0-design.md). 173 файла пока не назначены
(validation/docs/examples/… — назначаются в срезе 3).

## [2.45.0] — 2026-07-16

**Дизайн 3.0 + актуализация ROADMAP.** Живая часть Execution Engine разблокирована (2.42–2.44):
tool-loop подтверждён живьём, preflight ходит в GitHub REST, evidence collector гоняет команды
профиля. Остался единственный крупный заход — 3.0 (breaking): `ai-ops run` основным путём +
сплит на 5 пакетов. Он по своей природе ломающий и outward-facing (меняет установочный контракт
всех child), поэтому оформлен как детальный план и запускается по явному решению — не одним
коммитом.

### Added
- **docs/3.0-design.md** — дизайн 3.0: зачем major, что именно breaking, границы пяти пакетов
  (core / quality / execution / product / installer) с однонаправленными зависимостями,
  `ai-ops run` каноническим входом (`/ai-start-task` → совместимый алиас), миграционный мост
  (монорепо-пакеты → мета-пакет по умолчанию → `.ai-ops.yaml.packages` с дефолтом «все»),
  срезы реализации 0–4 и риски.

### Changed
- **ROADMAP.md** — «На паузе — живое» → «Живое разблокировано (v2.42–2.44)»; цель 3.0 ссылается
  на `docs/3.0-design.md` и помечена «запуск по явному решению».
- **manifest** — `package_version` → 2.45.0.

Заметка: 2.45 — подготовка и план; сам breaking-разнос дерева не начат (ждёт явного «да»).

## [2.44.0] — 2026-07-16

**Stack-aware evidence collector — детерминированный сбор доказательств из профиля репо.**
Замыкает Project Detector → gate: RepositoryProfile знает команды build/lint/typecheck/test
конкретного репо, а коллектор их ИСПОЛНЯЕТ (через Tool Broker, уровень execution) и превращает
результат в структурный evidence для `implementation_verification` — ровно по его evidence_schema.
Вердикт = exit_code реальной команды, не «pass словом» и не LLM.

### Added
- **tools/evidence_collector.py** (+ selftest) — `collect(profile, root, policy)`:
  прогоняет команды всех стеков профиля через `tool_broker.execute`, собирает `checks`
  (pass/fail/not_run), структурный `schema_evidence` (command/exit_code/revision) и готовый
  `gate_evidence` для `implementation_verification`. Selftest: всё прошло → gate pass; провал
  команды → fail + blocker; команда не определена → not_run (флаг не выдан); деструктивная
  команда → отклонена Policy (не исполнена); вывод валиден по gate-evidence-схеме; интеграция
  detect → collect на python-репо.

### Changed
- **CI + AGENTS.md** — шаг `tools/evidence_collector.py --selftest`.
- **manifest** — `execution_engine.evidence_collector` (feeds_gate implementation_verification);
  `phase3_done += stack-aware-evidence-collector`; в `not_yet` остался только 3.0-заход;
  `package_version` → 2.44.0.

**Инвариант честности:** в `provided` попадают только реально запущенные и прошедшие проверки;
команда `None` (undetermined) → `not_run`, флаг не фабрикуется (гейт честно останется
невыполненным, пока человек не задаст команду). Исполнение — только через Tool Broker
(`policy.decide` первым): деструктивная команда в профиле отклоняется, а не выполняется.

## [2.43.0] — 2026-07-16

**Concurrency preflight видит открытые PR без gh — REST-фоллбэк.** Раньше, если в среде нет
`gh` CLI, пункт «открытые PR по тем же путям» помечался `unavailable` (finding обкатки в
ии-среде). Теперь при отсутствии `gh` preflight ходит в GitHub REST API напрямую (`urllib`,
stdlib) с токеном из env — и честно видит конкурирующие PR.

### Added
- **tools/concurrency_preflight.py** — `open_prs_via_rest` (REST-фоллбэк), `_parse_owner_repo`
  (owner/repo из https/ssh remote), `_prs_overlap` (чистая функция пересечения путей),
  `_github_token`/`_gh_api_get`. Порядок источников: `gh` CLI → GitHub REST → `unavailable`.
  Новые selftest-кейсы: разбор URL, пересечение путей, REST без токена → честный `unavailable`.

### Changed
- **manifest** — `execution_engine.concurrency_preflight.open_prs_sources: [gh-cli, github-rest]`;
  dogfood-finding о слепоте к PR помечен ЗАКРЫТО; `execution_engine.phase3_done: [preflight-github-rest]`;
  из `not_yet` убран пункт про доступ preflight к GitHub API; `package_version` → 2.43.0.

**Границы честности:** токен только из env (`GITHUB_TOKEN`/`GH_TOKEN`), в вывод и логи не
попадает; при ошибке API сообщается класс ошибки, не тело запроса. GHE — через `GITHUB_API_URL`.
Нет ни `gh`, ни токена → `unavailable` (не выдаётся за `clean`).

## [2.42.2] — 2026-07-16

**tool-loop подтверждён живьём полностью — `live_proposal_quality: verified`.** Повторный живой
прогон на DeepSeek после фикса промпта (v2.42.1): та же задача прошла циклом
`write → shell(проверка) → done` за 3 шага (`executed=2, denied=0, stopped=done`) — модель больше
не зацикливается на записи, а завершает задачу. Execution Engine Фаза 2 закрыта.

### Changed
- **manifest** — `execution_engine.tool_loop.live_proposal_quality: partial → verified` +
  evidence обоих прогонов (до/после фикса); добавлен `execution_engine.phase2_done`
  (`tool-loop-live-verified`); из `not_yet` убран пункт про живой прогон петли;
  `package_version` → 2.42.2.

Совместно v2.42.0–2.42.2 замыкают петлю `task → controlled execution` и подтверждают её
на реальной модели через провайдер-swap — без изменения кода петли (`openai-compatible`).

## [2.42.1] — 2026-07-16

**Живой прогон tool-loop подтвердил механику — и вскрыл слабость промпта.** Первый живой
прогон петли на DeepSeek (`openai-compatible`) в ии-среде: реальная модель выдавала валидные
JSON-предложения, все распарсились и исполнились, `denied=0` (scope соблюдён), `budget` честно
оборвал петлю на потолке. МЕХАНИКА петли — подтверждена живьём (`live_mechanics_verified: true`).
Находка: модель зациклилась на `write` (6/6 шагов), не перешла к shell-проверке и `done`.

### Changed
- **tools/tool_loop.py** — `make_model_proposer`: усилён промпт предложителя (явные op-варианты,
  правило «не повторяй выполненный шаг; после записи+проверки сразу `done`», журнал шагов
  выделен заголовком) — чтобы живая модель сходилась к завершению, а не писала файл по кругу.
- **manifest** — `execution_engine.tool_loop`: `live_mechanics_verified: true` + evidence
  прогона; `live_proposal_quality: unverified → partial` (механика да, сходимость дорабатывается);
  `package_version` → 2.42.1.

**Честно:** петля исполняет предложения живой модели безопасно (политика+бюджет держат),
но качество самих предложений (сходимость к done) — предмет доработки промпта; повторный
живой прогон подтвердит эффект фикса.

## [2.42.0] — 2026-07-16

**Tool-calling петля — механика (Execution Engine Фаза 2, срез 3).** Замыкает
`task → controlled execution`: модель ПРЕДЛАГАЕТ действие (JSON), Policy решает
(`tool_broker`), Broker исполняет и собирает Evidence, результат идёт обратно в контекст —
до `done` / потолка `budget` / `max_steps`. «Модель предлагает, политика решает»: запрещённое
не исполняется, а возвращается модели как `DENIED`, чтобы та скорректировалась.

### Added
- **tools/tool_loop.py** (+ selftest) — механика петли: `parse_action` (JSON из ответа
  модели), `make_model_proposer` (обёртка text-provider в JSON-протокол действий),
  `run_loop(proposer, root, policy, budget, max_steps)` → отчёт (executed/denied/evidence/
  transcript, стоп по done/budget/max_steps). Selftest: write в scope исполнен, write вне
  scope запрещён и НЕ создан, shell даёт evidence, budget обрывает петлю, max_steps-предохранитель.

### Changed
- **CI + AGENTS.md** — шаг `tools/tool_loop.py --selftest`.
- **manifest** — `execution_engine.tool_loop` (status `component-ready`,
  `verified_offline: true`, `live_proposal_quality: unverified`); `package_version` → 2.42.0.

**Честная граница:** МЕХАНИКА петли детерминирована и проверена offline (mock-предложитель).
Качество предложений ЖИВОЙ модели — это `live_path` (swap провайдера на `openai-compatible`),
проверяется живым прогоном (как Шаг A для текста), а не этим offline-кодом.

## [2.41.0] — 2026-07-15

**Project Detector → RepositoryProfile (P0#5 аудита: stack-aware evidence).** Система сама
определяет стек и команды build/lint/typecheck/test, а не спрашивает — основа для того,
чтобы гейт `implementation_verification` знал, ЧЕМ собирать/тестировать именно этот репо.

### Added
- **tools/project_detector.py** (+ selftest) — `detect`: из манифестов (package.json/
  pyproject/go.mod/pom/Cargo…) выводит стеки, package manager, фреймворки, команды
  build/lint/typecheck/test, CI, monorepo. Детерминированно; неопределённое → `undetermined`
  (не выдумано); `status: draft` (подтверждает человек — writer≠judge).
- **schemas/repository-profile.schema.json** — контракт профиля.

### Changed
- **manifest** — `execution_engine.project_detector` (child: `.ai/project/RepositoryProfile.yaml`);
  `package_version` → 2.41.0.

Связь: RepositoryProfile — stack-часть онбординга (repo-onboarding) и вход будущих
stack-aware evidence collectors. Сам сбор build/test-evidence по профилю (запуск команд) —
следующий срез (перекликается с tool-loop, часть — на живой прогон).

## [2.40.0] — 2026-07-15

**Живой прогон подтверждён — `verified_against_live_api: true`.** Первый живой Шаг A
(QUICK на DeepSeek через `openai-compatible`) в ии-среде прошёл чисто по всем точкам.

### Changed
- **registry/runtimes.yaml → generic-orchestrator.live_provider** — `verified_against_live_api`
  false → **true** с `verified_evidence` (что именно подтверждено, не «поверьте на слово»):
  - 4 стадии, связные артефакты на живой модели без деградации против mock;
  - audit-log редакция держится (только `task_hash`, без сырого текста) — v2.31 на живом вызове;
  - **гейты честны против живой модели**: убедительный «pass» словами → BLOCKED без evidence;
  - budget-счётчик живой (`model_calls=4`, `budget_exceeded=false`) — v2.38;
  - `providers` += `openai-compatible`.
- **manifest** — `package_version` → 2.40.0.

Честная граница: подтверждён живой **провайдер-адаптер** (модель генерит артефакты стадий).
tool-calling петля (модель предлагает действия → broker исполняет) — **не** входит в этот
флип, это отдельный Шаг B. «Зелёный» прогон (evidence-пайплайн + tool-loop) — следующий срез.

## [2.39.0] — 2026-07-15

**OpenAI-совместимый провайдер (DeepSeek/local) — doc↔code fix + provider-agnostic живой
прогон.** Шапка `orchestrator.py` обещала `OPENAI_COMPATIBLE_BASE_URL`-адаптер, но код
бил только в `api.openai.com`. Теперь реализовано — child может гнать живой прогон на
своём провайдере (напр. DeepSeek), не добывая ключ Anthropic/OpenAI.

### Added / Fixed
- **tools/orchestrator.py** — провайдер `openai-compatible`: `--provider openai-compatible
  --model <...>` + env `OPENAI_COMPATIBLE_BASE_URL` + `OPENAI_COMPATIBLE_API_KEY`. Любой
  OpenAI-совместимый endpoint (DeepSeek: `https://api.deepseek.com/chat/completions`,
  local, GigaChat-gateway). `_openai_call` получил `base_url`/`key_env`; docstring
  приведён к реальности. Без base_url/model/ключа — честные ошибки (selftest).
- **manifest** — `providers.live_executor_providers: [anthropic, openai, openai-compatible]`;
  `package_version` → 2.39.0.

Секрет — только из env (не в репо/логах). Живой путь opt-in; CI/selftest офлайн на mock.

## [2.38.0] — 2026-07-15

**Execution budget — enforcement потолка прогона.** `RunPlan.execution_budget` был только
декларацией; теперь `max_model_calls` реально ограничивает вызовы модели (перед будущей
tool-calling петлёй — чтобы «дал задачу» не стало неограниченным расходом).

### Added
- **tools/budget.py** (+ selftest) — `Budget(max_model_calls, max_cost)`; `charge_call()`
  проверяет потолок ДО вызова (превышение → `BudgetExceeded`, вызов не делается);
  `from_dict(RunPlan.execution_budget)`.

### Changed
- **tools/orchestrator.py** — `run_workflow(budget=...)`: перед каждой стадией
  `charge_call()`; превышение → остановка, `status: blocked` + `budget_exceeded`;
  `model_calls` в interaction-log и TaskState.
- **tools/ai_ops_run.py** — прокидывает `RunPlan.execution_budget` в оркестратор.
- **manifest** — `execution_engine.execution_budget` (enforced: max_model_calls;
  declared_only: max_cost/max_duration — нужен учёт токенов/времени на рантайме);
  `package_version` → 2.38.0.

Честно: `max_model_calls` детерминирован и enforced; `max_cost`/`max_duration` — объявлены,
но без учёта токенов/времени провайдером по ним не блокируем (не выдаём за enforced).

## [2.37.0] — 2026-07-15

**Tool Broker: child-override protected-paths (finding обкатки 2.36).** Обкатка в ии-среде
вскрыла: Policy читал protected-paths только из пакета kit → защищал несуществующие
дефолты (`production/`, `security/`, `migrations/destructive/`) и НЕ защищал реальный
protected путь репозитория (`.github/workflows/` из `.ai-ops.yaml`). Корректностный/
security-баг — закрыт.

### Changed
- **tools/tool_broker.py** — `Policy(child_root=...)`; protected-paths = **MERGE**: дефолт
  пакета `config/protected-paths.yaml` + карта child'а (`.ai-ops.yaml → protected_paths`,
  список строк; опционально `<child>/config/protected-paths.yaml`). Child добавляет свои
  пути, не отменяя универсально-опасные дефолты. Форматы строки и `{path,approval}` оба
  поддержаны. Selftest: child-protected `.github/workflows/` запрещён, дефолт `security/`
  сохраняется (merge, не replace).
- **rules/ai/ToolBrokerPolicy.md** — источник protected-paths = merge пакет+child.
- **manifest** — `tool_broker.protected_paths_source`; `package_version` → 2.37.0.

## [2.36.0] — 2026-07-15

**Execution Engine — Фаза 2 (срез 2): Tool Broker + Policy Engine.** Для голого
API-рантайма (generic-orchestrator) — контролируемое исполнение: модель ПРЕДЛАГАЕТ
действие, а разрешено ли оно, решает политика, не модель.

### Added
- **tools/tool_broker.py** (+ selftest, 12 проверок на temp git-репо) — `Policy`
  (уровни `security/permission-levels.yaml` + write_scope + `config/protected-paths.yaml`)
  и `execute` с обязательным Evidence (op/target/exit_code/revision/ok). Инвариант:
  `execute()` всегда вызывает `decide()` первым — обхода политики нет. Правила: read≥read-only,
  write только в write_scope, protected → privileged+approval, необратимое (rm -rf,
  git push --force, drop table, curl|sh) → destructive+approval, иначе отказ.
- **rules/ai/ToolBrokerPolicy.md** — «модель предлагает, политика решает».

### Changed
- **manifest** — `execution_engine.tool_broker` (status: component-ready); `not_yet` →
  живая tool-calling петля в оркестраторе + доступ preflight к GitHub API;
  `package_version` → 2.36.0.

Честно: Broker/Policy/Evidence готовы и протестированы как компонент. Петля «живая модель
предлагает действия в цикле» интегрируется в оркестратор отдельным шагом (нужен
tool-calling провайдер). Для рантаймов со своим tool loop (claude-code) enforcement
держится на Evidence, не на брокере кита.

## [2.35.0] — 2026-07-15

**Фиксы из обкатки 2.34 в ии-среде.** Догфудинг вскрыл три вещи — закрываем аддитивно.

### Added
- **templates/ci/ai-ops-validate.yml** — канонический child-CI: пин kit =
  `installed_version` из `.ai-ops.yaml` (клон по тегу `v<version>`), а не хардкод строки в
  protected `ci.yml`. Убирает трение «каждый `ai-ops update` требует правки protected-файла
  ради пина». Один источник версии, который и так едет через PR обновления. Ставится
  `ai-ops init`.

### Changed
- **tools/ai_ops_run.py** — в planned-режиме run-report честно помечает
  `run_state_materialized: false`: `.ai/runtime/workitems/<id>/` создаёт рантайм при
  реальном исполнении стадий, не контроллер; на её наличие после planned-прогона полагаться
  нельзя (finding обкатки).
- **manifest** — `execution_engine.dogfood_findings` (planned-run/workitems, preflight
  слеп к PR без gh, пин-трение) — вход для Tool Broker; `package_version` → 2.35.0.

Finding для Фазы 2 (Tool Broker): `concurrency_preflight` слеп к открытым PR без gh/токена
(`open_prs.status: unavailable`) — реальная изоляция потребует доступа к GitHub API.

## [2.34.0] — 2026-07-15

**Execution Engine — Фаза 2 (срез 1): единый контроллер `ai-ops run`.** Разрозненные
шаги собраны в одну транзакцию — обещанный «task → controlled execution → report».

### Added
- **tools/ai_ops_run.py** (+ selftest) — `run`: классификация/маршрут → RunPlan
  (base_workflow + треки + агрегированные гейты) → WorkItem → регистрация в реестре
  активных работ → исполнение → компактный `run-report.json`.
  - **claude-code**: план + каркас состояния (RunPlan/WorkItem/active-work), стадии
    исполняет рантайм по плану — `status: planned` (кит не притворяется, что исполнил);
  - **generic-orchestrator**: реальный прогон стадий и гейтов — `status: done|blocked`.
- **commands/task/ai-run.md** — прозаический контракт команды.

### Changed
- **manifest** — `execution_engine.run_controller`; `not_yet` сдвинут (Tool Broker/Policy
  Engine для generic-orchestrator, Project Detector + stack-адаптеры, `ai-ops run` как
  основной путь + сплит на пакеты — 3.0); `package_version` → 2.34.0.

Честно: аддитивно (2.x). Для рантаймов со своим tool loop контроллер компонует и
готовит план — исполнение и enforcement «всех стадий» держатся на evidence (commit SHA,
структурный reviewer-result), а не на доверии рантайму. Свой tool loop нужен только
generic-orchestrator — это следующий, тяжёлый срез.

## [2.33.0] — 2026-07-15

**Execution Engine — Фаза 1 (часть 2): структурные reviewer-outputs + evidence-схемы
гейтов.** Убирает «pass словом»: истина о гейте — структура, а не regex по markdown.

### Added
- **schemas/reviewer-result.schema.json** + **validation/validate_reviewer_result.py**
  (+ selftest) — reviewer возвращает `{status, checks[], blockers[]}`; `status=fail`
  обязан иметь blockers; несогласованность (fail-check при общем pass) — ошибка.
- **gate_executor.collect_evidence** — читает `stage-<id>.reviewer.json` как **источник
  истины** (приоритет над markdown-regex; regex остался фолбэком для старых артефактов).
- **quality/gates.yaml → implementation_verification.evidence_schema** — детерминированный
  контракт evidence (build/lint/typecheck/tests: command/exit_code/revision/log_path);
  `gate_executor.validate_evidence_schemas` проверяет well-formedness (типы из словаря).

### Changed
- **manifest** — `execution_engine.phase1_done` [run-plan-tracks, structured-reviewer-outputs,
  per-gate-evidence-schema]; `not_yet` сдвинут на Фазу 2 (`ai-ops run`, tool loop, stack
  evidence collectors); `package_version` → 2.33.0.

Фаза 1 закрыта. Enforcement структурной формы evidence — по мере обкатки (сейчас
gate_executor принимает структурный reviewer-result как истину; строгая проверка формы
build/test-evidence — опция, не ломает существующие потоки).

## [2.32.0] — 2026-07-15

**Execution Engine — Фаза 1 (часть 1): RunPlan + base_workflow/tracks.** Модель «один
workflow» дополнена планом треков. Реальная фича многослойна; base_workflow задаёт
характер, а треки (обязательные области качества) выводятся из затронутых зон и
**добавляют свои гейты**. Так «Design/Analytics/Docs by Default» становится механикой:
PRODUCT-задача, тронувшая UI и измеримое поведение, сама получает UX/analytics/security
гейты, которых в самом PRODUCT-контракте не было (прямо по аудиту).

### Added
- **registry/tracks.yaml** — quality tracks: `signal → gates` (VISUAL/ANALYTICS/SECURITY/
  DOCUMENTATION/EVENTS — required; AI/RELEASE — conditional), с `skip_reason` для
  explainable skips.
- **schemas/run-plan.schema.json** + **tools/run_plan.py** (+ selftest) — `plan`: из
  сигналов задачи строит RunPlan (base_workflow из ai_route + треки + агрегированные
  гейты + пропуски с причиной); `validate`: целостность tracks.yaml (гейты резолвятся) и
  формы RunPlan. Аддитивно: ai_route не менялся.

### Changed
- **commands/task/ai-start-task.md** — шаг RunPlan (треки + агрегированные гейты) на intake.
- **manifest** — раздел `execution_engine` (phase0_done + run_plan + честный not_yet);
  `package_version` → 2.32.0.

## [2.31.0] — 2026-07-15

**Execution Engine — Фаза 0: correctness & safety.** Пять подтверждённых по коду дыр из
внешнего аудита (2.30.0), среди них безопасность и регрессия установленной команды. Всё
аддитивно (2.x).

### Fixed
- **Дрифт `ai-start-task`** — генерируемая команда (`generate_runtime.py`) расходилась с
  canonical `commands/task/ai-start-task.md`: в установленную версию не попадали
  concurrency preflight, WorkItem, worktree, active-work (регрессия v2.22–v2.28). Теперь
  генерируемая команда — тонкий адаптер к canonical со всем потоком; selftest ловит
  расхождение.
- **`security` не вызывался в ENGINEERING** — добавлен в `ENGINEERING.quality_gates`
  (applicability и так включала ENGINEERING).
- **`ai_red_team` не блокировал** — `blocking: true` (по применимости: LLM/агентный
  компонент с пользовательским вводом). jailbreak/injection/PII-утечки теперь блокируют.
- **Сырой task-текст в audit-log** — оркестратор больше НЕ пишет `task_text[:200]` (риск
  ПДн/секретов); пишет `workitem_id` + `task_hash`. Соответствует заявлению постуры.
- **Коллизия состояния параллельных задач** — прогон живёт в
  `.ai/runtime/workitems/<id>/` (по WorkItem), а не `.../orchestrator/<workflow>/`;
  `task_id = workitem_id`; resume сверяет `task_hash` и `workflow` (нельзя «продолжить»
  чужую задачу под тем же id). `--workitem-id` в CLI; `tools/workitem.py` run_state
  синхронизирован.

### Changed
- **manifest** — `package_version` → 2.31.0.

## [2.30.0] — 2026-07-15

**Автонакопление истории эффекта — baseline закрывается сам.** Причина, по которой
baseline метрик застревал: `run_report --record` был «шагом, который надо не забыть», и
фичи получали 1 срез вместо ≥3. Теперь запись среза — структурная часть каждой стадии +
CI-нетто, без ручного «не забыть».

### Added
- **templates/ci/ai-ops-record.yml** — на каждый push фиксирует срез (`run_report
  --record`) по затронутым фичам и коммитит снимок в `.ai/project/report-history/` с
  `[skip ci]` (без рекурсии; инструменты из parent, как в ai-ops-update). Ставится
  `ai-ops init`. Опт-аут — удалить файл.

### Changed
- **commands/task/ai-plan-task.md, ai-implement.md, ai-verify.md, ai-finish-task.md** —
  шаг «Записать срез эффекта» на каждой стадии: обычный прогон фичи сам даёт ≥3 среза.
- **installer/ai_ops.py** — `init` устанавливает и `ai-ops-record.yml`.
- **manifest** — раздел `effect_metrics.auto_record` (in_session + ci_net, честно про
  границу CI); `package_version` → 2.30.0.

## [2.29.0] — 2026-07-15

**Событийный каталог — единое имя события во всех слоях.** Закрывает класс
contract↔code↔analytics naming drift: событие названо по-разному в контракте
(`task.completed`), коде (`task.complete`) и MetricCatalog (`catalog.publish`), плюс
концептуальная подмена domain event на AuditEvent. Родня `validate_claims` (doc↔code) и
`validate_cross_artifacts` (tracking↔dashboard), но для событий.

### Added
- **schemas/event-catalog.schema.json** + **validation/validate_event_catalog.py**
  (+ selftest, + пример) — каждое событие названо один раз; грамматика имени (lowercase
  dot-нотация, прошедшее время); `kind: domain|audit|analytics`; audit/analytics обязаны
  `maps_to` domain-событие (или `standalone`+`reason`) — три «языка» сходятся к одному
  имени; domain нельзя описывать audit-полями (защита от подмены сущности);
  опциональный `--scan` ловит литералы событий в коде вне каталога (drift кода).
- **rules/engineering/EventNamingConvention.md** — правило единого имени и разделения слоёв.
- **quality/gates.yaml → event_contract_consistency** — гейт стадии specification,
  advisory; добавлен в quality_gates ENGINEERING/PRODUCT/ANALYTICS/AI_FEATURE.
- **examples/event-catalog-demo/events.yaml** — референс-каталог.

### Changed
- **manifest** — раздел `event_contract`; `package_version` → 2.29.0.

## [2.28.0] — 2026-07-15

**Concurrency preflight — коллизии параллельной работы до старта.** Закрывает класс
«concurrent-edit collision + stale premise»: два потока меняют одну поверхность → merge-
конфликт и переделки; хуже — работа на устаревшей посылке (удаляли «мёртвый» контрол,
который параллельный PR оживлял). Реестр активных работ (v2.22) ловит это, только если
оба потока в нём; preflight смотрит на фактическое состояние репозитория.

### Added
- **tools/concurrency_preflight.py** (+ selftest на temp git-репо) — по целевым путям:
  свежие мержи в base после отделения ветки (git, детерминировано — сигнал устаревшей
  премиссы), открытые PR по тем же путям (best-effort через gh; нет gh → `unavailable`, не
  выдаётся за clean), пересечение по зонам с реестром активных работ. Вердикт clean|collision.
- **quality/gates.yaml → concurrency_preflight** — гейт стадии intake, advisory (blocking:
  false; MVP-blocking ≤ 8 не трогаем), applicability пишущих workflow; добавлен в их
  quality_gates.
- **rules/engineering/ConcurrencyAwareness.md** — preflight до правки; перепроверять
  премиссу против актуального main, не базы ветки; «горячие» поверхности → меньше PR;
  координация по OwnershipMap; реестр и preflight дополняют друг друга.

### Changed
- **commands/task/ai-start-task.md** — шаг concurrency preflight на intake.
- **manifest** — `session_orchestration.concurrency_preflight`; `package_version` → 2.28.0.

## [2.27.0] — 2026-07-15

**Живой статус продукта — единая точка правды о «сейчас».** Закрывает системную дыру:
новая сессия анкорилась на устаревшем описании (перечисляла готовое как ненаписанное,
пыталась строить уже задеплоенное), потому что нормативные документы отвечают на «как
должно быть», а снимок «что фактически готово» жил протухшим в `CLAUDE.md`.

### Added
- **context/product/ProductStatus.md** — живой снимок готовности: что реально живёт в
  проде (backend/генерация/хранилище/деплой/провайдер), что отложено и почему, ссылки на
  источники истины. `stability: volatile` + `reviewed_at` → под freshness-контролем.
- **rules/core/ProductStatusPolicy.md** — правило: читать статус **первым**; обновлять на
  **каждом PR, меняющем готовность**; анти-паттерн — не смешивать вечные правила и снимок
  в `CLAUDE.md` (снимок — ссылкой на ProductStatus).

### Changed
- **commands/task/ai-session-start.md** — шаг «Статус продукта — ПЕРВЫМ», до нормативных
  документов.
- **commands/task/ai-finish-task.md** — обновление ProductStatus, если задача изменила
  готовность.
- **skills/repo-onboarding/SKILL.md** + **rules/meta/repo-onboarding.yaml** — онбординг
  заполняет черновик ProductStatus (отдельный от ProductOverview слой: «что работает», не
  «как должно быть»).
- **manifest** — `session_orchestration.living_status`; `package_version` → 2.27.0.

## [2.26.0] — 2026-07-15

**Session & Repository Orchestration — Срез 5: разговорная установка.** «Подключи AI Ops
и подготовь репозиторий» вместо ручных python-команд. Завершает эпик (все пять срезов).

### Added / Changed
- **tools/generate_runtime.py** — генерирует команду `ai-ops-init` для каждого рантайма
  (установка `installer/ai_ops.py init` → `doctor` → скилл `repo-onboarding` → предложить
  presets → отчёт); selftest на неё. Устанавливается в `.claude/commands/` при install.
- **manifest** — `session_orchestration.conversational_install`; `not_yet` закрыт (остаётся
  только runtime-часть: авто-срабатывание триггеров — привязка на уровне рантайма);
  `package_version` → 2.26.0.

Честно: реальную установку делает CLI (silent update запрещён; обновления — через
diff/PR); распознавание естественной фразы и запуск — поведение рантайма
(`verified_against_deploy: false`).

## [2.25.0] — 2026-07-15

**Session & Repository Orchestration — Срез 4: merge→memory flow.** Знание задачи не
теряется при мердже: что изменилось, какие решения, какие уроки — фиксируется в
репозиторную память.

### Added
- **tools/merge_memory.py** (+ selftest) — `record` пишет запись в
  `memory/lessons-learned/<дата>-<id>.md` в формате памяти (источник, owner, дата
  проверки, условие устаревания; зоны, решения со ссылкой на `decisions/registry.yaml`,
  уроки).

### Changed
- **commands/task/ai-finish-task.md** — шаг «обновить repository memory (merge→memory)»
  через инструмент + шаг удаления worktree.
- **manifest** — `session_orchestration.merge_to_memory` (перенесено из `not_yet`);
  `package_version` → 2.25.0.

## [2.24.0] — 2026-07-15

**Session & Repository Orchestration — Срез 3: worktree на WorkItem.** Изоляция файлов
между параллельными сессиями: каждая работа получает свой git worktree (рабочий каталог +
ветка), а не пишет в main. Это реальная git-операция, а не поведение рантайма.

### Added
- **tools/worktree.py** (+ selftest на временном git-репо) — `add`/`list`/`remove` git
  worktree под WorkItem в `.ai/worktrees/<id>`; отказ для main/master и дубликата; remove
  сохраняет ветку.
- **commands/task/ai-worktree.md** — команда изоляции работы (создать → работать в
  каталоге → зарегистрировать → по завершении смерджить и удалить).

### Changed
- **commands/task/ai-start-task.md** — шаг изоляции (worktree) перед регистрацией работы.
- **.gitignore** — `.ai/worktrees/`.
- **manifest** — `session_orchestration.worktree_per_workitem` (перенесено из `not_yet`);
  `memory_split.isolated` += `.ai/worktrees/**`; `package_version` → 2.24.0.

## [2.23.0] — 2026-07-15

**Session & Repository Orchestration — Срез 2: жёсткие связи задач.** Conflict forecast
из «пересекаются зоны?» дорос до явной модели связей между параллельными работами.

### Added / Changed
- **tools/active_work.py** — работа теперь может объявлять `--depends <id>` (зависимости)
  и `--contracts <пути>` (общие контракты). Прогноз классифицирует пересечение по типу:
  **area** (одна зона кода), **contract** (один общий контракт — риск расхождения),
  **dependency** (ждёт незавершённую задачу). Циклическая зависимость задач — **ошибка**
  register (детект цикла в графе depends_on), а не предупреждение.
- **schemas/active-work.schema.json** — поля `depends_on`, `shared_contracts`.
- **commands/task/ai-start-task.md** — шаг регистрации объявляет связи и показывает тип
  конфликта.
- **manifest** — `session_orchestration.active_work_registry.conflict_kinds`
  [area, contract, dependency, cycle]; `package_version` → 2.23.0.

## [2.22.0] — 2026-07-15

**Session & Repository Orchestration — Срез 1.** Начало внешнего слоя автоматики вокруг
ядра `task → workflow → agents → gates`: чтобы новая сессия не начинала с «а что вообще
происходит в этом репозитории?», а параллельные сессии не уничтожали работу друг друга.
Кит даёт скиллы/команды/инструменты/схему; «само-срабатывание» (распознать «подключи AI
Ops», авто-старт bootstrap, worktree-per-WorkItem) — поведение рантайма, объявлено честно
как runtime-binding (`verified_against_deploy: false`), а не как возможность кита.

### Added
- **skills/repo-onboarding/SKILL.md** (+ `rules/meta/repo-onboarding.yaml`) — первичный
  онбординг репозитория: агент исследует стек/структуру/сущности/дизайн-систему/правила/
  интеграции/метрики/словарь/риски и заполняет **черновики** `context/*`. Инвариант
  writer≠judge: источник истины подтверждает человек; ничего не выдумывается —
  неопределённое помечается «требует подтверждения»; секреты не собираются. opt-in.
- **schemas/active-work.schema.json** + **tools/active_work.py** (+ selftest) — реестр
  активных работ репозитория: `register`/`list`/`finish` и `check` — **conflict forecast**
  (предупреждение о пересечении зон между сессиями ДО старта, с вариантами решения).
  Работа не ведётся в main; each WorkItem — своя ветка, зоны, owner-сессия.
  Живёт в child по `.ai/runtime/active-work.yaml`, видна всем параллельным сессиям.
- **commands/task/ai-session-start.md** — session bootstrap: manifest → продуктовый
  контекст → свежие решения → ветка+WorkItem → параллельные работы (conflict forecast) →
  короткое резюме → старт. Runtime-исполняемая: только читает, не меняет.

### Changed
- **commands/task/ai-start-task.md** — шаг регистрации работы в реестре активных работ
  (со своей ветки, не из main) + показ conflict forecast перед стартом.
- **commands/task/ai-finish-task.md** — шаг снятия работы с реестра (освобождение зон).
- **manifest/ai-ops-manifest.yaml** — раздел `session_orchestration` (repo_onboarding,
  active_work_registry, session_bootstrap, memory_split shared/isolated, честный `not_yet`);
  скилл repo-onboarding в `skills.shipped`; `package_version` → 2.22.0.

## [2.21.0] — 2026-07-15

**Спецификация постоянного агента (Robin) — runtime-агностичная.** Кит описывает, что
должен делать постоянно работающий агент-ассистент команды и с какими границами, но НЕ
навязывает рантайм: даёт абстрактный контракт, спеку, пример обязанностей, валидатор и
шаблон привязки. Конкретный рантайм (Hermes, свой сервис, cron+CLI — что угодно) —
привязка на уровне child, как stack-skills. Идея адаптирована из
BayramAnnakov/team-os-toolkit (ROBIN-SPEC, MIT): «файл → skill, постоянный процесс → spec».

### Added
- **runtime/robin/ROBIN.md** — спека Робина: read-mostly (читает и синтезирует, не
  пишет в prod и не меняет базу знаний сам), двухслойная память (curated vs
  staged→promoted, перенос — только действие человека), append-only interaction-log в
  формате `tools/orchestrator.py`, границы (недоверенный чат-ввод, секреты только из env),
  kill-switch и честный критерий «когда внедрять».
- **runtime/robin/duties.example.yaml** — декларативные обязанности (id, триггер
  cron/событие, входы, выход+назначение, владелец); минимально обязательная —
  периодический дайджест.
- **validation/validate_duties.py** (+ selftest) — проверяет декларацию: обязательные
  поля, cron требует schedule / event требует event, есть периодический дайджест, и —
  инвариант read-mostly — destination не пишет в prod и не в curated/promoted-память.
- **templates/runtime/runtime-binding.example.yaml** — child объявляет, чем закрывает
  контракт (satisfied/declared по каждой возможности); Hermes — только как пример.
- **registry/runtimes.yaml → runtime_contracts.persistent-agent-runtime** — абстрактный
  контракт (always-on, вызов модели, чат-адаптер, kill-switch, audit-log, read-mostly,
  опция in-perimeter); `verified_against_deploy: false` — из среды разработки деплой не
  проверялся. Контракт, не адаптер: вне adapter_depth-проверки.

### Changed
- **governance/security-policies.md §3** — kill-switch развёрнут в runbook (отзыв прав →
  остановка процесса → отзыв чат-доступа → запись в audit-log) с честной пометкой, что
  механизм живёт на рантайме и из среды разработки не проверялся.
- **governance/security-posture.yaml** — области `audit-log` и `incident-killswitch`:
  evidence и note дополнены контрактом+спекой Robin (формат аудита и kill-switch стали
  требованием контракта); статусы остаются `partial` — enforcement на рантайме не
  проверялся (честно).
- **manifest/ai-ops-manifest.yaml** — раздел `runtime_spec` (contract/spec/validator/
  binding, `verified_against_deploy: false`); `package_version` → 2.21.0.

## [2.20.0] — 2026-07-15

**Постура безопасности** — сфокусированный проход по 13 областям безопасности: карта
«что есть → пробел → статус» как данные, валидатор drift на неё, закрыт самый ценный
реальный пробел (аудит-лог действий ИИ) кодом, остальное — честные политики.

### Added
- **governance/security-posture.yaml** — машиночитаемая карта по 13 областям (роли/права,
  ПДн, утечки, prompt-injection, секреты, аудит, human-in-the-loop, MCP/инструменты,
  red-team/evals, инциденты/kill-switch, TTL данных, test/prod, поставщики) со статусом
  (implemented/partial/declared/roadmap), severity и evidence (реальные файлы).
  Итог: 6 implemented, 4 partial, 3 declared.
- **governance/security-policies.md** — политики по пробелам: аудит-лог, подключение
  MCP/инструментов, kill-switch/инциденты, TTL/удаление данных, test/prod, контроль
  поставщиков и закрытого контура. Честно помечено, что политика, а что уже код.
- **validation/validate_security_posture.py** — проверяет форму постуры и что каждый
  evidence-путь резолвится (drift: постура не может врать о наличии контроля). Selftest + CI.
- **Аудит-лог действий ИИ (код):** orchestrator пишет append-only
  `.ai/runtime/interaction-log.jsonl` (ts/workflow/задача/статус/гейты/провайдер);
  секреты/сырые данные не пишутся. Закрывает самый ценный пробел области audit-log.

### Changed
- manifest.security_policies: posture/validator/policies/audit_log; package_version 2.20.0.

### Честная граница
6 из 13 областей — implemented, 4 partial, 3 — declared (политика написана, автоматический
enforcement — roadmap: MCP safe-connect, kill-switch постоянного агента, TTL, test/prod,
формальный vendor-review). Постура прямо показывает, где механизм, а где пока правило.

## [2.19.0] — 2026-07-15

**Eval-покрытие 51/51 + усиленный валидатор** — закрыт P1 ре-аудита: eval-кейсы были у
23 из 51 агента, а валидатор проверял только НАЛИЧИЕ файла. Теперь покрытие полное, а
проверка смотрит на структуру.

### Added
- **eval-кейсы для 28 оставшихся агентов** (evaluations/agents/) — по 3 кейса каждый
  (нормальный / граничный / отказ-передача), выведенные из роли агента и инвариантов
  кита (writer ≠ judge, честные декларации, scope control, human approval). Покрытие 51/51.

### Changed
- **validation/validate_agent_evals.py** усилен: помимо наличия файла проверяет
  **структуру** (≥3 кейса, ≥3 Expected/Forbidden) — для изменённых агентов и в режиме
  `--all` (структура всех + отчёт покрытия по реестру). CI-шаг `--all` + selftest.
- CI/AGENTS.md: шаги eval-структуры и покрытия.

### Честная граница
Валидатор проверяет **структуру и покрытие**, но по-прежнему НЕ прогоняет модель на
кейсах (это оффлайн-контракт, не live-evaluation). Кейсы написаны по ролям и инвариантам;
их качество — под ревью, как и любой контент. Прогон кейсов живой моделью — отдельный шаг
(в связке с живым оркестратором v2.18).

## [2.18.0] — 2026-07-15

**Живой оркестратор** — generic-orchestrator получает провайдер-адаптер к реальной
модели: полный путь «живая модель → стадии → принудительные гейты → единый статус»
становится исполнимым, а не только mock. Второй фундаментальный рубеж ре-аудита.

### Added
- **tools/orchestrator.py: провайдер-адаптеры** `anthropic` и `openai` — вызывают
  реальный API по ключу из **env** (stdlib urllib, сеть через системный прокси).
  CLI: `run … --provider anthropic|openai [--model …]`. По умолчанию — `mock`
  (офлайн, детерминированный: CI/selftest офлайн).
- Честный фолбэк: **без ключа — явная ошибка, а не тихий mock** (иначе «живой» прогон
  был бы фикцией). Selftest покрывает: mock по умолчанию, живой без ключа → ошибка,
  неизвестный провайдер → ошибка.

### Changed
- `registry/runtimes.yaml`: generic-orchestrator.live_provider объявлен честно —
  `status: implemented`, но **`verified_against_live_api: false`** (в среде разработки
  ключа не было — против реального API не прогонялось); `no_secrets: true`.
- docs/WALKTHROUGH: как включить живую модель (`--provider`, ключ из env).

### Честная граница (важно)
Адаптеры написаны и покрыты офлайн-selftest'ами, но **не проверены против реального
API** (в этой среде не было ключа/подтверждённого сетевого прогона). До первого
успешного живого прогона с ключом это — «implemented, not battle-verified».
Параллелизм по-прежнему нет (sequential-only), human-approval гейты — за человеком.

## [2.17.0] — 2026-07-15

**Единый продуктовый путь** — два прежде раздельных контура (прогон workflow и Feature
Blueprint, с разными id и статусами) связаны ОДНОЙ сущностью и ОДНИМ статусом. Закрывает
P1 ре-аудита «две хорошие подсистемы, а не один продукт».

### Added
- **tools/workitem.py + schemas/workitem.schema.json** — сущность WorkItem: один id
  (= id фичи) связывает routed workflow, Feature Blueprint (`features/<id>/`) и прогон
  оркестратора. `start` маршрутизирует (ai_route) и создаёт запись
  `features/<id>/workitem.yaml`; `status` выводит **единый статус** детерминированно из
  gate_executor + run_report. Selftest + шаг CI.
- **Единый статус (4 действия):** `done` / `blocked` / `needs_human_decision` /
  `needs_more_evidence`. Приоритет: реальный провал гейта > решение человека > нехватка
  доказательств > готово. Не два разных статуса (прогон vs blueprint), а один.

### Changed
- **commands/task/ai-start-task.md** — единственная точка входа теперь создаёт WorkItem
  (routing → blueprint → прогон под одним id) и подводит единый статус.
- manifest: секция `unified_product_path`; package_version 2.17.0.

### Честная граница
WorkItem связывает контуры и подводит итог **детерминированно**; он НЕ запускает живую
модель (это runtime/orchestrator, а generic-orchestrator пока mock) — заполнение blueprint
и вердикты ревьюеров остаются за исполнителем. Второй рубеж (живая модель + оркестратор)
остаётся заявленным, не закрытым.

## [2.16.0] — 2026-07-15

**Стабилизация ядра** — по итогам внешнего ре-аудита закрыты реальные дыры в главной
гарантии продукта (обход гейтов, бездоказательный evidence, рассинхрон контрактов) +
выпуск накопленных на main изменений (16 коммитов сверх тега v2.15.0 не доезжали до
child, т.к. VERSION не менялся).

### Fixed (integrity)
- **bypass_policy: forbidden теперь соблюдается.** `gate_executor.override_effective`:
  override НЕ снимает блок с гейта, где `bypass_policy: forbidden` (intake, security,
  implementation_verification); разрешён только при `override_policy.allowed: true`
  с субъектом и причиной; без явной политики — обход запрещён. Раньше любой
  override с by+reason обходил любой блокирующий гейт (нарушение основной гарантии).
  Selftest, который закреплял старое поведение, переписан.
- **Reviewer «pass» больше не фабрикует evidence.** `collect_evidence`: словесный
  вердикт ревьюера засчитывается как доказательство ТОЛЬКО для ai-review гейтов;
  детерминированные (build/lint/typecheck/tests) и human гейты требуют реальных
  фактов, а не строки «status: pass». «Evidence, а не слова» восстановлено.
- **Contract-противоречие у `requirements`** (одновременно bypass_policy: forbidden и
  override_policy.allowed) снято в пользу overridable-with-human.

### Added
- **validation/validate_workflow_gates.py** — валидатор согласованности workflow↔gate:
  гейт из quality_gates обязан числить workflow в applicability; WARN о применимых
  blocking-гейтах, не включённых в workflow. CI-шаг. Раньше CI это не ловил.

### Changed
- `implementation_verification.applicability` += VISUAL, ANALYTICS (они его используют).
- **PRODUCT.quality_gates** += `implementation_verification` — PRODUCT больше не может
  завершиться, не доказав сборку/тесты.
- Выпуск main как 2.16.0 (VERSION/manifest/CHANGELOG) — фиксы доезжают до child.

## [2.15.0] — 2026-07-15

**Замыкание контура: «провода подключены к механизмам».** Релиз соединяет уже
построенные части в рабочий путь установки/исполнения и приводит декларации в
соответствие реальности. Без бампа версии автообновление child'ов не увидело бы
эти фиксы (сравнивается `installed_version` с `VERSION`).

### Fixed — основной путь установки/обновления
- **`init` больше не ломает собственную валидацию сразу после установки:**
  подставляет актуальную версию пакета и совместимый SemVer-диапазон в `.ai-ops.yaml`
  (раньше оставалось `1.1.0`/`<2.0.0`, а provenance писался версией пакета).
- **Runtime подключён:** `init` генерирует и устанавливает команды в
  `.claude/commands/` (`command_loading` из `runtimes.yaml`), а не только в
  `.ai/generated/`, где раннтайм их не ищет.
- **`update` реально проверяет `allowed_version_range`** и блокирует несовместимый
  переход (раньше `compatibility` был захардкожен `compatible`).
- **`update` реально исполняет цепочку миграций** (`up.py`) и помечает applied
  только по факту; при падении — откат managed из backup.
- **rollback-safe `update`:** провал smoke-валидаторов откатывает managed-слой и
  версию из backup.
- **scheduled workflow уважает `parent.auto_update`:** по расписанию PR открывается
  только при `true`; ручной запуск — всегда.
- **shipped-скиллы не теряются молча:** локальная правка сохраняется в
  `.ai/runtime/backups/skills/<id>/` с предупреждением перед перезаписью.

### Added — исполнение и маршрутизация
- **Gate executor** (`tools/gate_executor.py`): резолвит `quality_gates` контракта,
  классифицирует гейты (deterministic / ai-review / human-approval), эмитит
  machine-readable результат по схеме; невыполненный блокирующий гейт → `fail`.
- **Оркестратор блокирует по гейтам:** не ставит `done`, пока блокирующие гейты
  не выполнены (`GateReport.json`, статус `blocked` + `unmet_gates`).
- **Workflow-контракт `CRITICAL`:** critical risk честно переопределяет task_type
  (routing возвращает `CRITICAL` с обязательным human approval); контракт с
  независимыми security/code review и стадией one-way-door.

### Changed — честность деклараций
- **`adapter_depth` у runtime-адаптеров** (`executing` / `generated-commands` /
  `manual-assisted`) + машинная проверка: `claude-code`/`codex` честно помечены как
  `generated-commands`, реальное исполнение — у `generic-orchestrator`.
- **drift-control:** валидатор синхронности чеклиста `AGENTS.md` ↔ CI; installer
  e2e-selftest (`init` → child-валидатор); проверка `adapter_depth`.

### Tests
- Eval-кейсы критической цепочки агентов (intake → context → requirements → plan →
  plan-review → integrate → verify → code-review), по 3 сценария на роль.

## [2.14.1] — 2026-07-13

**Курируемое из репозиториев A. Karpathy** — взято только то, что не ломает миссию и
не вендорится в ядро (кит строит продукты на LLM, а не обучает модели).

### Added
- **rendergit** в `registry/tools.yaml` (status: declared, BSD0) — «репозиторий →
  одностраничный HTML с навигацией/подсветкой + LLM-view»; браузерная карта архива,
  дополняет текстовый FILE_INDEX.md.
- **registry/skills-catalog.yaml → model_training** — учебно-тренировочные референсы
  на редкий случай «делаем свою модель» (nn-zero-to-hero, nanoGPT, nanochat, LLM101n,
  llm.c). Declared, на уровне child, китом не исполняются и не вендорятся.

### Отклонено осознанно
- llm-council (интеграция OpenRouter + параллельные модели против sequential-only) —
  взят только паттерн «коллегия судей», как идея; autoresearch (автономный само-меняющий
  цикл) — противоречит human-approval/one-way-door и дублирует experiment-designer+eval.

## [2.14.0] — 2026-07-13

**Онбординг и параллельные сессии** — объясняем ценность кита простым языком при
установке и фиксируем правила ускорения несколькими сессиями.

### Added
- **docs/ONBOARDING.md** — что даёт AI Ops Kit простым языком (ценности/преимущества,
  «с чего начать», куда смотреть дальше). Для продакта/команды, без терминов.
- **docs/parallel-sessions.md** — как безопасно вести несколько сессий Claude на один
  репозиторий: правило «одна сессия = ветка = область = PR», изоляция контейнеров,
  общий source-of-truth правит одна сессия, кит страхует на CI. Честно: оркестратор
  sequential-only, параллелизм создаёт пользователь.

### Changed
- **installer/ai_ops.py**: при `init` в child кладётся `AI-OPS-ONBOARDING.md` (не
  затирая собственный ONBOARDING репозитория) и печатается краткая сводка ценности —
  онбординг появляется в момент подключения кита.
- package_version 2.14.0.

## [2.13.0] — 2026-07-13

**Пользовательская документация и демо-видео** — два поставляемых скилла для того, что
нужно почти каждому продукту. Оба построены на **реальном механизме** кита (Playwright из
skills/e2e-browser-testing умеет и скриншоты, и запись экрана), а не на обещаниях.

### Added
- **skills/user-documentation/SKILL.md** — понятная польз. документация со скриншотами:
  структура Diátaxis; скриншоты снимаются детерминированно из реального UI на классах
  Device matrix и **переснимаются при изменении интерфейса** (не расходятся с продуктом);
  реальный путь к ценности, состояния Empty/Loading/Error/Success, язык пользователя.
  Чек-лист rules/documentation/user-docs.yaml.
- **skills/product-demo-video/SKILL.md** — короткий обход продукта: сториборд →
  закадровый сценарий → запись экрана реального UI (Playwright, webm). Честная граница:
  кит выдаёт сториборд+сценарий+сырой screen-recording; полировка/монтаж — опционально
  внешним рендером (Remotion, каталог), не ядром. Чек-лист rules/content/demo-video.yaml.

### Changed
- manifest: skills.shipped += user-documentation, product-demo-video (итого 8 shipped);
  package_version 2.13.0.
- Проводка opt-in: ADOPTION.user-docs → user-documentation; ADOPTION.adoption-plan →
  product-demo-video.

## [2.12.0] — 2026-07-13

**Review-этикет, каталог внешних скиллов, agnix** — курируемо из второго набора (13
скиллов). Ключевой принцип: ядро остаётся стек-агностичным, стек-специфичные и
сторонние скиллы **декларируются в каталоге и ставятся на уровне child**, а не
вендорятся в ядро.

### Added
- **rules/quality/code-review-etiquette.yaml** (адапт. obra/superpowers
  requesting/receiving-code-review) — как готовить PR к ревью и как отвечать на
  замечания (принять/обсудить/отклонить с аргументом). Подключён к гейту code_review.
- **registry/skills-catalog.yaml** — каталог внешних скиллов (status: declared, ставятся
  на уровне child): стек — react-best-practices/web-design-guidelines (vercel),
  postgres-best-practices (supabase), shadcn-ui (google); продуктовые/контентные —
  visual-explainer, writing-guru, revealjs (по запросу — чтобы продакт мог подключить
  при необходимости). Ядро не биасится под стек.
- **agnix** в registry/tools (status: declared) — линтер AI-конфигов (SKILL.md/CLAUDE.md,
  156 правил); дополняет validate_references и skill-authoring. Не вендорится.

### Changed
- manifest: registries.skills_catalog; package_version 2.12.0.
- гейт code_review получил checklist; skill-authoring — пункт про опциональный линтер.
- NOTICE: атрибуции obra/superpowers, agnix и каталогизированных внешних скиллов.

### Отклонено осознанно
- subagent-driven-development, dispatching-parallel-agents (конфликт с честной
  декларацией sequential-only); sentry-workflow, postgres read-only (интеграции —
  «не берём»); remotion (вне миссии); вендоринг стек-гайдов в ядро (агностичность).

## [2.11.0] — 2026-07-13

**Frontend & E2E** — два opt-in скилла из внешнего набора (курируемо: из 10
предложенных взяты два, закрывающие реальные пробелы; остальные отклонены как дубли
или вне миссии). Плюс конвенция авторинга скиллов.

### Added
- **skills/frontend-design/SKILL.md** (адапт. из anthropics/claude-code frontend-design)
  — создание отличающегося UI: план → критика против AI-клише → HTML/CSS; из токенов
  DesignSystem; a11y и адаптивность заложены при создании. Закрывает пробел «генерация
  UI» (ревью у нас уже было). Чек-лист rules/design/frontend-design.yaml.
- **skills/e2e-browser-testing/SKILL.md** (адапт. из lackeyjb/playwright-skill, MIT)
  — e2e/визуальные проверки в браузере на **viewport-матрице** из DesignSystem.
  Замыкает пункт e2e-viewport-matrix из responsive-baseline (в v2.6 объявлен, механизма
  не было). Чек-лист rules/quality/e2e-baseline.yaml.
- **rules/meta/skill-authoring.yaml** — конвенция авторинга скиллов (из anthropics/skills
  skill-creator; сам скилл не вендорился). validate_references теперь проверяет, что у
  каждого shipped-скилла есть frontmatter name+description.

### Changed
- manifest: skills.shipped += frontend-design, e2e-browser-testing; authoring_convention;
  package_version 2.11.0.
- Проводка (opt-in): VISUAL.implementation → frontend-design; VISUAL.verify →
  e2e-browser-testing. responsive-baseline e2e-viewport-matrix ссылается на скилл.
- validate_references: проверка frontmatter shipped-скиллов. NOTICE: 3 новых атрибуции.

### Отклонено осознанно (из 10 предложенных)
- prompt-master (дублирует AI Product Pack), mcp-builder («интеграции не берём»),
  superpowers (целый фреймворк, дублирует workflow/gate), ai-website-cloner (вне миссии,
  IP-риски), visual-explainer / writing-guru / revealjs (nice-to-have / вне миссии).

## [2.10.0] — 2026-07-13

**Decision Intelligence** (team-os-toolkit Ф3, MIT) — как команда принимает решения,
становится частью системы: не журнал «решили X», а способ мышления с калибровкой.
Ядро — recommendation-first: система не выдаёт вердикт, пока человек не сформулировал
позицию; развивает мышление команды, а не заменяет его. Строго opt-in.

### Added
- **skills/decision-support/SKILL.md** — recommendation-first (жёсткий гейт: нет
  рекомендации человека → нет вердикта), классификация обратимости (two-way vs
  one-way door), one-way-door бриф на эскалацию (AI не решает необратимое сам),
  калибровка принципов (confidence/recurrence/counterexamples/review_date),
  связь с systems-thinking (constraint → contradiction → decision).
- **decisions/registry.yaml + schemas/decisions-registry.schema.json +
  validation/validate_decisions.py** — реестр: принципы (proposed/ratified/retired,
  scope, калибровка), эпизоды (вопрос/решение/причина/обратимость), исходы.
  Валидатор проверяет целостность (уникальность id, статусы, supersedes/derived_from
  резолвятся, retired требует reason) и WARN'ит «принцип из одного случая». Селфтест.
  Реестр кита задогфужен реальными решениями сессии.
- **rules/thinking/decision-support.yaml** — 10 машиночитаемых гейтов.
- **Workflow DECISION** (десятый контракт): intake → recommendation (writer) →
  principle-review (product-reviewer, read-only judge) → one-way-door-brief
  (human approval) → decision-record → outcome-review → memory. writer ≠ judge.
- Шаблоны templates/decisions/{DecisionEpisode, OneWayDoorBrief, OutcomeReview}.md.
- Гейт **decision_quality** (non-blocking до обкатки).

### Changed
- manifest: skills.shipped += decision-support; workflows.extended += DECISION;
  секция decision_intelligence; package_version 2.10.0.
- product-reviewer ведёт principle-review в DECISION (скилл decision-support).
- CI: шаг validate_decisions. NOTICE: team-os-toolkit покрывает Ф3.
- ROADMAP: Ф3 выполнена; Ф4 Runtime/Robin остаётся спекой (постоянного runtime нет).

## [2.9.0] — 2026-07-13

**Knowledge Integrity + Governance** — интеграция механики team-os-toolkit (MIT):
drift-control, свежесть знаний и границы данных. ~60% идей репозитория у кита уже были
(registry как SoT, Knowledge Graph, memory-loop, human-approval) — взята только
недостающая механика; структурный reorg отклонён (ковенант: аддитивно, без breaking).
Drift-control наведён сначала на сам пакет и закрыл латентную дыру: ссылки uses_skills/
checklist/owner, добавленные в 2.7–2.8, не проверялись ничем.

### Added
- **validation/validate_references.py** — целостность ссылок пакета: каждый `uses_skills`
  → shipped-скилл (или внешний скилл раннера), `checklist:`/`source_of_truth:` →
  существующий файл, `owner`/`writer` в workflow → агент реестра, `quality_gates[*]` →
  gate реестра. Селфтест с искусственным сломом (гейт видят падающим). Шаг CI.
- **knowledge/claims.yaml + validation/validate_claims.py** — контракты «документация
  утверждает о коде»: типы file-exists, symbol-exists, enum-values. Расхождение
  документа с кодом становится видимым (падает в CI). Селфтест ловит намеренный drift.
  В child claims живут в `.ai/project/knowledge/claims.yaml` и ссылаются на код продукта.
- **rules/core/FreshnessPolicy.md + validation/validate_freshness.py** — классы
  устаревания (stable/evolving/volatile; единый термин `stability`, без второго `tier`),
  сроки по умолчанию (14/90/∞), advisory-предупреждение о протухших документах.
  Селфтест на фиксированной дате. **context/now.md** — датированный снимок (концепт now.md).
- **governance/information-boundaries.md** — что можно/нельзя хранить в репозитории и
  передавать внешним моделям (5 категорий; критично для гос-контекста).
- Гейты **knowledge_integrity** и **knowledge_freshness** (оба non-blocking до обкатки).

### Changed
- manifest: секции `knowledge_integrity` и `governance`; package_version 2.9.0.
- CI: шаги validate_references / validate_claims / validate_freshness.
- ROADMAP: интеграция team-os-toolkit — Ф1–2 выполнены; Ф3 Decision Intelligence и
  Ф4 Runtime/Robin (спека, не реализация) запланированы; reorg/adapters/Robin-бот отклонены.

### Fixed
- **eval-кейсы product-analyst и solution-architect** — эти core-агенты были изменены
  в v2.8 (ссылки на скиллы), но не имели eval-файлов; eval-гейт справедливо падал.
  Добавлены evaluations/agents/{product-analyst,solution-architect}.md (по 3 кейса).
  Дыру вскрыл сам тематический прогон v2.9 (integrity), что и требовалось.

## [2.8.0] — 2026-07-13

**Systems Thinking (два скилла)** — дисциплины системного мышления как opt-in скиллы:
находить главное ограничение и устранять компромиссы, а не оптимизировать всё подряд и
не искать «золотую середину». Из шести скиллов исходного набора взяты два самых
самодостаточных и не пересекающихся с китом; leverage — кандидат на потом; why-tree
(multi-agent, дублирует deep-research/INSIGHTS) и stockflow-builder (генерация
HTML-симуляторов) отклонены осознанно.

### Added
- **skills/system-constraint-analysis/SKILL.md** — теория ограничений Голдратта: гейт на
  цель/единицу пропускной способности, извлечение потока, классификация системы
  (потоковая/demand-constrained/исследовательская), локализация ОДНОГО ограничения,
  презумпция политики, 5 фокусирующих шагов (Exploit/Subordinate до Elevate), оценка по
  T↑/I↓/OE↓. Адаптировано из constraint-finder (MIT), инструмент-агностично.
- **skills/contradiction-resolution/SKILL.md** — ТРИЗ: техническое + физическое
  противоречие, классификатор структура/физика (не фабриковать разрешение закона), IFR,
  4 разделения + 40 приёмов, гейт фальсификации «растворение vs релокация стоимости».
  Адаптировано из triz-dissolve (MIT).
- **rules/thinking/constraint-analysis.yaml** (10 пунктов) и
  **rules/thinking/contradiction-resolution.yaml** (9 пунктов) — машиночитаемые гейты к
  скиллам; находки ссылаются на id.

### Changed
- **manifest.skills.shipped**: +2 скилла (реестр поставляемых китом скиллов). Инсталлятор
  (v2.7) раскладывает их в child `.claude/skills/` автоматически.
- Проводка (opt-in): INSIGHTS.insight-synthesis → `uses_skills: [system-constraint-analysis]`;
  ENGINEERING/PRODUCT.specification → `uses_skills: [contradiction-resolution]`.
  Агенты product-analyst и solution-architect ссылаются на соответствующие скиллы.
- NOTICE.md: атрибуция systems-thinking-skills (MIT).

## [2.7.0] — 2026-07-13

**Product Session Review** — первый скилл, который поставляет сам кит. Дисциплина
доказательного разбора сессионных записей и поведенческих данных: вывод держится на
триангуляции (реплей + база + исходник), а не на впечатлении от одного реплея. Строго
opt-in — включается, только когда у продукта инструментированы session-replay/
поведенческие данные.

### Added
- **skills/product-session-review/SKILL.md** — адаптированная методология
  (из BayramAnnakov/clarity-session-review, MIT): инструмент-агностична (Clarity,
  FullStory, Hotjar, PostHog, LogRocket…), Clarity-специфика убрана. 8 принципов
  (вопрос до реплея, идентичность до интерпретации, триангуляция, таймлайн ≠ реплей,
  координаты доказательства, счёт людей а не сессий, пройди шаг сам, аудит показанного
  UI), конвейер с adversarial refute-проходом и dead-click анализом, evidence appendix
  с уровнями MEASURED/OBSERVED/INFERRED, cold-read gate, gated blind spots.
- **rules/research/session-review.yaml** — machine-readable чек-лист (15 пунктов) к
  скиллу; находки ссылаются на id. Критичные: question-before-replay, bots-stripped,
  triangulated, count-people, refute-pass, evidence-coordinates, blind-spots-gated.
- **manifest: skills.shipped** — реестр скиллов, поставляемых китом.

### Changed
- **installer/ai_ops.py**: init и update синхронизируют поставляемые скиллы в
  `<child>/.claude/skills/<id>/` (место загрузки скиллов раннером), драйвится
  manifest.skills.shipped.
- **INSIGHTS.data-collection** (`registry/workflows.yaml`): `uses_skills: [product-session-review]`.
- **user-researcher**: применяет скилл при разборе поведенческих данных/записей сессий.
- NOTICE.md: атрибуция clarity-session-review (MIT).

## [2.6.0] — 2026-07-10

**Responsive by Default** — адаптивность под целевые устройства перестаёт зависеть
от того, вспомнил ли о ней человек: целевая матрица устройств определяется один раз
на продукт, дальше процесс проверяет её сам (шаблоны требуют, blocking-гейт проверяет,
e2e на viewport-матрице ловит регрессии).

### Added
- **rules/design/responsive-baseline.yaml** — machine-readable чек-лист адаптивности
  (12 пунктов): матрица устройств определена, mobile-first, fluid layout, breakpoints
  из токенов, touch-цели >= 44px, независимость от hover, масштабирование текста,
  адаптивные медиа, overflow внутри контейнеров, safe areas/ориентация, состояния
  Empty/Loading/Error/Success на всех классах, e2e по viewport-матрице.
  Критичные пункты: device-matrix-defined, fluid-layout, touch-targets, input-modality.
- **Device matrix в context/product/DesignSystem.md** — источник истины по целевым
  классам устройств продукта (класс, min viewport, ввод, обязателен ли); заполняется
  один раз, все проверки адаптивности идут против него. Явный opt-out класса —
  только с причиной.

### Changed
- Гейт **ux_review** (blocking): required_evidence дополнен
  `device_matrix_defined` — фича не проходит design-review, пока матрица устройств
  не определена в DesignSystem.
- Пункт `responsive` в rules/design/ux-heuristics.yaml: severity critical,
  ссылается на детальный чек-лист responsive-baseline.yaml.
- Шаблоны templates/ux/UXFlow.md и ScreenStates.md: секции Responsive требуют
  описания поведения по всем классам Device matrix, не только desktop
  (пустой скелет по-прежнему PROBLEM в run_report).

## [2.5.0] — 2026-07-09

Сбор данных о работе кита в child-репозиториях становится системным: история
прогонов переживает эфемерные сессии/CI и превращается в «метрики эффекта»
(последняя инженерная зона внешнего ревью).

### Added
- **run_report --record [dir]** — дописывает компактный срез отчёта (дата, вердикт,
  стадия, покрытие, число находок) в `.ai/project/report-history/<фича>.jsonl`
  child-репозитория (зона project — коммитится с PR). Корень child находится
  автоматически по .ai-ops.yaml.
- **tools/effect_metrics.py** — детерминированные метрики эффекта по истории:
  на фичу — PROBLEM-rate, последний вердикт/стадия, динамика покрытия,
  days-in-flight, продвижение по стадиям; агрегат — PROBLEM-rate, медиана дней
  до retrospective. Честность встроена: фичи с <3 срезов помечаются
  insufficient-data, при <3 фич с достаточной историей — явное «baseline не готов»
  (условие из memory соблюдается кодом, не дисциплиной). Selftest + шаг CI.
- QUICKSTART §3a: запись срезов перед PR и чтение метрик.

## [2.4.0] — 2026-07-09

**AI Product Pack** — команда, workflow и инструменты для продуктов с LLM/агентной
частью, где качество и скорость ИИ в целевом сценарии — отдельная дисциплина.
Строго opt-in: preset ai-product + task_type фичи; продуктам без AI-части ничего
не добавляется.

### Added
- **Preset ai-product** (opt-in): llm-architect (архитектура AI-возможности —
  model_class через routing, контекстная стратегия, числовые бюджеты
  качества/latency/стоимости, деградация), ai-feature-engineer (eval-driven:
  golden set до реализации, промпты как код), ai-red-teamer (адверсариальные
  проверки), ai-evaluator (переезд из software-product). Реестр: 48 -> 51,
  все с eval-кейсами.
- **Workflow AI_FEATURE** (девятый контракт): intake -> target-scenario ->
  golden dataset (ДО реализации) -> implementation -> offline-evals (ai_eval) ->
  red-team (ai_red_team) -> verify -> memory. Writer ≠ judge дважды: строит
  ai-feature-engineer, качество меряет ai-evaluator, ломает ai-red-teamer.
  Маршрутизация по task_type (ai-feature, llm-integration, rag-pipeline,
  agent-capability, prompt-change, model-migration) — подхватилась data-driven
  роутером автоматически, закреплена selftest-сценарием.
- **Гейт ai_red_team** (non-blocking до обкатки, applies_when: LLM-компонент) +
  машиночитаемый **rules/ai/red-team-checklist.yaml** на основе OWASP Top 10 for
  LLM Applications (инъекции прямые/косвенные, утечки PII/промпта, excessive
  agency, RAG-отравление, unbounded consumption, jailbreak).
- **Шаблоны**: AIFeatureSpec (целевой сценарий + бюджеты числами), GoldenDataset
  (распределение, edge cases, версионирование), RedTeamReport (находки по id
  пунктов чек-листа).
- **Открытый инструментарий как опции** (registry/tools.yaml, status: declared;
  связь CLI-and-protocol, как с OpenSpec; карта — rules/ai/EvalTooling.md):
  promptfoo (MIT — evals-as-config + red team), DeepEval (Apache-2.0 —
  pytest-style LLM-тесты), Ragas (Apache-2.0 — RAG-метрики), Langfuse (OSS —
  online-наблюдаемость: качество/стоимость/latency, вход для INSIGHTS),
  garak (Apache-2.0 — сканер уязвимостей LLM).

### Fixed
- README: устаревшие «38 агентов» и «OpenSpec выключена по умолчанию»;
  AGENTS.md: счётчик агентов.

## [2.3.1] — 2026-07-09

Закрытие документационных зон внешнего ревью (демонстрация, UX CLI, adoption-гайд).

### Added
- **docs/QUICKSTART.md** — первый день с китом: установка, первая фича, вердикт
  одной командой, проверенный CI-джоб для child + таблица типовых ошибок
  (все — из реальных прогонов).
- **docs/WALKTHROUGH.md** — воспроизводимый сквозной сценарий за 15 минут
  (обезличенный первый боевой прогон); команды проверены выполнением.
- **docs/adoption-guide.md** — гайд внедрения по ролям (CTO / PM / EM / QA /
  Platform): что даёт, с чего начать, зона ответственности.
- README: блок «Начать здесь».

### Fixed
- run_report: незаполненный скелет достигнутой стадии теперь PROBLEM независимо
  от status (раньше — только при done/draft; расхождение с generate_artifacts check
  вскрыто прогоном walkthrough). Selftest дополнен.

## [2.3.0] — 2026-07-09

Оба изменения обоснованы данными первого боевого прогона (ii-sreda,
memory/lessons-learned/2026-07-09-first-child-run-insights.md). Аддитивно.

### Added
- **Профили blueprint lean/full**: на прогоне 75% артефактов full-профиля были
  declined — для прототипов/MVP введён lean-профиль (discovery / definition /
  delivery / analytics / retrospective, 10 скелетов вместо 24). Скоуп объявляется
  явно полем feature.profile (не молчаливый пропуск); стадии вне профиля можно
  добавлять точечно. `generate_artifacts.py new ... --profile lean`;
  шаблон FeatureBlueprint.lean.yaml; схема и валидатор понимают профиль
  (lean: ux/architecture не требуются; full: поведение прежнее).
- **validate_cross_artifacts.py** — кросс-артефактная консистентность (идея —
  Spec Kit `analyze`): события из dashboard-spec (Source events, Funnels) обязаны
  быть объявлены в tracking plan; dashboard без tracking plan — PROBLEM;
  отсутствие артефактов или нераспарсиваемая таблица — мягкая деградация
  (skip/WARN, не ложный fail). Встроен в run_report (находки попадают в общий
  вердикт) и в CI; пример express-checkout дополнен согласованным dashboard-spec.

## [2.2.0] — 2026-07-09

Ответ на вопрос первого боевого прогона (child ii-sreda): «как понять, хорошо
прошёл прогон или плохо». Слой «Метрики эффекта» в минимальной честной версии.

### Added
- **tools/run_report.py — оценка прогона фичи одной командой**
  (`run_report.py <feature-dir> [--graph graph.yaml] [--json]`):
  валидность blueprint; покрытие стадий (заполнено / declined с причинами /
  скелеты / не начато); ловит артефакты, помеченные done, но оставшиеся
  незаполненными скелетами; сверяет blueprint с knowledge graph — если фича
  delivered-by (выпущена), а current_stage раньше release, честно сообщает
  «реальность обогнала blueprint»; напоминает про retrospective.
  Вердикт OK/WARN/PROBLEM (exit 1 при PROBLEM). Качество содержания артефактов
  оценивают ревьюеры (gates) — скрипт оценивает честность процесса.
  Selftest + шаг CI. Обкатан на реальном прогоне catalog-api-migration в ii-sreda:
  нашёл 2 PROBLEM (невалидный status в blueprint; выпуск при current_stage=definition)
  и 1 WARN (retro не заполнена).

## [2.1.1] — 2026-07-09

Патч: первый улов dogfooding — маршрутизация не знала о workflow, добавленных после MVP.

### Fixed
- **ai_route.py**: детальные task_type (ui-change, instrumentation,
  post-release-analysis, onboarding, bug-fix, ...) теперь маршрутизируются по
  `selection_criteria.task_type` из registry/workflows.yaml — единый источник истины,
  без дублирования в routing-policy. Раньше роутер знал только 4 MVP-имени, а
  fallback возвращал task_type как имя workflow — отдавал несуществующие маршруты
  (`workflow: "ui-change"` вместо VISUAL).
- Passthrough-fallback заменён явным дефолтом: неизвестный task_type -> ENGINEERING
  с причиной в reasons.
- +6 selftest-сценариев маршрутизации (VISUAL/ANALYTICS/INSIGHTS/ADOPTION/QUICK по
  selection_criteria, unknown -> default).
- Урок зафиксирован: memory/lessons-learned/2026-07-09-routing-unaware-of-new-workflows.md.

## [2.1.0] — 2026-07-09

**Курируемая интеграция research-пакета** (Product & Design Extension Pack):
взяты два слепых пятна v2.0 — измерение AI-фич и adoption — плюс discovery-исследование
и источники истины; дубли уже построенного отклонены. Всё аддитивно.

### Added
- **AI Feature Evals** — кит измерял своих агентов, но не AI-фичи для пользователей:
  агент ai-evaluator (read-only judge), rules/ai/EvalPolicy.md,
  templates/quality/AIFeatureEvalPlan.md, **blocking-гейт ai_eval** (task fidelity,
  faithfulness, guardrails, regression при смене модели/промпта; applies_when —
  только для фич с LLM/агентным компонентом).
- **Adoption как стадия**: агент adoption-manager, **контракт ADOPTION**
  (launch-readiness с проверкой событий live -> adoption-plan -> user-docs ->
  feedback-loop -> post-launch-review -> независимое ревью; learning_output required),
  стадия adoption в Feature Blueprint (схема/валидатор/генератор/шаблон),
  preset product-adoption, шаблоны LaunchPlan/AdoptionPlan/FeedbackLoop/PostLaunchReview.
- **Discovery-исследование**: агент user-researcher (Continuous Discovery, JTBD),
  templates/discovery/UserResearchPlan.md (story-based интервью) и AssumptionTest.md
  (RAT); правила Терезы Торрес в шаблоне OpportunitySolutionTree (product outcome
  в корне, 3-4 интервью до построения, приоритизация без effort).
- **Источники истины в context/product/**: DesignSystem.md (принципы, DTCG-токены,
  компоненты, voice) и MetricCatalog.md (семантический слой: каждая метрика определена
  ровно один раз); у gates design_system_usage и analytics_readiness — поле source_of_truth.
- Шаблоны ExperimentReadout (результат эксперимента с decision rule) и InAppContent
  (тексты интерфейса); rules/product/MeasurementBaseline.md.
- Реестр: 45 -> 48 агентов (все с eval-кейсами); 5 presets.

### Changed
- analytics_readiness: + required_evidence events_verified_live; applicability + ADOPTION.
- intake_completeness/documentation_updated: applicability + ADOPTION (и VISUAL/ANALYTICS
  для intake).
- UserGuide — Diátaxis-компас; DashboardSpec — каркасы North Star/HEART/AARRR со ссылкой
  на MetricCatalog.

## [2.0.0] — 2026-07-09

**Фаза 4 roadmap — платформа AI Product Operating System завершена** (VISION.md,
все фазы Ф1–Ф4 ✅). Breaking-изменений НЕТ: контракты остаются schema_version 1,
обновление — штатный `ai-ops update` (см. MIGRATION_GUIDE.md). Мажорная версия
отмечает завершение платформы, а не слом совместимости. Цикл замкнут:
Discovery → Delivery → Release → Measurement → Insights → Discovery.

### Added
- **Knowledge Graph**: registry/entities.yaml — словарь 15 типов сущностей
  (Goal → Initiative → Epic → Feature → ... → Insight) и 20 допустимых связей;
  schemas/knowledge-graph.schema.json (граф проекта — knowledge/graph.yaml в child);
  validate_knowledge_graph.py — ссылочная целостность, допустимость связей,
  существование blueprint у feature-узлов (+selftest, пример, CI).
- **Product Health**: schemas/product-health.schema.json (machine-readable отчёт) +
  tools/product_health.py — детерминированный расчёт Health Score
  (adoption/activation/retention/reliability/errors/performance/support_load,
  нормализация против target, веса, band healthy/warning/critical, findings).
  Интерпретация — за людьми и workflow INSIGHTS, не за скриптом.
- **Workflow INSIGHTS** (extended): data-collection → health-report (детерминированно)
  → insight-synthesis → insight-review (product-reviewer) → hypotheses-for-discovery
  (experiment-designer) → memory-capture (learning_output: required). Инсайты и
  гипотезы записываются в knowledge graph. Прозаический сценарий workflows/insights.md.
- manifest: registries.entities, workflows.extended += INSIGHTS.

### Changed
- Gates intake_completeness и evidence расширили applicability на новые workflow
  (VISUAL/ANALYTICS/INSIGHTS и INSIGHTS соответственно).
- README/ROADMAP/MIGRATION_GUIDE: фазы Ф1–Ф4 отмечены выполненными; зафиксировано,
  что пересмотр schema_version не потребовался.

## [1.5.0] — 2026-07-09

**Фаза 3 roadmap** (см. ROADMAP.md): генераторы. Скелеты артефактов создаются
детерминированно из единого источника (принцип 27); содержание пишут агенты стадий.

### Added
- **tools/generate_artifacts.py** — generator framework по Feature Blueprint:
  `new` (blueprint из шаблона), `scaffold` (скелеты недостающих артефактов, все стадии
  или одна), `add` (внеплановый артефакт, например эксперимент), `check` (drift-статус:
  edited / untouched-skeleton / template-updated; незаполненный скелет достигнутой
  стадии = fail). Хэши — в .generation.json. Selftest + шаг CI. Стадийные наборы
  шаблонов покрывают генераторы VISION.md: Discovery, PRD, UX, Analytics, Dashboard,
  Documentation, Release, Monitoring, Experiment, Retrospective.
- Шаблоны: templates/documentation/{UserGuide,FAQ,WhatsNew}.md,
  templates/task/Retrospective.md (результат vs метрики Discovery, уроки -> memory/,
  гипотезы следующего цикла).
- Дефолтный FeatureBlueprint.yaml расширен: documentation (4 артефакта),
  release (+release-checklist), retrospective с шаблоном. Полный scaffold — 24 скелета
  по 10 стадиям.

### Changed
- **Gates переведены в blocking**: discovery_completeness, ux_review,
  design_system_usage, analytics_readiness (их applicability целиком в
  PRODUCT/VISUAL/ANALYTICS). documentation_updated, release_safety,
  observability_readiness остаются non-blocking до обкатки в QUICK/ENGINEERING.

## [1.4.0] — 2026-07-09

**Фаза 2 roadmap** (см. ROADMAP.md): каждая зона ответственности получила независимого
ревьюера; Discovery — первоклассный этап PRODUCT. Всё аддитивно.

### Added
- **7 review-агентов** (agents/quality/, все read-only, с eval-кейсами в
  evaluations/agents/): product-reviewer, ux-reviewer, design-system-reviewer,
  analytics-reviewer, documentation-reviewer, observability-reviewer,
  architecture-reviewer. Реестр: 38 -> 45 агентов; presets product-discovery (+3)
  и software-product (+4).
- **UX-чек-листы как данные** (rules/design/): ux-heuristics.yaml (10 эвристик
  Nielsen + состояния экранов), accessibility-checklist.yaml (WCAG 2.2 AA),
  design-system-checklist.yaml. Находки ревью ссылаются на id пунктов.
- **Discovery-стадии в PRODUCT**: hypotheses (experiment-designer) и
  discovery-review (product-reviewer, read-only); gate discovery_completeness
  подключён к контракту.
- **Review-стадии в контрактах**: VISUAL — design-review (ux-reviewer),
  design-system-review, accessibility-review; ANALYTICS — analytics-review.

### Changed
- Gates фазы 1 переназначены на профильных ревьюеров (writer ≠ judge):
  discovery_completeness -> product-reviewer, ux_review -> ux-reviewer,
  design_system_usage -> design-system-reviewer (read-only),
  analytics_readiness -> analytics-reviewer (read-only),
  observability_readiness -> observability-reviewer (read-only).
  У ux_review и design_system_usage появилось поле checklist.

## [1.3.0] — 2026-07-09

**Фаза 1 roadmap к AI Product Operating System** (см. VISION.md, ROADMAP.md):
«Analytics/Design/Docs by Default» как контракты. Всё аддитивно; новые gates —
non-blocking до обкатки (перевод в blocking — фаза 3).

### Added
- **15 шаблонов артефактов** полного цикла: discovery (ProblemStatement, JTBD,
  Personas, Hypotheses, OpportunitySolutionTree), analytics (TrackingPlan, EventSchema,
  DashboardSpec), ux (UXFlow, ScreenStates, DesignReview), release (RolloutPlan,
  FeatureFlag, RollbackStrategy), monitoring (MonitoringSpec).
- **7 quality gates продуктового цикла** (non-blocking): discovery_completeness,
  ux_review, design_system_usage, analytics_readiness, documentation_updated,
  release_safety, observability_readiness.
- **Workflow-контракты VISUAL и ANALYTICS** (заявлены post-MVP с v0.2): стадии,
  агенты, gates, memory-capture; runtime-команды генерируются автоматически
  (ai-visual, ai-analytics). Прозаический сценарий workflows/analytics-instrumentation.md.
- **Feature Blueprint v1**: schemas/feature-blueprint.schema.json,
  валидатор validate_feature_blueprint.py (+selftest, шаг CI), шаблон
  templates/blueprint/FeatureBlueprint.yaml, живой пример
  examples/feature-blueprint-demo/express-checkout. Правило: артефакты достигнутых
  стадий существуют либо явно declined с причиной.
- manifest: workflows.extended [VISUAL, ANALYTICS].

## [1.2.0] — 2026-07-09

Улучшения для работы команд: автообновление child-репозиториев, замкнутый цикл
repository memory, вход для агентов (AGENTS.md), eval-гейт и автоматический релизный
процесс. Всё аддитивно и обратно совместимо.

### Added
- `templates/ci/ai-ops-update.yml` — CI-workflow автообновления для child-репозиториев:
  раз в день сверяет `installed_version` с VERSION parent-пакета и открывает PR с
  обновлением и отчётом. `ai-ops init` устанавливает его в `.github/workflows/` child.
- Стадия `memory-capture` (owner — repository-memory-curator) в контрактах ENGINEERING
  и PRODUCT: опубликовать запись в memory/ или явно отказаться с причиной в TaskState;
  для incident-resolution запись в `memory/incidents/` обязательна. Контракт описан
  в `memory/README.md`.
- `AGENTS.md` — вход для AI-агентов: карта репозитория, обязательные проверки,
  инварианты, релизный процесс; `CLAUDE.md` ссылается на него.
- `FILE_INDEX.md` пересобран: полный (234+ файлов вместо 149), с аннотациями разделов —
  карта в духе llms.txt.
- `validation/validate_agent_evals.py` + шаг CI — eval-гейт: добавленный/изменённый
  агент обязан иметь кейсы в `evaluations/agents/<agent-id>.md`; существующие агенты
  без кейсов не блокируются.
- `.github/workflows/release.yml` — автоматический выпуск: пуш в main с изменением
  VERSION создаёт тег vX.Y.Z и GitHub Release из раздела CHANGELOG.

### Changed
- Честная декларация generic-orchestrator: `preferred_mode: sequential`,
  `parallel_execution: unsupported` (parallel scheduler — planned, в коде его нет).
  Правило `execution_mode` в routing-policy и `ai_route.py` теперь берут режим из
  `preferred_mode` рантайма; ожидания selftest обновлены (orchestrated -> sequential
  для generic-orchestrator).

## [1.1.0] — 2026-07-08

### Changed
- OpenSpec теперь **включён по умолчанию** (`spec_protocol.enabled_by_default: true`,
  в заготовке child-конфига `openspec.enabled: true`). Выключается в child флагом
  `openspec.enabled: false`. Существующие child-репозитории не затронуты — их
  `.ai-ops.yaml` уже содержит явное значение флага. Новым child-репозиториям нужен
  Node.js и `@fission-ai/openspec` (>=1.5.0 <2.0.0); `ai-ops doctor` подсказывает.

### Fixed
- `examples/child-config.example.yaml`: устаревшие `installed_version: 0.7.0` и
  `allowed_version_range: ">=0.7.0 <1.0.0"` обновлены до 1.x — свежий `ai-ops init`
  больше не создаёт конфиг, чей диапазон не включает установленную версию пакета.

## [1.0.0] — 2026-07-08

**Первый стабильный релиз.** Функциональность 0.8.0 объявляется стабильной: с этой версии
действуют обещания SemVer — patch/minor не ломают child-репозитории, breaking changes
только в 2.0.0 с миграцией в migrations/.

### Стабилизировано
- Контракты: agent registry, workflow contracts (QUICK/ENGINEERING/PRODUCT/RESEARCH),
  gate-result, route-decision, child-config, update-result (schema_version 1).
- CLI `ai-ops`: init / status / diff / update / validate / doctor / migrate / verify-capabilities.
- Boundary-модель managed/project/custom/generated/runtime + drift-детект по контрольным суммам.
- Provider/runtime абстракция, декларативный routing, capability-index.
- OpenSpec-опция (>=1.5.0 <2.0.0) + parallel-merge guard.
- Sequential-оркестратор, генерация runtime-команд, presets, stale-gates детектор.

### Совместимость
- Подтверждено на двух child-репозиториях (existing + new pilot), обновления 0.6→0.7→0.8
  прошли штатным updater'ом без потери локальных файлов.

## [0.8.0] — 2026-07-08

Закрытие post-MVP бэклога: stale-gates, генерация runtime-файлов, sequential-оркестратор,
декларативные presets. Всё аддитивно; existing agents/workflows не изменялись.

### Added
- `validation/validate_stale_gates.py` — детектор «протухших» gate-результатов
  (hash артефактов / expires_at / tested_revision+affected_files); stale blocking = fail.
- `tools/generate_runtime.py` — генерация `.ai/generated/{claude-code,codex}` команд из
  workflow-контрактов + `.generation.json` (drift-детект генерации). Принцип 27 выполнен.
- `tools/orchestrator.py` — sequential-mode оркестратор: изолированные role prompts,
  judge получает только опубликованные артефакты (handoff), TaskState + возобновление;
  провайдер подключается как callable (mock включён, сетевые адаптеры — снаружи).
- `presets/*.yaml` — декларативные presets (core, software-product, product-discovery,
  data-and-integrations): агенты подключаются по id, файлы не перемещаются.
- `validation/validate_presets.py` — двусторонняя сверка presets ↔ registry.
- CI: +4 шага (stale-gates, generator, orchestrator, presets).

### Changed
- `VERSION`, manifest → 0.8.0.

## [0.7.0] — 2026-07-08

Фаза 9 миграции: **updater** — CLI `ai-ops` для установки и обновления child-репозиториев.
Обновление этого репозитория 0.6.0 → 0.7.0 выполнено самим updater'ом (боевой прогон).

### Added
- `installer/ai_ops.py` — команды status / diff / update / init / validate / doctor /
  migrate / verify-capabilities. Алгоритм update: версии → drift-детект (блокирует при
  ручной правке managed, не перезаписывает молча) → diff → backup → миграции → замена
  managed → project/custom не тронуты → перегенерация provenance/checksums → smoke-валидаторы →
  machine-readable отчёт (`.ai/runtime/last-update-report.json`, схема update-result).
- `manifest -> update_policy.managed_set` — состав managed-слоя объявлен декларативно.
- `migrations/` — механизм миграций (README + _template/{up,down}.py; цепочка пока пуста).
- `schemas/update-result.schema.json` — контракт отчёта об обновлении.
- CI: шаг `ai-ops doctor`.

### Verified
- Боевой update 0.6.0→0.7.0: 2 изменения применены, 24 файла под контролем, smoke pass,
  отчёт валиден по схеме; `.ai-ops.yaml` installed_version обновлён updater'ом.
- Негативный тест: ручная правка `.ai/managed/quality/gates.yaml` → update **blocked**,
  `human_approval_required: true`, путь правки в отчёте.

### Changed
- `VERSION`, manifest → 0.7.0; `.ai/runtime/.gitignore` (бэкапы не коммитятся).

## [0.6.0] — 2026-07-08

Фаза 8 миграции: этот репозиторий установлен как **первый child** (existing-repo pilot).
Ф7 (раскладка presets) сознательно отложена — не блокирует пилот.

### Added
- `/.ai-ops.yaml` — child-конфигурация репозитория (parent=path:02_tools/ai-first-system,
  installed_version 0.6.0, update через PR, только secret-reference, OpenSpec выключен).
- `/.ai/managed/` — управляемый слой (23 файла: реестры, gates, схемы, манифест, security)
  с `.provenance.json` и `.checksums.json`; тела агентов читаются in-place из пакета
  (source: package-in-place, монорепо).
- `/.ai/{project,custom,generated,runtime}` — защищённые/генерируемые зоны.
- `schemas/child-config.schema.json` — контракт child-конфига (в пакете).
- `02_tools/ci/validate_ai_ops_child.py` — валидатор установки: структура конфига,
  secret-reference, согласованность версий (config==provenance==manifest==VERSION),
  целостность managed-слоя, providers/gates известны реестрам. CI: +2 шага,
  триггеры дополнены путями `.ai-ops.yaml` и `.ai/**`.

### Verified
- Живой drift-тест: ручная правка `.ai/managed/quality/gates.yaml` обнаружена, установка
  блокируется; литеральный ключ в credentials_ref отклоняется.

### Changed
- `manifest/ai-ops-manifest.yaml`, `VERSION` → 0.6.0 (managed-копия синхронизирована).

## [0.5.0] — 2026-07-08

Фаза 6 миграции: provider/runtime абстракция + декларативная маршрутизация.
Аддитивно и обратимо. GigaChat — planned-провайдер (опция на будущее), реальных
credentials в репозитории нет и не появилось.

### Added
- `registry/providers.yaml`, `models.yaml`, `runtimes.yaml`, `tools.yaml` — реестры
  четырёх независимых сущностей (provider ≠ model ≠ runtime ≠ tool protocol).
- `registry/capability-index.yaml` — заполненный нормализованный индекс возможностей
  (статусы documented/verified/inferred/... , словарь дополнен `inferred`).
- `registry/routing-policy.yaml` — декларативные правила выбора workflow/provider/
  model_class/runtime/mode (конкретные модели в workflow не зашиты).
- `02_tools/ci/ai_route.py` — движок маршрутизации: explainable route-decision
  (self-test: конфиденциальная RU-задача -> gigachat/local, обычная -> anthropic/claude-code,
  quick -> fast без approval).
- `02_tools/ci/validate_ai_first_providers.py` — валидатор реестров (ссылочная целостность,
  no-secrets, статусы, прогон движка).
- `02_tools/ci/ai_capability_selftest.py` — offline capability self-test (structured output
  parse/retry, error normalization, routing downgrade); credentialed-тесты пропускаются без ключей.
- Схемы provider-entry, runtime-entry, route-decision. CI: +3 шага.

### Changed
- `schemas/capability-entry.schema.json` — статус `inferred` добавлен в словарь.
- `manifest/ai-ops-manifest.yaml` — providers.status=integrated; package_version 0.5.0.
- `VERSION` → 0.5.0.

## [0.4.0] — 2026-07-08

Фаза 5 миграции: интеграция OpenSpec как spec-протокола (опция, выключена по умолчанию).
Аддитивно и обратимо; текущий task-lifecycle работает без OpenSpec.

### Added
- `openspec/README.md` — интеграция (opt-in, зависимость `@fission-ai/openspec >=1.5.0 <2.0.0`,
  детерминированные validate/archive/sync, fallback).
- `openspec/change-template/` — расширенный change-пакет (OpenSpec-часть + наши
  execution/gates/decisions/learning/verification).
- `openspec/schemas/product`, `openspec/schemas/research` — custom extension schemas для
  неинженерных workflow.
- `examples/openspec-demo/` — рабочий пример, проходит реальный `openspec validate --all --strict`
  (2 passed, 0 failed на 1.5.0).
- `02_tools/ci/validate_openspec_change.py` — структурный валидатор change-пакетов +
  **parallel-merge guard** (закрывает известный баг OpenSpec: два un-archived change на одном
  требовании блокируются). CI-шаг добавлен.

### Changed
- `manifest/ai-ops-manifest.yaml` — spec_protocol.status=integrated, enabled_by_default=false;
  package_version 0.4.0.
- `VERSION` → 0.4.0.

### Verified
- Реальный `openspec@1.5.0`: example проходит `validate --all --strict`.
- Guard: параллельный конфликт и структурные ошибки корректно ловятся (негативные тесты).

## [0.3.0] — 2026-07-08

Фаза 4 миграции: границы managed/project/custom/generated/runtime + 6 уровней
разрешений + обнаружение прямой правки managed-файлов. Аддитивно и обратимо.

### Added
- `security/permission-levels.yaml` — 6 кумулятивных уровней разрешений
  (read-only → controlled-write → execution → network → privileged → destructive),
  расширяют config/tool-permissions.yaml (сохранён).
- `security/boundary-model.md` — модель зон child-репозитория: что обновляет parent,
  что защищено, что генерируется, как обнаруживается ручная правка.
- `schemas/provenance.schema.json` — контракт `.ai/managed/.provenance.json`.
- `examples/child-install/.ai/{managed,project,custom,generated,runtime}` — пример-фикстура
  установки с `.provenance.json` и `.checksums.json`.
- `02_tools/ci/ai_managed_checksums.py` — generate/verify контрольных сумм managed-слоя
  (обнаружение drift). CI-шаг verify на фикстуре добавлен.

### Changed
- `manifest/ai-ops-manifest.yaml` — package_version 0.3.0; добавлены security_policies и
  расширен update_policy (provenance/checksums/update_lock/runtime paths, drift_detection).
- `VERSION` → 0.3.0.

## [0.2.0] — 2026-07-08

Фаза 3 миграции: декларативные workflow-контракты + единый gate-реестр + 3 новых
core-агента. Аддитивно и обратимо — тела существующих агентов и прозаические
`workflows/*.md` не изменялись (остаются рабочими до перевода).

### Added
- `registry/workflows.yaml` — контракты MVP-workflow QUICK/ENGINEERING/PRODUCT/RESEARCH
  (runtime-independent; стадии ссылаются на агентов, gates — на реестр gate'ов).
- `quality/gates.yaml` — единый gate-реестр (8 blocking MVP + non-blocking), с revision-binding
  и read-only ролями проверки.
- Новые core-агенты: `intake-classifier` (приём/классификация), `requirements-writer`
  (writer требований, из merge system-analyst+business-analyst), `plan-reviewer`
  (PLAN CRITIQUE, adapt prompt-reviewer). Прежние роли остаются до фазы миграции.
- `schemas/` пополнены контрактами `workflow`, `gate-result`.
- `02_tools/ci/validate_ai_first_workflows.py` — валидатор контрактов (стадии→агенты,
  workflow→gates, MVP≤8 blocking, writer/judge separation). CI-шаг добавлен.

### Changed
- `registry/agents.yaml` — 38 записей (35 + 3 новых core).
- `manifest/ai-ops-manifest.yaml` — package_version 0.2.0; registries указывают на
  workflows.yaml и quality/gates.yaml.
- `VERSION` → 0.2.0.

## [0.1.0] — 2026-07-08

Первый change package целевой архитектуры V2: `bootstrap-structured-registry-and-manifest`
(см. `audit/ai-ops-target-v2/FIRST_CHANGE_PACKAGE.md`). Аддитивный и обратимый —
тела агентов не изменялись, файлы не перемещались.

### Added
- `registry/agents.yaml` — machine-readable реестр всех 35 агентов со структурными полями
  контракта (id, version, contract_version, layer, review_mode, target/action/migration_phase).
- `manifest/ai-ops-manifest.yaml` — центральный манифест пакета (package_version 0.1.0).
- `registry/capability-index.yaml` — скелет индекса возможностей (значения — на фазе Ф6).
- `schemas/` — контракты: registry-entity, package-manifest, capability-entry.
- `VERSION` — версия пакета (0.1.0).
- `02_tools/ci/validate_ai_first_registry.py` — валидатор полноты реестра
  (каждый агент зарегистрирован и наоборот; уникальность id; валидность манифеста).
- CI-шаг «Валидация реестра AI-first системы» в `repo-quality-check.yml`.

### Unchanged (сознательно)
- Тела агентов, workflows, rules, templates, AGENTS.md, CLAUDE.md — без изменений.
- `config/agents.yaml` остаётся source-совместимым; реестр создан рядом, не вместо.
