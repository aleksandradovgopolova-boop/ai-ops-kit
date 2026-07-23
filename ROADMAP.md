# Roadmap — путь к AI Product Operating System

Видение — в `VISION.md`. Здесь — что уже есть, чего не хватает и в каком порядке
закрываем разрыв. Каждая фаза — отдельный minor-релиз, аддитивный и обратно
совместимый в пределах 2.x; 3.x (текущий канал — v3.0.x stable, точная версия в VERSION) остаётся обратно совместимым —
физический разнос дерева по packages (breaking) намечен на v3.2/v4.0, см. «Схема версий».

## Что уже есть (опора)

| Механизм видения | Состояние в ките |
|---|---|
| Product First | Контракт PRODUCT (problem → users → value → ... → handoff), агенты product/* |
| Writer ≠ judge, gates | 28 gates с revision-binding, machine-readable результаты (MVP-blocking = 8; счётчик запиннен claim gate-count/mvp-blocking-count) |
| Everything as Code | Registry как источник истины, схемы контрактов, валидаторы в CI |
| Review-агенты | 14 независимых ревьюеров по зонам: plan, prompt, requirements, code, architecture, performance, security, accessibility, ux, design-system, analytics, documentation, observability, product |
| Аналитика | Частично: ProductAnalyticsPlan, Experiment (шаблоны), experiment-designer, product-analyst |
| Документация | documentation-steward, gate documentation_drift (пока non-blocking) |
| Observability | observability-engineer, workflow release.md, incident-resolution + memory |
| Память/инсайты | memory/ + стадии memory-capture (замкнуто в 1.2.0) |
| Генераторы | Образец: tools/generate_runtime.py (единый источник, drift-детект) |

## Фаза 1 — Продуктовый фундамент (v1.3) ✅ выполнена

Цель: «Analytics/Design/Docs by Default» как контракты, а не пожелания.

- **Шаблоны недостающих артефактов**: TrackingPlan, EventSchema, DashboardSpec,
  UXFlow, ScreenStates (Empty/Loading/Error/Success), DesignReview, RolloutPlan,
  FeatureFlag, RollbackStrategy, MonitoringSpec (SLO/alerts), ProblemStatement, JTBD,
  Personas, Hypotheses, OpportunitySolutionTree.
- **Новые quality gates** (сначала non-blocking, ужесточение — фаза 3):
  discovery_completeness, ux_review, design_system_usage, analytics_readiness,
  documentation_updated, release_safety (flag+rollback), observability_readiness.
- **Feature Blueprint v1**: структура каталога функции + JSON Schema
  (feature-blueprint.schema.json) + валидатор полноты по стадии жизненного цикла.
- **Workflow-контракты ANALYTICS и VISUAL** (заявлены как post-MVP с v0.2) — стадии,
  агенты, gates.

## Фаза 2 — Review-агенты и Discovery (v1.4) ✅ выполнена

Цель: каждая зона ответственности имеет своего ревьюера; Discovery — первоклассный этап.

- **Новые агенты** (каждый — с записью в registry и eval-кейсами, гейт уже требует):
  product-reviewer, ux-reviewer, design-system-reviewer, analytics-reviewer,
  documentation-reviewer, observability-reviewer. Architecture review — расширение
  зоны solution-architect + отдельный architecture-reviewer.
- **Углубление PRODUCT-контракта**: полноценные Discovery-стадии (problem statement,
  JTBD, personas, hypotheses, impact mapping, competitor review, success metrics,
  risks) с шаблонами фазы 1.
- **UX-чек-листы как данные**: rules/design/ на основе Nielsen Heuristics и WCAG —
  машиночитаемые списки, на которые ссылаются ревьюеры.

## Фаза 3 — Генераторы (v1.5) ✅ выполнена

Цель: стандартизированные артефакты создаются генераторами, а не свободной формой.

- **Generator framework** в tools/ по образцу generate_runtime.py: генератор читает
  Feature Blueprint + результаты предыдущих этапов, создаёт скелеты артефактов из
  шаблонов, drift-детект отличает сгенерированное от отредактированного.
- Первые генераторы: Discovery, PRD, Analytics (Tracking Plan + Event Schema),
  Dashboard Specification, Documentation (User Guide/FAQ/Release Notes/What's New),
  Release (checklist + rollout + rollback), Monitoring (logging/metrics/alerts/SLO),
  Experiment, Retrospective.
- Gates фазы 1 переводятся в blocking для workflow PRODUCT/VISUAL/ANALYTICS.

## Фаза 4 — Knowledge Graph и Product Health (v2.0) ✅ выполнена

Цель: непрерывный цикл Discovery → Delivery → Release → Measurement → Insights → Discovery.

- **Knowledge Graph**: registry/entities.yaml — типы сущностей и связи
  (Goal → Initiative → Epic → Feature → Story → ... → Insight), валидатор ссылочной
  целостности; Feature Blueprint становится узлом графа.
- **Product Health**: контракт метрик (adoption, retention, reliability, errors,
  performance, support load) + Product Health Score; вход — экспорт из
  аналитики/мониторинга, выход — machine-readable отчёт.
- **Continuous Improvement**: workflow INSIGHTS — анализ данных после релиза,
  генерация гипотез и экспериментов, запись в memory/ и вход следующего Discovery.
- Пересмотр schema_version контрактов: breaking НЕ потребовался — все контракты
  остаются schema_version 1, v2.0 полностью обратно совместим с 1.x.

## v2.1 — интеграция research-пакета ✅ выполнена

Курируемая интеграция внешнего исследования (Product & Design Extension Pack):
взяты реальные пробелы, дубли уже построенного отклонены.

- **AI Feature Evals**: ai-evaluator + rules/ai/EvalPolicy.md +
  templates/quality/AIFeatureEvalPlan.md + blocking-гейт ai_eval (applies_when:
  LLM/агентный компонент в фиче). Кит теперь измеряет не только своих агентов,
  но и AI-возможности, отданные пользователям.
- **Adoption как стадия**: adoption-manager, контракт ADOPTION (launch-readiness ->
  adoption-plan -> feedback-loop -> post-launch-review -> independent review),
  стадия adoption в Feature Blueprint, preset product-adoption.
- **Discovery-исследование**: user-researcher + UserResearchPlan (story-based
  интервью) + AssumptionTest (RAT); правила Continuous Discovery в OST-шаблоне.
- **Источники истины**: context/product/DesignSystem.md (DTCG-токены) и
  MetricCatalog.md (семантический слой); поле source_of_truth у gates.
- analytics_readiness усилен evidence events_verified_live; ExperimentReadout,
  InAppContent; Diátaxis-компас в UserGuide; HEART/AARRR в DashboardSpec.

Кандидаты v2.3 ✅ выполнены в v2.3.0 (оба обоснованы данными первого боевого
прогона — memory/lessons-learned/2026-07-09-first-child-run-insights.md):
профили blueprint lean/full и кросс-артефактный валидатор
(tracking-plan ↔ dashboard-spec; расширение на MetricCatalog — следующий шаг).

## Интеграция team-os-toolkit (референс операционной архитектуры команды)

Из четырёх слоёв team-os-toolkit ~60% уже реализовано в ките под другими именами
(registry как SoT, Knowledge Graph, memory-loop, human-approval). Берём механику
недостающего, отклоняем структурный reorg (ковенант: аддитивно, без breaking в 2.x).

- **Фаза 1 — Knowledge Integrity (v2.9) ✅ выполнена.** Drift-control, наведённый
  сначала на сам пакет: validate_references.py (uses_skills/checklist/owner/gate
  резолвятся — закрыл латентную дыру 2.7–2.8), claims.yaml + validate_claims.py
  (утверждения документации о коде: file/symbol/enum), селфтесты с намеренным сломом
  (гейт видят падающим). Гейт knowledge_integrity (non-blocking до обкатки).
- **Фаза 2 — Freshness + Governance (v2.9) ✅ выполнена.** FreshnessPolicy (классы
  stable/evolving/volatile, единый термин stability) + validate_freshness.py + now.md
  как датированный снимок; governance/information-boundaries.md (что можно/нельзя
  хранить — критично для гос-контекста). Гейт knowledge_freshness (advisory).
- **Фаза 3 — Decision Intelligence (v2.10) ✅ выполнена.** decisions/registry.yaml
  (принципы с confidence/recurrence/counterexamples/review_date, эпизоды, outcomes) +
  схема + validate_decisions.py; skill decision-support (recommendation-first: система
  не выдаёт вердикт, пока человек не сформулировал позицию; one-way-door — бриф на
  эскалацию, AI не решает необратимое сам); workflow DECISION; гейт decision_quality
  (non-blocking). Связь с systems-thinking (constraint -> contradiction -> decision).
- **Фаза 4 — Runtime/Robin (v2.21) ✅ выполнена как runtime-агностичная спека.** Кит даёт
  абстрактный контракт `persistent-agent-runtime` (`registry/runtimes.yaml`), спеку
  `runtime/robin/ROBIN.md` (декларативные duties, два слоя памяти staged→promoted через
  человека, append-only interaction-log, read-mostly границы, kill-switch), валидатор
  `validation/validate_duties.py` и шаблон привязки `templates/runtime/runtime-binding.example.yaml`.
  Честно: конкретный рантайм (Hermes, свой сервис, cron+CLI) — привязка на уровне child, не
  в ядре; `verified_against_deploy: false` (из среды разработки деплой не проверялся);
  постоянного runtime у кита по-прежнему нет, оркестратор sequential-only. Не строим: Robin
  как готовый бот.

Отклонено осознанно: reorg `.ai/` целиком, `capabilities/`/`adapters/` как новые
верхнеуровневые слои (дублируют capability-index/presets/runtimes), Robin как готовый бот.

## Execution Engine (v2.31–2.39) — от «конституции» к исполняющему ядру

По внешнему аудиту: у кита сильное ядро `task → workflow → agents → gates`, но не хватало
внешнего слоя автоматики. Всё, что строится **детерминированно/offline**, — сделано и
обкатано на реальном child (ии-среда):

- **Фаза 0 — correctness & safety (v2.31) ✅.** Устранён дрифт `ai-start-task`; `security`
  в ENGINEERING; `ai_red_team` блокирующий; сырой task-текст убран из audit-log;
  состояние прогона — per-WorkItem (`.ai/runtime/workitems/<id>/`).
- **Фаза 1 — контракт исполнения (v2.32–2.33) ✅.** RunPlan = base_workflow + треки
  (`registry/tracks.yaml`): «Design/Analytics/Docs by default» выводится из сигналов и
  добавляет свои гейты. Structured reviewer-result — источник истины вместо regex;
  evidence-схемы гейтов.
- **Фаза 2 — исполнение (v2.34–2.39) ✅ offline-часть.** `ai-ops run` — единый контроллер
  (route→RunPlan→WorkItem→active-work→исполнение→отчёт). Tool Broker + Policy Engine
  («модель предлагает, политика решает»; protected-paths = merge пакет+child). Execution
  budget (потолок вызовов). Провайдеры anthropic/openai/openai-compatible (DeepSeek/local).
- **Живое — разблокировано (v2.42–2.44) ✅.** tool-calling петля подтверждена живым прогоном
  на DeepSeek (`openai-compatible`): цикл `write → проверка → done`, политика и бюджет держат
  (`live_proposal_quality: verified`). Concurrency preflight видит открытые PR через GitHub
  REST-фоллбэк без `gh` (токен из env). Stack-aware evidence collector гоняет команды
  RepositoryProfile через Broker и отдаёт структурный evidence в `implementation_verification`.
- **3.0 additive-complete (`docs/3.0-design.md`):** срез 0 ✅ границы 5 пакетов + валидатор
  (`validate_package_boundaries.py`); срез 1 ✅ `ai-run` канонический вход (`ai-start-task` —
  совместимый алиас); срез 2 ✅ по-пакетная установка (`.ai-ops.yaml packages`, дефолт = все).
  Всё аддитивно, ни один child не сломан.
- **Физический разнос дерева → 3.1** (решение `ep-2026-07-16-tree-split`): перенос ломает
  CI-контракт установленных child и не даёт пользы сверх уже сделанного; оправдан только
  раздельной дистрибуцией пакетов. Тогда же — энтрипойнт-шимы, миграция child-CI, MIGRATION_GUIDE.

## Execution integrity audit (v2.93–2.96) ✅ — доведение исполнения

По внешнему разбору (9 из 9 пунктов подтверждены по коду) закрыт слой корректности исполнения,
аддитивно к Execution Engine:

- **v2.93 Truth & Integrity** — worktree-only контейнер (одноразовый клон, основной checkout не
  смонтирован, доставка host-слоем); целостность коммита (снимок untracked до install; факт правок
  из git-diff, а не по числу write-op); PR delivery без хардкода дефолт-ветки + идемпотентность;
  синхронизация safety-claim'ов с кодом.
- **v2.94 One Run Transaction** — pipeline и lifecycle в одной транзакции: единый план, WorkItem,
  active-work, concurrency-preflight, run-report, закрытие active-work.
- **v2.95 Security evidence** — детерминированный секрет/dep-скан (`security_scan.py`) закрывает
  факты `no_secrets`/`deps_approved`; находки блокируют с деталями; injection-surface — судье.
- **v2.96 Real Qualification** — канонический e2e движка на реальной фикстуре в CI, матрица Python
  3.9/3.12, живые сценарии S6–S10.

## Context Engineering & Spec-Driven Execution ✅ выполнено (v2.97–v2.103, доведено в v2.123 Spec-First)

Отдельный эпик ПОСЛЕ текущего execution-аудита (не блокер, не меняет уже переданные постановки).
Продуктовая гипотеза: AI Ops должен управлять не только тем, что модель **делает**, но и тем, что
она **знает**, что **помнит**, насколько глубоко задача **описана** и когда автономность должна
**остановиться**. Источники подхода — Spec-First, GSD (борьба с context rot), структурный Security
Review. Порядок — строго последовательный; каждый блок — свой minor-релиз с валидаторами и
self-test'ами, аддитивно.

**Этап 1 — Context Compiler. ✅ v2.97.** Перед прогоном собирать минимальный релевантный `ContextBundle` для
WorkItem (задача, часть Project Context, RepositoryProfile, применимые спеки/решения, нужные файлы
или summaries, релевантные правила, только нужные skills/роли/reviewers, состояние прошлого прогона,
открытые допущения). Явно исключать нерелевантное/устаревшее с указанием причины. Новый артефакт
`kind: ContextBundle` (included/excluded+reason/assumptions/open_questions/estimated_tokens/
context_budget). Приёмка: у каждого прогона сохранён bundle; видно, почему источник включён; размер
считается ДО вызова модели; превышение бюджета не обрезает контекст молча; устаревшее не включается
без предупреждения; тот же WorkItem при тех же входах даёт воспроизводимый пакет.

**Этап 2 — Adaptive Spec-First. ✅ v2.98.** Глубина спецификации = f(масштаб, риск, неопределённость,
необратимость). Уровни: L0 QUICK (цель/scope/acceptance/ограничения/файлы), L1 ENGINEERING
(+requirements/scenarios/контракты/зависимости/edge cases/план/write scope/verification), L2 PRODUCT
(+проблема/пользователи+JTBD/ценность/сценарии/гипотезы/метрики/UX-состояния/аналитика/rollout/риски),
L3 CRITICAL (+threat model/rollback/migration/failure modes/audit/approvals/compliance/DR).
Классификатор выбирает уровень (видно почему); уровень повышается при риске, не понижается молча;
у каждого обязательного раздела статус complete|not_applicable|declined|needs_human|missing
(`declined` требует объяснения); реализация не стартует без блокирующих разделов. Приёмка: QUICK не
превращается в бюрократию; ENGINEERING не стартует с однострочника; PRODUCT несёт проблему/пользо­
вателей/ценность/метрики; CRITICAL всегда требует человека; предположения модели сохраняются.

**Этап 3 — Context Lifecycle и Resume (защита от context rot). ✅ v2.99.** Сущности Feature → WorkItem → Run
→ Stage → Step → Handoff. После каждого значимого этапа сохранять сделанное/изменённое/решения/
проверки/остаток/открытые допущения/следующий безопасный шаг/актуальный SHA. Новый артефакт
`kind: RunHandoff` (completed/decisions/changed_files/verification/open_questions/known_risks/
next_action/resume_from_revision). Resume: проверить актуальность base branch, worktree/branch,
перечитать последний Handoff, проверить устаревание решений, пересобрать ContextBundle, продолжить
с последнего подтверждённого шага; НЕ начинать заново, не повторять подтверждённое без причины, не
использовать старый контекст после смены main, не удалять предыдущий результат. Приёмка: задача
продолжается в новой сессии; решения не теряются; смена main вызывает revalidation; точка
возобновления видна; старый evidence не идёт для нового SHA.

**Этап 4 — Atomic Planning и Context Budget. ✅ v2.100.** Каждый work package оценивается (объём контекста,
файлы, системные границы, зависимости, ожидаемые model calls, риск, критерий завершения).
Автодекомпозиция при: слишком многих файлах/подсистемах, превышении контекста, нескольких
независимых результатах, потребности в >1 логически завершённом коммите, неверифицируемости одним
набором критериев. Ограничение: декомпозиция не меняет продуктовый смысл; новые бизнес-решения не
принимаются ради удобства модели. Приёмка: один проверяемый результат на пакет; каждый пакет —
отдельный коммит; зависимости явные; пакет не стартует без подтверждённой зависимости; превышение
бюджета блокирует или дробит; причина декомпозиции в отчёте.

**Этап 5 — Security Pack. ✅ v2.101.** Security review из одного вердикта → набор применимых доменов:
authentication; authorization и IDOR; input validation; secrets; dependencies и supply chain;
rate limiting; file upload; network и SSRF; logging и monitoring; deployment и configuration;
AI prompt injection; data isolation и tenant boundaries. На домен: applicability(signals),
deterministic_checks, reviewer_checklist, required_evidence, severity_policy, blocking_conditions,
human_approval_conditions, remediation_template. Правило: гейт нельзя закрыть фразой модели «уязви­
мостей нет» — только scanner/dependency audit/secret scan/test/policy check/diff review/отдельный
security reviewer/human approval. Приёмка: проверяются только применимые домены; finding несёт
файл+строку+риск+способ исправления; Critical/High блокируют PR; Medium — по policy; false-positive
отклоняется только с причиной; evidence привязан к tested revision; reviewer без write-доступа;
security не закрывает автор кода. (Основа — `security_scan.py` v2.95: детерминированные домены
secrets/deps уже есть.)

**Этап 6 — Простой внешний UX. ✅ v2.102.** Intent-based команды поверх флагов: `new`, `onboard`, `discuss`,
`specify`, `plan`, `run`, `resume`, `review`, `status`, `health`. Пользователь не обязан помнить
`--engine pipeline`/`--author`/`--review`/`--baseline-diff`/`--sandbox` (остаются как низкоуровневый
интерфейс). Приёмка: для запуска достаточно задачи и проекта; система сама подбирает workflow/стадии;
перед запуском — execution preview (что понято, что будет сделано, какие данные, какие approvals,
ожидаемый результат); продвинутые настройки доступны, но не обязательны.

**Этап 7 — Qualification нового слоя. ✅ v2.103.** Обязательные сценарии: Q1 context filtering; Q2 context
overflow → автодекомпозиция; Q3 resume в новой сессии; Q4 stale context после смены main; Q5 spec
depth (QUICK короткая, PRODUCT — discovery+метрики); Q6 небезопасное предположение эскалируется, а
не додумывается; Q7 security applicability (frontend-only не запускает database audit, но проверяет
XSS/secrets); Q8 prompt injection в README/issue не меняет policy; Q9 решение первой фазы учтено в
последней; Q10 auth/secret-boundary не становится ready_for_pr без человека.

**Очерёдность:** 1 Context Compiler → 2 Adaptive Spec-First → 3 Context Lifecycle и Resume →
4 Atomic Planning и Context Budget → 5 Security Pack → 6 Product UX → 7 Qualification. Общий план:
audit backlog → trust/integrity → unified lifecycle → full ENGINEERING/PRODUCT → qualification
движка (всё ✅) → **Context Engineering & Spec-Driven Execution** (этот эпик).

## Аудит v2.104 → Trust & Operational hardening

Внешний аудит на v2.104 подтвердил: execution-ядро сильное (~8/10), но новый Context-слой пока
сильнее в контрактах/наблюдаемости, чем в РЕАЛЬНОМ управлении исполнением. Разбит на релизы:

- **Trust Fixes (v2.105–2.107) ✅** — дефекты, дающие неверный verdict: самоаудит security (path→content,
  v2.104), resume-ревалидация при неразрешимой base (v2.105), enforcement-виринг security-reviewer/
  spec-depth/context-budget (v2.106), ложный green medium-fail + dependency_diff + дрейф
  secret_boundary + единая классификация + не-глушение ошибок слоя + active-work finally (v2.107).
- **Operational Context (v2.108) ✅** — ГЛАВНОЕ: ContextBundle должен реально попадать в prompt модели
  (compiled payload: содержимое правил/решений/спек/skills/project+repo context с hash+revision+
  причиной), бюджет с учётом модели/output-reserve/tool-loop. Сейчас bundle — аналитический артефакт,
  а tool loop получает task+стек+baseline. Это ключевой разрыв «описывает, но не управляет».
- **Real Spec-First (v2.110) ✅** — `specify` реально создаёт (`features/<wid>/spec.yaml` нужной
  глубины) и валидирует спеку; SpecCoverage заполняется из РЕАЛЬНЫХ артефактов (spec.yaml + засчёт
  requirements/plan/openspec), а не из сигналов с пустым provided. Enforcement: существующий, но
  неполный spec.yaml не пускает в implementation (`ready_for_pr=False`), спеки нет → поведение
  прежнее (spec-first опционален для мелких задач).
- **Atomic Planner создаёт WorkPackages (v2.111) ✅** — при необходимости разбиения `decompose`
  строит КОНКРЕТНЫЕ пакеты (id/scope/depends_on/acceptance/order) по основной оси
  (subsystem/result/commit/size), а не только называет оси. Инвариант: не выдумывает новых бизнес-
  решений (scope ⊆ подсистем сигналов), финал подтверждает человек. Контроллер сохраняет пакеты в
  `features/<wid>/work-package.yaml` и отчёт.
- **Real Resume (v2.109) ✅** — resume-mode ПРОДОЛЖАЕТ поверх подтверждённой работы: переиспользует
  ветку/worktree прошлого прогона (коммиты НЕ удаляются), подаёт модели состояние из RunHandoff
  (что сделано/решения/next_action), tool loop продолжает, а не начинает заново. Честность: нечего
  продолжать → honest error; база/состояние устарели → блок без `--force` (не молча на старом
  evidence). `ai-ops resume … --execute [--force]`.
- **Real Intent UX (v2.112) ✅** — намерения — настоящие действия, а не только превью: `onboard`
  пишет RepositoryProfile, `status` читает active-work, `health` считает Product Health (или честно
  отказывает без метрик), `plan` пишет RunPlan+context+spec+work-package без правок кода, `new`
  ставит workitem+spec-каркас, `discuss` создаёт discovery-draft. `run`/`resume`/`specify` уже
  реальны; `preview <intent>` по-прежнему только показывает.
- **Container delivery scope (v2.113) ✅** — доставка из одноразового клона забирает ТОЛЬКО ветки,
  которые создал/изменил ЭТОТ прогон (диф снимка `ai-ops/*` до/после), а не все `ai-ops/*`. Раньше
  force-fetch всех `ai-ops/*` мог перезаписать параллельную ветку устаревшей версией из клона.
  Логика — в `containers/deliver-run-branches.sh`, проверяется `validate_container_delivery.py` без
  docker (на настоящем git). Осталось: product-qualification с живой моделью.
- **Product Qualification (v2.114) ✅** — сквозные ГАРАНТИИ продукта проверяются ДЕТЕРМИНИРОВАННО в
  CI через реальный контроллер (`validate_product_qualification.py`, PQ1-PQ6): ContextBundle реально
  в prompt; неполная спека не пускает в implementation; resume поверх коммита; secret_boundary без
  человека не проходит; крупная задача → конкретные WorkPackages; нет ложного green (dry-run не ready;
  честный прогон даёт реальный evidence, но ready=False с названным блокером). Живые прогоны с
  МОДЕЛЬЮ (качество правок) — на машине пользователя (`qualification/scenarios.yaml` + `qual_run.py`,
  DeepSeek/стек, см. `docs/qualification-runbook.md`).
- **Preflight Truth (v2.115) ✅** — обязательный trust-релиз перед RC. Проверки выполняются ДО
  запуска модели (`tools/preflight.py`, в контроллере перед `run_pipeline`): classification →
  ContextPayload собран → spec достаточна → задача атомарна ИЛИ декомпозиция подтверждена → context
  budget не превышен → необходимые human approvals присутствуют. Блок → tool loop НЕ запускается,
  правок/коммита НЕТ (Spec-First блокирует РЕАЛИЗАЦИЮ, а не только доставку — главный дефект аудита).
  Ошибки Context Compiler/Spec/Planner → fail-closed для ENGINEERING/PRODUCT/CRITICAL. Human-approval
  — настоящий `ApprovalRecord` (`tools/approvals.py`: approval/approved_by/scope/revision/created_at/
  reason), доменные `human_approval_conditions` реально исполняются (не boolean). PQ2/PQ4/PQ5
  доказывают ноль вызовов tool loop и отсутствие коммита при блоке.

- **RC Qualification — детерминированная часть (v2.116) ✅** — `ai-ops review` стал настоящим
  read-only review действующей ветки (`tools/review_branch.py`: независимый ревьюер под read-only
  политикой над worktree ветки, БЕЗ tool loop/правок/коммита, вердикт по ai-review гейтам). S1–S10
  актуализированы (S4: security-reviewer закрывает security на чистой правке; S8: настоящий resume
  v2.109). Доказаны ДЕТЕРМИНИРОВАННО положительные зелёные пути: **PQ7** — корректная QUICK →
  `ready_for_pr=true`, `overall=delivered`; **PQ8** — ENGINEERING с author+review+security →
  `ready_for_pr=true` (при доступном openspec CLI; иначе спек-гейт честно блокирует). «Incomplete
  spec → ноль вызовов tool loop» доказано в PQ2 (v2.115).

### Интеграционная честность склейки (аудит v2.119) — короткий слой до RC
- **Canonical Runtime Wiring (v2.120) ✅** — устранён P0-разрыв: канонический `run --execute` теперь
  проводит provider/model/base/open-pr/max-steps/require-fix в движок (раньше уходил в `mock`);
  sequential наследует sandbox/install/provider/baseline/open-pr/budget (containment не теряется);
  exit-код sequential = 0 только при `ready_all`, 1 — исполнено-не-готово, 2 — цепочка блокирована;
  цепочка ОСТАНАВЛИВАЕТСЯ на настоящем блокере (security/reviewer FAIL, регрессия, нет коммита,
  scope-violation, preflight-блок), а не только на preflight; `work_package_id` валидируется против
  плана (вымышленный id → блок); голый `decomposition_confirmed` больше не пускает блоб; package-level
  write-scope провязан в Tool Broker.
- **Spec & Approval Binding (v2.121) ✅** — spec обязателен до tool loop для ENG/PRODUCT/CRITICAL по
  правилу **author-or-spec** (без spec.yaml и без `--author` → preflight-блок; с `--author` спека
  авторизуется пре-стадией, артефакт-гейты проверяют готовность; QUICK — light); ApprovalRecord ←
  hash spec/RunPlan (`binds_to`/`bind_to_plan`) + `scope` + тип риска (`risk`) + срок (`expires_at`),
  `recheck_after_diff` сверяет `scope` с реально изменёнными путями (не покрыл → не ready); `review`
  пишет lifecycle-evidence (`features/<wid>/branch-review.yaml`) и пересчитывает `ready_for_merge`,
  `needs-reviewer`/`needs-changes` → ненулевой код; install-фикс требует реально отработавшей
  env-проверки (`_env_proven_ok`; ноль проверок или только env-симптомы → не квалифицировано).

### v3.0-rc1 ✅ ВЫПУЩЕН (2026-07-20) — узкий честный claim: QUICK

**AI Ops v3.0-rc1 (QUICK): trustworthy task → verified draft PR для supervised low-risk задач.**
Живая RC-квалификация (DeepSeek/Mac, v2.122→v2.125) пройдена; движок честен по всем осям.

- **Live-qualified (QUICK):** S1/S2 (fix true-green), S6 (prompt-injection проигнорирована), S7
  (контейнер-изоляция: основной checkout байт-в-байт, ветка через доверенный fetch), S9 (реальный
  draft PR, base=default_branch), S8 resume (`resumed=True`), canonical CLI без ручного task_type
  (тривиальная задача → QUICK), approval negative/positive (ApprovalRecord binding в обе стороны),
  dependency-без-signal (security форсируется даже в QUICK). Провайдер-гэп v2.120 закрыт; v2.121
  approval_recheck/review-exit подтверждены; S10 false-negative (v2.122) починен и перепройден.
- **Найдено и починено живой квалификацией:** v2.118/2.119 (env/тул-кэши), v2.122 (baseline-diff
  fixed node-id), v2.123 (Spec-First/ApprovalDecision/write-scope/классификатор), v2.124 (sequence
  transaction), **v2.125→v2.124.1** (security в QUICK; ложный scope-violation на артефактах движка).

### Статус живой квалификации — ЗАКРЫТА (v3.0.0 stable, 2026-07-21, claude-sonnet-5)

- ✅ **Single-run ENGINEERING → настоящий draft PR — ДОКАЗАНО ЖИВЬЁМ.** Канонический CLI: authoring →
  реальная реализация → tests pass → security → `code_review=pass` → `ready_for_pr=true` → draft PR
  (scratch-репо PR #1).
- ✅ **Sequential 3×WorkPackage → `aggregate_ready=true` → настоящий draft PR — ДОКАЗАНО ЖИВЬЁМ.** Все
  пакеты ready → aggregate (baseline на точной базе + security-reviewer + code-review на `base..final`)
  → draft PR (seq-scratch PR #1).
- ✅ **Sequential hard-stop / recovery — ДОКАЗАНО.** reviewer-block → `reviewer-blocked` → downstream не
  стартует; trusted retry → recovery → `executed_all`; provider-crash/429 contained.
- ✅ **Негативные пути — ДЕТЕРМИНИРОВАННО** (94/94 CI): no-verdict aggregate → нет PR; high-risk по путям
  без approval → fail; baseline не доказан → нет PR; base_drift → нет PR; ranged read; 429 → durable report.

Движок закрыт: rc7→rc20 исправили все находки живых прогонов и трёх аудитов.

### Post-stable hardening + Qualification Readiness (v3.0.11 → v3.0.14)

Серия узких trust/lifecycle-патчей по итогам сквозного самоаудита (денежный путь — доставка PR +
security-гейтинг — доказанно fail-closed, P0 false-green нет):

- **v3.0.11 — Batch A (trust/корректность):** `op:git` больше не обходит sandbox; `exit_code≠0` при
  `delivery-failed`; `security_pack` fail-closed при git-сбое; destructive-approval strict;
  context/spec fail-closed на исключении; anti-fabrication code-read без basename-fallback; скраб
  секретов в evidence; блокирующий ai-review не закрывается 0-read рубер-стампом.
- **v3.0.12 — Batch B (durable resume):** `tools/lifecycle_store.py` (atomic+fsync-file+fsync-dir+
  re-read) для run-settings/RunHandoff/active-work/SequencePlan/checkpoint; corrupt ≠ absent; flock на
  RMW active-work.
- **v3.0.13 — Batch C (maintainability):** единый `gitio.py` (+timeout от зависаний), дедуп envelope,
  extract `_aggregate_verify`, закрытие тест-гэпов.
- **v3.0.14 — Qualification Readiness:** (#1) **fast-forward базы** трактуется как rewrite —
  `force_resume` больше НЕ отдаёт PR против сдвинувшейся базы (worktree форкнут от старой, интеграция
  не проверена); нужен свежий прогон от новой базы. (#2) LifecycleStore расширен на RunPlan/final-report/
  controller-report/run-history/ApprovalRecord/sequence-report (+`durable_write_json`). (#3) bounded
  **event journal v0.1** (JSONL, checksum-цепочка, Run→Package→Gate, crash-boundary на запись).

**Отложено в v3.1 (осознанно):** авто-интеграция fast-forward (rebase WorkItem-коммитов на новую базу +
полный повтор проверок при `force_resume` — «настоящая ревалидация», а не блок); извлечение сильно
связанных god-блоков `run_pipeline`/`run`; event journal v0.2 (полное покрытие событий, восстановление
последовательности как первичный контракт).

### Research v0.1 — ранний bounded context (контрактный прототип)

В `main` появился отдельный research-контекст (namespace `research.*`, хранилище `.research/`):
`ResearchRequest → Research execution → Evidence → DecisionPackage`, с versioned-схемами, provenance,
freshness и первым живым DecisionPackage. Архитектура **extractable**: при втором независимом
потребителе Research выносится в отдельный research-center.

Статус: **v0.1 — контрактный прототип, НЕ законченный runtime.** По собственному roadmap модуля на
**v0.2** назначены: валидатор + self-test, memory, source registry, повторное использование evidence.
Это ранняя часть будущего Discovery/Product-Learning-фундамента — официально числится в общем roadmap
как отдельный трек, развиваемый параллельно execution-ядру, а не как часть его qualification-релиза.

### Осталось (валидация в бою, не дефекты)
- **dogfood на 2–3 реальных репозиториях** (Python → TS/Node → реальный сервис) — рекомендованная
  следующая валидация ПОВЕРХ stable (реальная мессовость vs синтетические фикстуры). Не блокер
  корректности. Критерии зрелости при dogfood: ≥5 реальных задач (≥2 ENGINEERING, ≥1 sequential), ноль
  false-green, основной checkout ни разу не тронут recovery, каждый вердикт привязан к SHA/диапазону,
  delivery проверена против актуальной remote base.

### Историческое: Live RC Qualification (v2.122) — исходный план прогонов
- Живые прогоны S1/S2/S4/S6/S7/S8/S9/S10 + live sequential с DeepSeek на Mac (`tools/qual_run.py`
  **и** канонический intent CLI — там был provider-gap), настоящий draft PR (`--open-pr` +
  GITHUB_TOKEN), сохранённые очищенные JSON-отчёты.
  - **Живой прогон 2026-07-18 (DeepSeek/Mac, база v2.121):** sanity-selftest 7/7 PASS. Провайдер-гэп
    v2.120 **закрыт** — `model==deepseek-chat` во всех отчётах (canonical CLI, sequential, S1–S10),
    не mock. v2.121 подтверждён вживую: `approval_recheck.ok=true (uncovered=[])` во всех прогонах;
    `review` exit-код связан с вердиктом (S1 green → 0 / ready_for_merge=true; S4 ENGINEERING → 1 /
    needs-changes). **PASS:** S1, S2 (`fixed=['test']`), S4 (движок честно блокирует без артефактов;
    writer≠judge держится), S6 (инъекция проигнорирована, main нетронут), S7 (изоляция: основной
    checkout байт-в-байт, ветка через доверенный fetch). Ядро честности держит — `ready_for_pr`
    нигде не true при блоке/регрессиях.
  - **S9 — ✅ PASS (обе половины).** Негатив: `--open-pr` честно отказал без `GITHUB_TOKEN` (PR не
    имитируется). Позитив (через `gh auth token` + throwaway repo под authed-аккаунтом): `ready_for_pr=
    true`, `overall=delivered`, `delivery.status=opened`, `draft_pr` — реальный draft PR, `base==main`
    (default_branch репо, не хардкод). Токен только в env прогона, не в отчётах/коммитах.
  - **S10 — реальный false-negative движка (см. finding ниже).** Держит rc1.
  - **Наблюдения:** (1) образ контейнера (`ai-ops-engine`) не содержит `pytest` в окружении child →
    внутри env не квалиф. → доставленная ветка пуста (изоляция доказана, зелёная доставка требует
    установки dev-зависимостей); (2) `--sequential` не задействовал package-executor — планировщик
    счёл 2-модульную задачу атомарной (`decomposition_advised=false`), нужен явно делимый кейс;
    (3) auto-классификатор канонического CLI грейдит тривиальные задачи как ENGINEERING → spec-first
    блок (честно, но агрессивно; QUICK-путь — через `qual_run --task-type QUICK`); (4) фикстура
    обязана нести pytest-сигнал (`[tool.pytest.ini_options]` или каталог `tests/`), иначе детектор
    (`project_detector.py:119`) не находит test-команду → env не квалиф. (дефект фикстуры, не движка).

- **✅ ЗАКРЫТО в v2.122 (перепроверено в v3.0.15).** `_diff_checks` считает `fixed` симметрично
  регрессиям на уровне structural failure-ids (`_failure_ids(baseline) − _failure_ids(after)`): красная
  база с починенным профильным узлом и оставшимся старым падением даёт `fixed` непуст, `regressions`
  пуст. Юнит-тесты: «S10 red-base …» и «v3.0.15 require_fix {a:fail,b:fail}→{a:pass,b:fail}» в
  `execution_pipeline.selftest`. Историческое описание находки ниже — как было ДО фикса.
- **Finding обкатки S10 (2026-07-18): `fixed` считался на уровне чек-агрегата, не structured node-id
  → false-negative на красной базе под `--require-fix`.** На red base модель корректно починила
  профильный тест (`apply_discount → x*0.9`, узел `test_discount10` red→green), непрофильный
  пред-существующий `test_legacy_report` остался красным (как задумано). Отчёт: `fixed=[]`,
  `ready_for_pr=false`, `other_blocking_unmet=[]` — ready держит **исключительно** пустой `fixed`
  (`implementation_verification` baseline-освобождён и не блокирует). Корень: `_diff_checks`
  (`tools/execution_pipeline.py:571`) итерирует по ИМЕНАМ проверок и делает `fixed.append(name)`
  только когда чек целиком `fail→pass` (стр. 589); при `fail→fail` (стр. 591) сравнивает node-id
  **лишь в сторону регрессий** (`_failure_ids(a) - _failure_ids(b)`), но никогда не считает
  ПОЧИНЕННЫЕ узлы. Асимметрия: node-level для регрессий, check-level для фиксов — противоречит
  acceptance S10 («baseline.fixed содержит починенное») и заявке v2.84 про «structured-id
  baseline-diff». Честно-консервативно (не ложный green, P0.6/канон честности НЕ нарушен), но
  блокирует легитимный фикс на красной базе. **Направление фикса:** считать `fixed` симметрично
  регрессиям — `fixed_ids = _failure_ids(baseline) - _failure_ids(after)` на каждом чеке, добавлять
  чек в `fixed` при непустом множестве; юнит-тест на red-base (профильный узел починен, непрофильный
  остаётся красным → `fixed` непуст, `regressions` пуст) + перепрогон S10. Держит rc1.

### Схема версий (разведён двойной v3.1)
- **v3.0-rc1 ✅ (2026-07-20)** — live-qualified execution (QUICK-claim; ENGINEERING positive-green → v3.0).
- **v3.0** — stable после positive-green ENGINEERING + dogfood.
- **v3.1** — Sequential WorkPackages как веха (капабилити поставлена аддитивно в 2.117).
- **v3.2 / v4.0** — физический разнос дерева по packages (breaking).

> ⚠️ Схема версий ВЫШЕ — ИСТОРИЧЕСКАЯ (Sequential уже поставлен в 2.117; нумерация v3.1/v3.2 ниже
> переопределена). Актуальный маршрут — в разделе «Current Forward Roadmap» ниже.

## Current Forward Roadmap (актуально с v3.0.14)

Ядро вышло из фазы бесконечного исправления execution-логики. Осталось закрыть транзакционную границу
между доказательствами и delivery, затем квалифицировать систему на РЕАЛЬНЫХ задачах, и дальше —
развитие вокруг ядра.

Зафиксированный маршрут:

- **v3.0.14** ✅ — Qualification Readiness (fast-forward база fail-closed / вариант B; LifecycleStore на
  весь источник истины; event journal v0.1).
- **v3.0.15 — Lifecycle Commit Barrier** (последний внутренний trust-релиз): delivery ТОЛЬКО после
  durable-фиксации RunHandoff+report+journal (доставка вынесена из pipeline в транзакционный контроллер);
  обязательные write-barriers на критические артефакты; LifecycleStore v1.1 (validate-before-replace,
  unique temp, backup); симметричный require_fix (перепроверено); честные ограничения journal v0.1.
- **v3.0.16 — Real Execution Qualification** (две фазы):
  - **Phase A — Delivery Outbox & Reconciliation** ✅ (v3.0.16, qualification-entry closure): прямой
    run_pipeline не может обойти lifecycle-барьер (доставка только в контроллере); DeliveryIntent →
    external → DeliveryReceipt; `outcome_unknown` + reconciliation при сбое после внешнего действия;
    идемпотентная доставка (без дубля PR); единые write-barriers. Это ВХОДНОЙ gate, ещё не «квалифицировано».
  - **v3.0.17 — Delivery Outbox Integrity** ✅ (адресный патч по findings Phase A): per-`delivery_id`
    immutable outbox; неразрешённый Intent блокирует новую доставку; reconciliation сверяет ТОЧНЫЙ
    `head.sha`+`base.ref`+repository (не имя ветки); все записи outbox — барьеры; неоднозначный POST →
    `outcome_unknown`; reconciliation ловит Intent-без-Receipt по факту; Research-контур подключён к CI.
  - **Phase B — Real Execution Qualification**: реальные прогоны на настоящих репо (Python + TS/Node +
    security-sensitive + реальный сервис): QUICK, ≥2 ENGINEERING, sequential, provider interruption,
    resume в новой сессии, base moved → safe block → fresh run, reviewer block → trusted retry, red base →
    partial fix, настоящий draft PR, downstream CI, child update, **delivery crash → reconciliation**.
    Критерии: ≥5 задач, 0 false-green, 0 повреждений основного checkout, **0 duplicate PR после retry**,
    100% verdicts привязаны к SHA, 100% external deliveries имеют DeliveryIntent, 100% outcomes
    подтверждены Receipt или помечены outcome_unknown. Результат — QualificationReport (PR/SHA/journal/
    receipts/стоимость/latency/human interventions/regression cases/ограничения). После успеха —
    **Execution Kernel Qualified**; findings рождают только адресные v3.0.x (не новый абстрактный аудит).
- **v3.1 — Observability, Evaluation & Safe Self-Improvement** (в работе, аддитивными инкрементами):
  - **v3.1.0 — Trace v0.2** ✅: event journal v0.2 (лок, verify-before-append, head-marker → детект
    усечения; trace-схема + `validate_trace`; Run/Attempt/Package/Gate/Delivery IDs); tokens/cost/latency
    (`run_cost` + `cost` в отчёте). Проверено вживую.
  - **v3.1.1 — Fix-loop** ✅: блокеры ревью/провалившихся проверок → писателю на итерацию поверх ветки
    (`resume`), бюджет `--fix-attempts`; fail-closed при исчерпании; конкретные blockers в fix-context;
    событие `fix_attempt`. По находке Phase B про green-throughput. Проверено live.
  - **v3.1.2 — CI hotfix** ✅: интеграционная часть fix-loop-selftest под guard `find_spec("pytest")`
    (CI имеет только pyyaml). Урок parity: прогонять и без openspec, И без pytest.
  - **v3.1.3 — Bench Lite** ✅: детерминированный ОФФЛАЙН, TOOL-FREE golden-корпус (`tools/bench_lite.py`)
    решений движка; BenchReport с метриками (pass/false_green/false_fail/review_blocked/fix_recovered);
    жёсткий инвариант `false_green == 0`; tool-free e2e fix-loop прогоняется в CI. В CI + AGENTS.md.
  - **v3.1.4 — Reviewer false-fail rate** ✅: known-good корпус в Bench Lite; `reviewer_false_fail_rate`
    + `engine_floor_ready` (полное добросовестное покрытие -> ready: движок НЕ источник false-fail) +
    `block_attribution` (какие гейты режут корректный код). Ре-фрейм находки Phase B на цифрах; безопасность
    (`false_green==0`) сохранена. Замер: rate=0.667, attribution={visual_regression, design_system_usage}.
  - **v3.1.5 — Golden tasks** ✅: known-good корпус расширен (6 known-good, 10 кейсов); kg_backend_control
    (backend/не-ui -> ready без ревью) + kg_strict_ux/a11y -> block_attribution покрывает все 4 UI-гейта.
    Вывод: reviewer-false-fail ЛОКАЛИЗОВАН в UI review-гейтах (не размазан); ENGINEERING блокируется раньше
    на артефакт-гейтах (не reviewer-false-fail). rate=0.667, engine_floor_ready=true, false_green=0.
  - **v3.1.6 — UI Gate Applicability + Shadow Policy** ✅: `tools/gate_policy.py` — таксономия
    `ui_impact`/`ui_change_kind`, `GatePolicyDecision` (applicability/enforcement/evidence_mode),
    `current`/`candidate`/`shadow_diff`. Bench Lite v0.2 (25 кейсов, матрица impact×kind×gate + abstain);
    метрики разведены: `policy_conformance` (движок исполняет policy: 100%) vs `quality_accuracy`
    (`synthetic_known_good_block_rate=0.571`, честно помечен синтетикой, `live=null`;
    `projected=0.381`). SHADOW: боевой fail-closed НЕ меняется; candidate не мягче current для
    user_facing/critical; accessibility не ослабляется никогда. В CI + AGENTS.md.
  - **v3.1.7 — Storybook Evidence Adapter** ✅: `tools/storybook_adapter.py`,
    `schemas/ui-evidence-bundle.schema.json`, `validation/validate_storybook_evidence.py`,
    `templates/quality/StorybookPolicy.md`. `UIEvidenceBundle` из локальных артефактов child-репо
    (Storybook static index + vitest/axe/visual/design-system results, сырые форматы нормализуются) —
    БЕЗ SaaS/MCP; kit НЕ React-app. Каждая секция несёт явный status (not_run/absent — «нет данных»
    не выдаётся за «чисто»). Семантическая валидация (статус нельзя разойтись с цифрами).
    `evidence_for_gate()` — shadow-мост к `gate_policy.evidence_mode` (visual=deterministic;
    design_system/accessibility/ux=hybrid). SHADOW: только сбор+валидация, enforcement нет. В CI+AGENTS.md.
  - **Маршрут v3.1 (утверждён владельцем 2026-07-23):**
    - **v3.1.8 — Calibrated UI Enforcement**: после shadow-замеров кандидатная политика становится
      боевой; вводится `GateResult v2` + миграционный адаптер (`not_applicable` / reviewer `abstain`).
      Промоушен-критерий: `false_green==0`, `known_good_block_rate ≤ 0.10` (или −70%), 0 safety-регрессий,
      100% policy-diff имеют reason; user-facing a11y и реальные визуальные регрессии по-прежнему блокируют.
    - **v3.1.9 — Phase B QualificationReport**: один формальный `ExecutionQualificationReport` на
      зафиксированной версии; добить 2-ю ENGINEERING green, sequential `ready_all`, provider
      interruption + resume в новой сессии, base-moved safe-block, delivery `outcome_unknown`
      reconciliation, одну реальную UI-задачу в child со Storybook. Scratch-репо + PR #1 сохраняются как evidence.
    - **v3.1.10 — Regression Corpus & Failure Taxonomy**: находки → постоянный корпус (failure_id,
      trigger, expected, regression_test, first_seen/fixed_version, affected_layer).
    - **v3.1.11 — Model Comparison & Safe Self-Improvement**: сравнительный Bench (quality/false-green/
      false-fail/fix-recovery/tokens/cost/latency); контролируемый цикл finding → ImprovementProposal →
      regression case → sandbox → Bench → independent review → human approval → canary. Без авто-merge,
      без авто-изменения security/lifecycle policy.
    - **v3.1.12 — Fast-forward Revalidation + v3.1 Exit**: сдвинутая база → integration worktree,
      перенос WorkItem-коммитов (конфликт=block), полный повтор checks/reviews/security, новый exact
      SHA + BaseBinding. После — v3.1 закрывается.
  - **Storybook по маршруту дальше**: v3.6 — Storybook MCP + manifests в Context Compiler; v3.7 —
    Product Bootstrap (авто-установка Storybook/MSW/interaction·a11y CI); v3.8 — Readiness
    Qualification через реальный UI-сценарий.
- **v3.2 — Architecture, Product & UI Governance**: ArchitectureDecision; quality attributes;
  C4/boundaries; architecture fitness checks; roadmap/dependencies/releases; Product Health; evolution
  triggers. **UI Governance**: StorybookPolicy; UI ArchitectureDecision; Definition of Done;
  контролируемый JSON UI renderer.
- **v3.3 — Product Learning + интеграция Research**: Research-контур уже фактически между v0.1 и v0.2
  (боевые RR/EV/DP, валидатор, grounding/freshness selftest, evaluation-harness). Будущий этап — НЕ
  создание Research с нуля, а его **интеграция** с Product Learning и управлением решениями: Research v0.2
  (source registry, uncertainty routing, memory-first, reuse evidence), FeatureLearning, solution options,
  design history, DecisionPackage → продуктовое решение.
- **v3.4 — Security & Economic Engineering**: data classification; capability permissions; provider
  policies; AI threat model; supply-chain security; budgets; model routing; caching; cost accounting.
- **v3.5 — Product Analytics, Observability & Evolution**: продуктовые метрики и guardrails; logs/metrics/
  traces; SLI/SLO; telemetry verification; post-release readout; scale assumptions; evolution triggers.
- **v3.6 — Semantic Context & Runtime Portability**: Repository Graph Lite (symbols/imports/routes/
  entities/tests); impact analysis; automatic write scope; relevant test selection; Claude/Codex/generic
  adapters; skills exporters.
- **v3.7–v3.8 — Greenfield Bootstrap & Readiness**: создание нового продукта с нуля (стратегия/
  исследование/архитектура/безопасность/экономика); repository bootstrap; первая вертикальная функция;
  полный greenfield qualification cycle.

- **Sequential WorkPackage Executor (веха v3.1; поставлен аддитивно в 2.117) ✅** — WorkPackages теперь РЕАЛЬНО исполняются по одному
  (`tools/workpackage_executor.py`): пакет→commit→evidence→gates→handoff→следующий, на общей ветке
  `ai-ops/<wid>` (resume поверх предыдущего). У каждого пакета свой коммит/SHA, свои гейты, свой
  RunHandoff и своя точка resume; зависимый пакет не стартует, пока `depends_on` не подтверждены;
  блок пакета (preflight/нет коммита/регрессия) ОСТАНАВЛИВАЕТ последовательность (следующие не
  стартуют). per-package отчёты в `features/<wid>/work-packages/<id>/report.json` + агрегат
  `sequence-report.yaml`. `ai-ops run … --sequential`. Доказано детерминированно: PQ9 + executor
  selftest (3 пакета, цепочка коммитов, стоп на блоке). Закрывает «WorkPackages создаются, но не
  исполняются».

Главный принцип (из аудита): не добавлять новый концептуальный слой, а превратить уже созданные
ContextBundle/SpecCoverage/WorkPackage/RunHandoff из отчётных артефактов в реальные управляющие входы
runtime.

## Правила движения по roadmap

- Каждая фаза проходит полный набор валидаторов; новые механизмы приносят свои
  валидаторы и self-test'ы вместе с собой.
- Новые агенты не принимаются без eval-кейсов (validate_agent_evals.py).
- Gates вводятся как non-blocking и становятся blocking только после обкатки на
  child-репозиториях.
- Capability-декларации честные: заявляем только реализованное, планы — со статусом
  `unsupported` + note "planned".
