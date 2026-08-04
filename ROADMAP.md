# Roadmap — путь к AI Product Operating System

Видение — в `VISION.md`. Здесь — что уже есть, чего не хватает и в каком порядке
закрываем разрыв. Каждая фаза — отдельный minor-релиз, аддитивный и обратно
совместимый в пределах 2.x; 3.x (текущий канал — **v3.21.0 stable**: Engineering Operating Model ЗАВЕРШЁН, срезы 1–3 (дисциплина коммита и ветки с детектом отставания базы; карта окружений и честная зрелость поставки + гейт `deploy_readiness`; экономическая граница ДО траты в preflight; `ai-ops engops`); Development Culture & Resource Guardrails завершён (гигиена сессий/контекста: телеметрия, пороги бюджета, Task Completion Ritual + `ai-ops session`; boundary classifier + культура делегирования; cost-aware work method + `ai-ops method`); Architecture Baseline (v3.15.0); Startup Context Budget завершён v3.12–3.14; UI Evidence Readiness (v3.11.0); Usage Truth (честный учёт модельных расходов, v3.10.0); First-class Claude Code Adapter + complexity-aware routing (v3.9.0); фаза v3.8 Product Bootstrap завершена в 3.8.0; точная версия в VERSION) остаётся обратно совместимым —
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
  постоянного runtime у кита по-прежнему нет. (v3.8: concurrent parallel-2 + governed fan-in доказаны
  live через `tools/parallel_live.py` — `tools/orchestrator.py` остаётся sequential.) Не строим: Robin
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

### Статус живой квалификации v3.0 (ИСТОРИЧЕСКОЕ, 2026-07-21) — ПЕРЕКРЫТО фазой v3.8/v3.9

> ⚠️ ИСТОРИЧЕСКОЕ. Первая живая квалификация ядра шла на claude-sonnet-5. Позже (v3.8/v3.9) доказано:
> **sonnet НЕ требуется** — сильный writer = локальный `claude -p` (first-class adapter), дешёвый портфель
> закрывает остальное, человек — strict security #5. Актуальный статус — в «Current Forward Roadmap».

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

## Current Forward Roadmap (актуально с v3.9.0)

**AI Ops 3.9.0 — квалифицированная фабрика изменений + first-class Claude Code executing adapter.**
Дальше данные с РЕАЛЬНЫХ продуктов определяют точечное развитие, а не наоборот.

- **v3.9.0** ✅ — First-class Claude Code Adapter (кит оркестрирует локальный `claude -p` read-only как
  СИЛЬНОГО writer'а; Claude предлагает, кит владеет worktree/diff/evidence/gates/delivery) +
  complexity-aware routing (сложный класс → сильный writer СРАЗУ; QUICK → дешёвый API; review → deepseek;
  strict security → человек). Доказано live end-to-end (writer≠judge, независимый deepseek поймал дефект
  claude, 0 false-green).
- **v3.9.1 / v3.9.2 — Release/Docs Truth Alignment** ✅: убран дрейф источников правды + claims-drift-детектор
  (расширен на docs/, `forbidden_stale_markers`).
- **v3.10.0 — Usage Truth** ✅: честный учёт ВСЕХ модельных вызовов (UsageRecord на writer/reviewer/fix-loop/
  fallback/escalation; usage_status measured|estimated|unavailable — неизвестное != 0; claude-cli usage
  измеряется; ledger задача+продукт; `ai-ops usage`).
- **v3.11.0 — UI Evidence Readiness** ✅: Storybook onboarding maturity (absent/configured/runnable/verified,
  `ai-ops onboard`); doctor сообщает ui-evidence; UI-CI только на UI-изменениях/VISUAL; build/interaction/axe/
  visual — отдельные честные статусы; отсутствие Storybook НЕ маскируется; кит не ставит зависимости за владельца.
- **v3.12.0 — Startup Context Budget, срез 1** ✅ (части 1→2→3): обязательные документы контекста
  (ProductStatus.md/now.md) доезжают до подключённых репозиториев — `ai-ops update` back-fill'ит черновики,
  doctor сообщает пробел, freshness-гейт проверяет контекст РЕПОЗИТОРИЯ (не селфтест кита), дефолт валидатора —
  контекст репо, шаблоны кита исключены. Аудит/референс: Proektnyy-ofis/ii-sreda.
- **v3.13.0 — Startup Context Budget, срез 2** ✅ (части 4/6): ярусы чтения `read_tier: 1|2|3` во frontmatter
  всех шаблонов + переписанный `ai-session-start` (ярус 1 всегда / 2 по теме / 3 по нужде); `tools/context_cost.py`
  (оценка стоимости старта с поправкой на кириллицу, разбивка, вердикт против `context_budget.session_start_tokens`)
  + строка в doctor + `--strict` как advisory-гейт; ProductStatus ≤~2КБ токенов.
- **v3.14.0 — Startup Context Budget, срез 3** ✅ (часть 5): управляемая стоимость самого кита —
  бюджет `description` скилла ≤300 символов (все 9 сокращены, сумма 3893→2498; валидатор
  `validate_runtime_surface`); `runtime_surface` (skills/commands: enabled) в `.ai-ops.yaml`; адаптеры только
  для `runtimes.configured` (не эмитим codex, если не включён). **Вся фича Startup Context Budget закрыта.**
- **v3.15.0 — Architecture Baseline** ✅: read-only `ai-ops audit architecture` (12 осей: модули/границы/
  зависимости/API/данные+миграции/интеграции/failure-modes/deployment/observability/security/ADR-дрейф/риски,
  детерминированно, честный not_detected); дешёвый baseline отдельно от полного AI-review; architecture-reviewer —
  обязательный независимый судья на architecture-сигналах (гейт architecture_review + механизм required_when).
- **v3.16.0 — Development Culture & Resource Guardrails, срез 1** ✅ (WP1+WP3+WP5): гигиена сессий/контекста —
  `session_telemetry` (честный снимок, unknown НЕ как 0), `SessionEconomyPolicy` (пороги 150/250/400k,
  one-task-per-session, advise-not-block), Task Completion Ritual с `SessionRecommendation`
  (continue/compact/clear/new_session) + точной командой; `ai-ops session`; интеграция в каждый прогон.
- **v3.17.0 — Development Culture Guardrails, срез 2** ✅ (WP2+WP4): Session Boundary Classifier
  (same_task/continuation/adjacent_subtask/new_independent_task/new_product, вшит в `ai-ops session`) +
  Delegation Culture (`delegation_advisor` + `DelegationPolicy.md`: разведка/логи/сравнение/research/review/
  mechanical → сабагент; в основной контекст только сводка, не сырьё).
- **v3.18.0 — Development Culture Guardrails, срез 3** ✅ (WP6): Cost-aware Work Method (`cost_method` +
  `ai-ops method`) — советы в порядке гигиена>делегирование>итерации>runtime>effort; собирает session_guardrails
  + delegation_advisor + model_router; affected-tests/не-читать-весь-репо/переиспользование.
  **Вся фича Development Culture & Resource Guardrails закрыта (3.16→3.18).**
- **v3.19.0 — Engineering Operating Model, срез 1** ✅ (WP1+WP2+WP3): CommitContract (`commit_policy` —
  жёстко: смешение зон кит/продукт, артефакты прогонов, `.env`/ключи, секрет в сообщении, protected_paths
  без approval, сообщение-заглушка; мягко: размер/scope/WorkItem/evidence) + BranchContract
  (`branch_policy` — жёстко: доставка движка только через PR, имя ветки прогона; мягко: **отставание базы**,
  рассинхрон базы с upstream, несколько WorkItem, возраст; `unavailable != 0`) + `EngineeringOperatingModel.md`
  + ключ `engineering_operating_model` в схеме + `validate_engops_policy` (связность порогов + паритет
  правило↔код) + `ai-ops engops` + 2 строки doctor. Мотив: ветка дочки отстала от main на 234 коммита,
  и это не было ничьей ответственностью.
- **v3.20.0 — Engineering Operating Model, срез 2** ✅ (WP4+WP5+WP6): EnvironmentMap (`environment_map` —
  окружения объявлено vs обнаружено в CI `environment`/`.env.<name>`; находки `detected_not_declared`
  (CI деплоит туда, где нет владельца и правил доступа), `declared_not_detected`,
  `production_without_approvers`; **секреты только ИМЕНАМИ**, значения не читаются и в отчёт не попадают)
  + DeployReadiness (`deploy_readiness` — лестница absent/configured/runnable/verified; **без объявленного
  отката verified недостижим**; платформенная поставка отмечается как путь ВНЕ репозитория, а не
  «задеплоить нечем») + детерминированный blocking-гейт `deploy_readiness` с `required_when`
  [deployment_change, new_service, infrastructure_change], чек-лист `rules/quality/deploy-readiness.yaml`,
  исполнение в `gate_executor` (недоступность инструмента → `warn`, не `pass`) + ключи
  `environments`/`deploy` в схеме + `ai-ops engops env|deploy` + 2 строки doctor. gate-count 30 → 31.
- **v3.21.0 — Engineering Operating Model, срез 3** ✅ (WP7): EconomicPreflight (`economic_preflight`) —
  граница расхода ДО первого вызова модели. Прежде деньги узнавались ПОСЛЕ траты (контекстный бюджет их
  не касался, `Budget.charge_call` рвался на N-м вызове, `cost_account` сверял после). Оценка по истории
  `usage_ledger` против `RunPlan.execution_budget`, встроена в `preflight.py` шагом 7. Решение по ХУДШЕМУ
  сравнимому прогону; нет истории → `unavailable`, НИКОГДА 0, и НЕ блок; частично неизвестная стоимость →
  честная НИЖНЯЯ ГРАНИЦА с предупреждением; никаких выдуманных коэффициентов по writer_tier.
  Ключ `economics` в схеме, `ai-ops engops cost`, строка doctor.
  **ВСЯ ФИЧА ENGINEERING OPERATING MODEL ЗАКРЫТА (3.19 → 3.21).**
- **Затем — Autonomous Operation** (прежний 3.15 из спеки владельца): worker, `ai-ops do`, ask-once,
  blocker resolver.
- **Real-Product Qualification:** 10 РЕАЛЬНЫХ задач на продуктах владельца через `./ai-run`; данные
  (owner_effort, где кит ускоряет/страхует/мешает, регрессии, стоимость/latency из Usage Truth) решают дальнейшее.
- **После данных (точечно, ПО ФАКТАМ):** DX; устойчивость runtime; адресный рефакторинг. **Дальше:** Codex
  executing adapter; multi-product control plane.

### Историческая дорожная карта ядра (v3.0.14 → v3.1, ЗАКРЫТА — путь к Execution Kernel Qualified)

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
- **v3.1 — Observability, Evaluation & Safe Self-Improvement** ✅ **ЗАКРЫТ** (Execution Kernel
  qualified; известные ограничения перечислены; внешне-gated green-path сценарии — rolling evidence,
  НЕ ворота roadmap). Поставлен аддитивными инкрементами:
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
  - **v3.1.8 — Calibrated UI Enforcement** ✅ (ПЕРВОЕ изменение боевого fail-closed за v3.1):
    калиброванная политика ЖИВАЯ в контроллере (`calibrated_enforcement=True`); хук в
    `execution_pipeline._run_reviews` — reviewer `warn` не блокирует при advisory-тире / `evidence=pass`;
    `evidence=fail` блокирует всегда (усиление); critical ux/a11y требуют human-signoff. `GateResult v2`
    (`gate_result_v2.py`, +not_applicable/abstain) + адаптер v2→v1. **NO-OP** без богатых сигналов
    (легаси ui_changed→user_facing→fail-closed). Доказано на Bench Lite v0.3 (реальный A/B):
    block-rate 0.667→0.333 (−50%), residual_false_fail_rate=0.0 (≤0.10), false_green=0, safety-регрессии
    (evidence=fail) блокируются 2/2. Reviewer `abstain` (эмиссия) — future. В CI+AGENTS.md.
  - **v3.1.9 — Phase B QualificationReport** ✅: `qualification/PHASE-B-QUALIFICATION-REPORT.md` —
    честно разделяет ДВЕ вещи: гарантии ядра qualified live (QUICK green, ENGINEERING→PR #1
    sha_verified, delivery reconciliation, fail-closed непробиваем, 0 false-green/0 duplicate PR); а
    несколько положительных green-path сценариев (2-я ENGINEERING green, полный sequential
    ready_all, реальная UI-задача) — **rolling evidence**, зависят от сильного провайдера и
    React/Storybook-тулчейна и НЕ удерживают roadmap. Живьём подтверждён fail-closed под слабой
    моделью (DeepSeek: ENGINEERING → блок, PR не открыт). **v3.1 закрыт.**
  - Содержимое старой лестницы v3.1.10–v3.1.12 перенесено в крупные фазы: model comparison → **v3.4**;
    regression corpus / failure taxonomy → **v3.5**; fast-forward integration revalidation → **v3.6**.
- **v3.2 — Architecture, Product & UI Governance** ✅ **ПЕРВЫЙ ПРОХОД ВЫПОЛНЕН** (governance-слой
  `ADR → quality attributes → health → evolution` замкнут):
  - v3.2.0 `ArchitectureDecision`-контракт + UI Definition of Done;
  - v3.2.1 ADR-реестр (`decisions/adr/`) + fitness (supersede-цепочки, ui_impact ∈ gate_policy);
  - v3.2.2 quality-attributes fitness (профиль + детект необоснованного degrade и противоречий);
  - v3.2.3 Storybook component-reuse enforcement (новый компонент, дублирующий каталог, = дефект);
  - v3.2.4 evolution-triggers (ADR → обещанный quality attribute → Product Health → сигнал пересмотра).
- **v3.3 — Product Learning + интеграция Research** ✅ **ЗАКРЫТ** (строился НАД research-контуром,
  слабой ссылкой на `DecisionPackage`, без касания `.research/`):
  - v3.3.0 ✅ `FeatureLearning` (`DecisionPackage` → гипотеза → проверка → verdict → learnings →
    follow_up); реальная цепочка `DP-108 → FL-001 → ADR-001`;
  - v3.3.1 ✅ learning-loop fitness (`follow_up` ADR-ссылки резолвятся в реальный реестр);
  - v3.3.2 ✅ Operational Architecture Backbone (ТОЛЬКО контракты — см. раздел ниже):
    `ContextArchitectureDecision`, `LoopPolicy`, `WorkGraph`, `ParallelSafetyDecision`,
    `IntegrationPlan` + пример `examples/work-graph-demo`;
  - v3.3.3 ✅ Product Learning Completion: `completion` (delivery/learning/outcome), явные решения
    continue/change/stop/investigate/scale, solution_options, research_gap (uncertainty→research),
    reuse evidence, supersede-цепочка. Живая приёмка: FL-001 confirmed→scale→ADR-001; FL-002
    refuted→change (DeepSeek недостаточен для ENGINEERING); FL-003 research-gap→investigate→RR.
  - **Отложено из v3.3.2 (runtime, не контракт):** доведение `GateResult v2` до канонического
    runtime-формата (not_applicable/advisory/blocking, reviewer `abstain`, targeted retry, human
    handoff) — отдельный runtime-инкремент, не удерживает закрытие v3.3.
- **ТЕКУЩАЯ ФАЗА → v3.6 — Semantic Context Engine + Governed Parallel Execution + Storybook MCP** (см. ниже).

### Post-v3.2 Operational Architecture Backbone (объединяющая операционная архитектура)

Основание уже есть (Context Compiler v1 с payload/provenance/token-budget; последовательный
WorkPackage Executor; `active-work` с affected-areas/shared-contracts/dependencies/conflict-forecast).
Не хватает **объединяющих контрактов** — их вводит v3.3.2, БЕЗ второго executor'а/второй context-
системы/scheduler'а/vector-DB/MCP:

- **Context Architecture** (развитие Context Compiler, не отдельная «векторная память»): repository =
  источник истины; retrieval `policy/metadata → Repository Graph → full-text → semantic fallback →
  reranking → budgeted role view`. Инвариант: exact-revision binding, provenance, access-filter ДО
  retrieval, stale detection, role-views (planner/executor/UI-reviewer/security/integration),
  cache-key = repository + SHA + policy + view.
- **Governed Loops** (`LoopPolicy`: trigger/budgets/success/stop/progress/on_stop/escalation). Типы
  регистрируются (implementation/review-fix/UI-Storybook/research/product-learning/safe-improvement),
  движки НЕ строятся; существующий fix-loop — первая реализация общего контракта.
- **Parallel Architecture** (`WorkGraph` + `ParallelSafetyDecision` + `IntegrationPlan`): packages/
  depends_on/write_scope/shared_contracts/execution_mode(single|sequential|parallel|hybrid)/
  integration_order/aggregate_verification. **Инвариант: успешные package-SHA не доказывают
  успешность всей работы — после fan-in нужен новый integration-SHA и полный повтор проверок.**

Активация этих механизмов (не только контрактов) требует ограничений безопасности/экономики (v3.4)
и наблюдаемости (v3.5); полная реализация — v3.6.

- **v3.4 — Security, Permissions & Economics** ✅ **ЗАКРЫТ** (три инварианта + residency + учёт +
  выбор модели — контрактами):
  - v3.4.0 ✅ BudgetContract (никакой scope без бюджета; поверх tools/budget.py + run_cost);
  - v3.4.1 ✅ PackageCapabilityScope (никакой package без capability-scope; least-privilege);
  - v3.4.2 ✅ AccessFilterPolicy (никакой retrieval без access-filter; deny-by-default, секреты вне context);
  - v3.4.3 ✅ ProviderResidencyPolicy (секреты не в облако, confidential не в external-cloud; кросс-проверка providers.yaml);
  - v3.4.4 ✅ cost accounting (tools/cost_account.py: spent vs BudgetContract по scope);
  - v3.4.5 ✅ model comparison (tools/model_comparison.py: safety-first, false_green>0 → дисквалификация).
- **v3.5 — Observability, Regression Corpus & Evolution Loops** ✅ **ЗАКРЫТ** (loops и параллель
  измеримы; находки — постоянный корпус; петля доставили→измерили→узнали замкнута):
  - v3.5.0 ✅ Regression Corpus + Failure Taxonomy (RegressionCase, RC-001..004 по слоям);
  - v3.5.1 ✅ Loop/Iteration trace + no-progress/repeated-failure detection (LoopTrace);
  - v3.5.2 ✅ WorkGraph/integration trace + parallel-vs-sequential (IntegrationTrace, integration-SHA инвариант);
  - v3.5.3 ✅ post-release readout (PostReleaseReadout: DeliveryReceipt→CI→Health→evolution→решение).
- **v3.6 — Semantic Context Engine + Governed Parallel Execution + Storybook MCP** — **OFFLINE-веха
  (v3.6.6) + Runtime Promotion Readiness & Live Qualification (v3.6.7, 2026-07-27)**.
  OFFLINE-scope ✅ (v3.6.0–6): retrieval-цепочка + Retrieval Integrity + GateResult v2 runtime + bounded
  parallel-2 planner + read-only Storybook.
  Runtime Promotion Readiness ✅ (v3.6.7a–d): exact-snapshot proof, mandatory-blocks-view, child-политики,
  fail-closed integration_gate, TS/docs retrieval.
  **Живая квалификация (v3.6.8) — проведена на moonshot/kimi; результаты:**
  ✅ ядро safety-qualified (0 false-green); ✅ зелёный ENGINEERING draft PR (`sha_verified`); ✅ Context
  Engine v2 в SHADOW (`snapshot_verified` на точном SHA); ✅ UI-CI capability (реальный
  interaction/a11y/pixel-visual/design-system evidence, отдельные UI-гейты зелёные); ✅ parallel-2
  decision-layer + 10/10 негативов; **5 реальных багов кита найдено и починено** (shadow-sha,
  provider-timeout, verdict-observability, P1 security-evidence-type, UI-CI collector).
  ОСТАЁТСЯ (v3.7-объём, ранее «не сейчас», + сильная модель): **живой parallel-executor** (concurrent
  worktrees + fan-in integration + один PR) и **hybrid/default промоушен Context Engine** (сейчас по коду
  только sequential executor + shadow); стабильный полный зелёный multi-gate UI/ENGINEERING PR за один
  прогон (kimi — лотерея на строгий review; нужен sonnet-класс).
  Полная реализация (план фазы):
  Context Engine v2 строгой последовательностью (`metadata → Repository Graph Lite → full-text →
  role/package views → cache → retrieval Bench → semantic fallback → incremental index` — НЕ начинаем
  с vector-DB). Parallel execution (WorkGraph planner → safety classification → isolated package
  worktrees → shared-contract-first → bounded scheduler → fan-in integration worktree → aggregate
  checks/reviews → exact integration SHA → один DeliveryIntent → один draft PR). **fast-forward
  integration revalidation** (перенос из старого v3.1.12). Storybook: manifests в Context Compiler +
  Storybook MCP-адаптер + package-level UI context + новый UIEvidenceBundle на integration-SHA после
  fan-in (текущий exact-SHA evidence и reuse-enforcement НЕ переписываются).
- **v3.7 — Runtime Activation ✅ ВЫПУЩЕН** (v3.7.0 stable 2026-07-28; v3.7.1 Trust Alignment). Провайдер-
  независимость стала ПОВЕДЕНИЕМ рантайма (не только реестром/резолвером), доказана живьём БЕЗ Anthropic:
  - **Money-based routing** (`model_router`+`provider_endpoints`): без `--model` роль резолвится в
    конкретную модель по ДЕНЬГАМ (deepseek-v4-flash $0.0115 < qwen $0.072 < kimi $0.467) и диспатчится на
    endpoint вендора; `rep.model_resolution` в каждом отчёте. ✅ (v3.7.10/12/15, live smoke).
  - **Context Hybrid fed_to_model** ✅ (v3.7.16): hybrid строится ДО model-call, exact-snapshot
    (require_snapshot=True), additions реально в prompt, полный token-budget (v3.7.1 #3).
  - **Governed multi-package fan-in** ✅ (v3.7.17): пакеты → package-SHA → git fan-in → integration-SHA →
    повтор aggregate → ОДИН реальный PR. Честно: execution_concurrency=serial (не настоящий concurrency;
    отдельные клоны на пакет — позже), parallel_safe по write_scope (v3.7.1 #2).
  - **Security enforcement** ✅: key_preflight РЕАЛЬНЫЙ барьер (TTL/now, ready=false->blocked-preflight);
    merge_memory self-ingested без human_confirmed НЕ пишется (v3.7.1 #4); strict judge — нет qualified
    security-судьи -> pending_human, self-model не закрывает security (v3.7.1 #1).
  ОТКРЫТО (post-3.7, в v3.8/Bench v2): qualified АВТОсудьи (security/integration) — пока human-fallback;
  настоящий concurrent parallel (отдельные клоны); точная ревизия DeepSeek V4 Flash; verify_artifact loader.
- **v3.8 — Product Bootstrap & Readiness Qualification (ТЕКУЩАЯ ФАЗА)**: greenfield (architecture → backend/frontend+
  Storybook/data/CI/observability) → parallel fan-out → integration → первая вертикальная функция →
  release → measurement → learning → readiness report (single/sequential/parallel/resume/fix-loop/
  release/post-release/product-learning на нескольких реальных child-репо).

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
