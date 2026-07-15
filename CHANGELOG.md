# CHANGELOG — AI-first система (пакет)

Формат: [SemVer](https://semver.org/lang/ru/). Версия пакета — в `VERSION`.

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
