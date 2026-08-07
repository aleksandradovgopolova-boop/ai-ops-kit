# CHANGELOG — AI-first система (пакет)

Формат: [SemVer](https://semver.org/lang/ru/). Версия пакета — в `VERSION`.

## [Unreleased]

## [3.28.0] — 2026-08-06 — Verification Foundation II

Запись восстановлена 2026-08-07: релиз 3.28.0 вышел БЕЗ записи в CHANGELOG, из-за чего
`changelog_gen` держал `package-quality` красным на main с 6 августа. Содержание собрано по
релизному коммиту `85dc201` и последующим правкам того же среза.

Тесты:
- 34 → 230 тестов pytest: 161 unit (10 модулей), 19 property-based (hypothesis) на budget,
  usage_ledger, security_scan, preflight, 16 на kit_observability;
- дальнейший набор покрытия до 732 тестов (execution_pipeline 53%, ai_ops_run 75%),
  заполнены contract-заглушки, закрыты модули с 0%.

Типизация:
- `tools/contracts.py` — 8 TypedDict (UsageRecord, PreflightResult, GateResultV2, RunReport,
  DeliveryIntent/Receipt, ContextBundle, WorkItemState), интеграция в preflight и usage_ledger.

Архитектура:
- `orchestrator.py` 3210 → 606 строк; извлечены `orchestrator_http.py`,
  `orchestrator_providers.py`, `orchestrator_usage.py` с полной обратной совместимостью
  (re-export). Позже так же разделён `execution_pipeline`.

CI:
- `package-quality.yml` — один job заменён на 7 параллельных групп (`.github/ci-groups/`).

Пакет:
- `pyproject.toml` + `setup.py` (`pip install -e .`), `tools/__init__.py`,
  `validation/__init__.py`; включён coverage, добавлены бенчмарки производительности и
  автоматизация changelog.

## [3.27.7] — 2026-08-06 — Fix: claude -p writer переживает транзиентный 529 (F-011)

Патч-релиз (без новой функциональности). Устойчивость первоклассного локального writer'а
`claude -p` к транзиентным сбоям API Anthropic.

Исправления:
- `orchestrator._claude_cli_call`: транзиентные 5xx/429/**529 Overloaded** ретраятся с
  экспоненциальным backoff+jitter (прежде — 3 фикс-паузы 3с/6с; один невосстановленный 529
  ронял весь многошаговый прогон). Синтетический `is_error:true` на rc==0 (конверт 529:
  input_tokens:0, stop_reason:stop_sequence) распознаётся и НЕ выдаётся за валидный результат.
  Полный человекочитаемый текст ошибки claude сохраняется (парсинг content[].text/error),
  а не режется до 200 символов.
- `tests/contracts/test_critical_path.py`: +3 регрессионных теста (positive транзиент-529 →
  ретрай → успех; fail-closed `is_error` не отдаётся за результат; полный текст ошибки не обрезан).

Находка Real-Product Qualification F-011: writer=claude -p не финишировал реальный brownfield-таск
из-за транзиентного 529 + мелкого ретрая. После фикса прогон сошёлся живьём (recentTimeGroup 10/10,
регрессий 0). Также приведены к текущей версии публичные маркеры README/ROADMAP (release truth).

## [3.27.6] — 2026-08-05 — Corrective Release: восстановление release truth

Корректирующий релиз без новой функциональности. Исправляет дрейфы после 3.27.x и
восстанавливает доверие к CI/CD.

Исправления:
- gate-count claim: 31 → 32 (analytics_readiness → analytics_design_readiness + analytics_runtime_verification)
- ai_ops_run.py selftest: analytics_readiness → analytics_design_readiness + проверка что
  analytics_runtime_verification НЕ входит в дорелизный RunPlan
- package-quality.yml: добавлен pytest tests/contracts/ (20 process contract tests)
- release.yml: stable Release создаётся ТОЛЬКО после успешного package-quality на том же SHA
  (workflow_run trigger вместо push trigger)

## [3.27.5] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP6): Process Contract Tests

20 contract tests, доказывающих инварианты процессов.

TestGateCoverageMatrix (8 тестов):
- PRODUCT требует code_review, security, architecture_review, deploy_readiness
- CRITICAL требует architecture_review, deploy_readiness
- gates applicability включает PRODUCT и CRITICAL

TestAnalyticsGateSplit (5 тестов):
- analytics_design_readiness существует и НЕ требует events_verified_live
- analytics_runtime_verification существует и ТРЕБУЕТ events_verified_live
- PRODUCT/ANALYTICS/ADOPTION используют analytics_design_readiness

TestProgressiveVerification (4 теста):
- docs-only возвращает skip tier
- draft intent возвращает affected tier
- merge_candidate intent возвращает full tier
- no affected tests возвращает targeted_tests_not_found (impact_unknown)

TestReleaseEvidence (3 теста):
- released без DeliveryReceipt -> fail
- released с SHA-verified DeliveryReceipt -> ok
- released с sha_verified=false -> fail

## [3.27.4] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP5): Release Evidence

feature.status=released теперь требует SHA-verified DeliveryReceipt, а не просто done-артефакт.

Проблема: ранее feature.status=released доказывался наличием любого done-артефакта. Это мог
быть problem statement из discovery — не доказательство поставки.

Решение: feature.status=released требует:
1. Хотя бы один done-артефакт (как раньше)
2. SHA-verified DeliveryReceipt (PR смержён, SHA совпадает с remote)

DeliveryReceipt ищется в:
- features/<feature_id>/delivery-receipt.yaml
- .ai/runtime/delivery/<workitem_id>/receipt.yaml

validate_feature_blueprint.py обновлён:
- 9 selftest'ов (добавлены 3 теста для WP5)
- released без DeliveryReceipt -> fail
- released с SHA-verified DeliveryReceipt -> ok
- released с DeliveryReceipt, но sha_verified=false -> fail

## [3.27.3] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP4): Progressive Verification Truth

Исправление проблем Progressive Verification для честной и быстрой верификации.

- **verification_tiers.py** — расширен:
  - Добавлен `skip` tier для docs-only (не запускаем product build/test)
  - Добавлен `impact_status`: targeted_tests_found / targeted_tests_not_found / docs_only
  - Добавлен `lifecycle_intent` параметр: explore→skip, draft→affected, ready_for_review→module, merge_candidate→full
  - Команды тестов берутся из project_detector (child config), не угадываются pytest/jest
  - 15 selftest'ов

- **evidence_collector.py** — обновлён:
  - Поддержка `skip` tier: docs-only возвращает pass с skip_verification evidence
  - Передаёт impact_status в verification info

- **package-quality.yml** — добавлено условие:
  - `if: github.event.pull_request.draft == false` — не запускаем полный CI для draft PR

Решённые проблемы:
- docs-only → без product build/test (skip tier)
- no affected tests → impact_unknown, не "не влияет" (targeted_tests_not_found)
- команды test runner из child config (project_detector)
- explicit draft/merge/release tier (lifecycle_intent)
- condition для draft PR в full CI (if: draft == false)

## [3.27.2] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP3): Analytics Gate Split

Разделение analytics_readiness на два гейта для решения временного парадокса.

- **analytics_design_readiness** (blocking, до merge): tracking_plan, event_schema,
  product_metrics, dashboard_spec. Применяется в PRODUCT, ANALYTICS, ADOPTION.
- **analytics_runtime_verification** (blocking, после deploy): events_verified_live,
  no_pii_in_events, cohort_identification_works, dashboard_receives_data.
  Применяется после release, не в workflow gates.

Проблема: analytics_readiness требовал events_verified_live до merge, но live-поток
появляется только после deployment. Это приводило к блокировке или формальному закрытию.

Решение: design-часть (tracking plan, schema, metrics, dashboard spec) проверяется до merge.
Runtime-verification (события реально приходят, нет PII, cohort работает) — после deploy.

- quality/gates.yaml: analytics_readiness → analytics_design_readiness + analytics_runtime_verification
- registry/workflows.yaml: ANALYTICS и ADOPTION используют analytics_design_readiness
- registry/tracks.yaml: ANALYTICS track добавляет analytics_design_readiness

## [3.27.1] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP2): Gate Coverage Matrix

Исправление пробелов в матрице workflow → gates. PRODUCT и CRITICAL теперь имеют полный
контур качества.

- **quality/gates.yaml** — расширена applicability:
  - code_review: [ENGINEERING, CRITICAL] → [ENGINEERING, CRITICAL, PRODUCT]
  - security: [ENGINEERING, CRITICAL] → [ENGINEERING, CRITICAL, PRODUCT]
  - architecture_review: [ENGINEERING, AI_FEATURE] → [ENGINEERING, AI_FEATURE, PRODUCT, CRITICAL]
  - deploy_readiness: [ENGINEERING, AI_FEATURE] → [ENGINEERING, AI_FEATURE, PRODUCT, CRITICAL]

- **registry/workflows.yaml** — добавлены missing gates:
  - PRODUCT: +code_review, +security, +architecture_review, +deploy_readiness
  - CRITICAL: +architecture_review, +deploy_readiness

- PRODUCT теперь не может пройти без независимого code review, security check,
  architecture review (при архитектурных сигналах) и deploy readiness (при изменении поставки).
- CRITICAL теперь не может пройти без architecture review и deploy readiness.

## [3.27.0] — 2026-08-05 — Process Applicability & Lifecycle Truth (WP1): Lifecycle Intent

Первый шаг плана Process Applicability & Lifecycle Closure. Добавлена единая стадия
жизненного цикла задачи (lifecycle_intent), которая определяется детерминированно из
состояния WorkItem.

- **tools/lifecycle_intent.py** — новый модуль для определения lifecycle stage:
  - Стадии: discovery, implementation, review, delivery, completed
  - Терминальные: cancelled, superseded, abandoned
  - `derive()` — детерминированный вывод из status/evidence/PR/receipt
  - `validate_transition()` — проверка допустимости переходов
  - `intent_to_lifecycle()` — маппинг CLI intents на lifecycle stages
  - 22 selftest'а

- **schemas/workitem.schema.json** — добавлено поле `lifecycle_intent` (optional, enum)

- **tools/workitem.py** — интеграция lifecycle_intent:
  - `start()` инициализирует lifecycle_intent="discovery"
  - `derive_status()` вычисляет lifecycle_intent детерминированно
  - `status_cmd()` сохраняет lifecycle_intent в workitem.yaml

- Детерминированный вывод:
  - draft без evidence → discovery
  - draft с evidence → implementation
  - done без PR → implementation
  - done с PR → review
  - done с merged PR → delivery
  - done с receipt → completed
  - needs_human_decision → review
  - blocked без evidence → discovery
  - blocked с evidence → implementation

## [3.26.3] — 2026-08-05 — Progressive Verification: fix-loop integration

Интеграция progressive verification в fix-loop (автоматическая через execution_pipeline).

- Fix-loop уже использует progressive verification автоматически: каждая итерация
  вызывает `run_pipeline()`, который вычисляет `changed_files` и передаёт их в
  `evidence_collector.collect(changed_files=...)`.
- Это означает: на каждой итерации fix-loop запускаются только затронутые тесты
  (affected tier) вместо полного набора — быстрее обратная связь.
- Добавлен параметр `progressive_escalation` в `run()` для будущей escalation
  к full verification на последней итерации (зарезервирован, не активен).
- Полная цепочка Progressive Verification завершена:
  `commit → changed_files → verification_tiers → evidence_collector → targeted tests`
  работает на всех уровнях: pipeline, fix-loop, baseline-diff (full для baseline).

## [3.26.2] — 2026-08-05 — Progressive Verification: execution_pipeline integration

Интеграция progressive verification в execution_pipeline.

- `run_pipeline()` теперь автоматически вычисляет `changed_files` после коммита
  через `_committed_changed_files()` и передаёт их в `evidence_collector.collect()`.
- Это включает targeted test execution: для небольших изменений запускаются только
  затронутые тесты (affected tier) вместо полного набора.
- Baseline-diff НЕ использует changed_files (полный прогон ДО изменений — корректно).
- Результат evidence включает `verification` поле с информацией о выбранном tier.

## [3.26.1] — 2026-08-05 — Progressive Verification: evidence_collector integration

Интеграция verification_tiers в evidence_collector для targeted test execution.

- `evidence_collector.collect()` теперь принимает `changed_files` параметр.
- Если changed_files задан, используется `verification_tiers.select_tests()` для определения
  targeted test command (affected/module/full tier).
- Для tier=affected/module запускаются только затронутые тесты вместо полного набора.
- Для tier=full или отсутствия targeted command — обычный полный прогон.
- Результат включает `verification` поле с информацией о выбранном tier и affected tests.
- CLI: `evidence_collector.py collect --changed file1 file2` для progressive verification.
- Selftest: 14 тестов (включая 4 новых для changed_files).

## [3.26.0] — 2026-08-05 — Progressive Verification: test selection + verification tiers

Фундамент для прогрессивной верификации — проверки масштабируются по размеру изменений.

- **repo_graph.py расширен для Node/TypeScript.** Добавлен `_analyze_js()` — regex-based парсинг
  импортов (ES modules + CommonJS) и символов (export function/class/const). `build_graph()`
  теперь включает JS/TS файлы (опция `include_js=True`). Поддерживаемые расширения: .js, .jsx,
  .ts, .tsx, .mjs, .cjs. Пропускаются node_modules, dist, build, .next, coverage.
- **affected_tests()** — новая функция в repo_graph: какие тесты затронуты изменениями.
  changed_files → impact() → test files, которые импортируют затронутые модули (транзитивно).
- **verification_tiers.py** — новый модуль для определения уровня верификации:
  - `affected` — только затронутые тесты (быстро, для итерации)
  - `module` — все тесты затронутых модулей (средне, для checkpoint)
  - `full` — полный набор (медленно, для merge/release)
  - `decide_tier(changed_files)` — автоматический выбор: критическая инфраструктура → full,
    документация → affected, >20 файлов → module.
  - `select_tests(changed_files, child_root, tier)` — test selection engine: возвращает
    `{tier, affected_tests, targeted_command, note}`.
- **CLI:** `repo_graph.py --affected-tests file1 file2` — показать затронутые тесты.
  `verification_tiers.py --changed file1 file2 [--tier affected|module|full]` — выбрать тесты.
- **Selftest'ы:** repo_graph — 20 тестов (Python + JS/TS + affected_tests); verification_tiers —
  10 тестов (decide_tier + select_tests).

## [3.25.1] — 2026-08-05 — CI Trigger Fix: полный CI не на каждый draft PR

Исправление дефекта процесса: `package-quality.yml` запускался на каждый PR, делая `pr-smoke`
бессмысленным. Теперь полный CI запускается только когда PR действительно готов.

- `package-quality.yml` триггеры: `pull_request: types: [ready_for_review, synchronize]` —
  полный CI запускается только при выходе из draft или новом коммите в non-draft PR.
- `pr-smoke.yml` остаётся на каждом PR — быстрая проверка критического пути (~2 мин).
- Лестница проверок: draft → smoke; ready for review → full; merge → full на актуальном SHA.

## [3.25.0] — 2026-08-05 — Verification Foundation: pytest, test harness, CI layers

Фундамент тестовой инфраструктуры. Не переписываем 199 selftest'ов — добавляем pytest как
агрегатор, contract tests для critical path, и разделяем CI на слои.

- **tests/ структура.** Создана иерархия: `unit/`, `contracts/`, `integration/`, `live/`,
  `regression/`. Каждый слой — для своего типа тестов и CI-триггера.
- **conftest.py с selftest wrappers.** 142 существующих selftest'а из `tools/` и `validation/`
  обёрнуты в pytest-совместимые функции. Старые `--selftest` продолжают работать, новые
  contract tests живут в `tests/contracts/`. Постепенная миграция без массового переписывания.
- **Contract tests для critical path.** `tests/contracts/test_critical_path.py` — 11 тестов,
  проверяющих контракты критических модулей (orchestrator, execution_pipeline, usage_ledger,
  lifecycle_store). Включая регрессию на claude-cli NameError (v3.21.1).
- **CI layers.** Создан `.github/workflows/pr-smoke.yml` — быстрый слой для PR (~2 мин):
  contract tests + critical path selftests + key validators. Полный CI остаётся на main/release.
- **pytest.ini.** Конфигурация pytest с маркерами (critical_path, unit, contract, integration,
  live, regression, slow) для разделения тестов по слоям CI.
- **Fixtures.** `temp_repo`, `child_root`, `mock_provider` — переиспользуемые фикстуры для
  тестов, требующих временной структуры репозитория.

## [3.24.0] — 2026-08-05 — Cost & Architecture Accuracy: технические хвосты

Закрываем технические хвосты, которые мешают точной экономической оценке и архитектурному контролю.

- **UsageRecord расширен.** Новые поля: `task_type`, `workflow`, `risk`, `size`, `writer_tier`,
  `execution_mode`, `stack`, `architecture_impact`. Заполняются через `extra_context` в
  `usage_ledger.append()` из signals/plan/model_resolution. Старые записи получают `None` (честно).
  `aggregate()` теперь группирует по `by_task_type`, `by_workflow`, `by_writer_tier` — для ответа
  на вопрос «сколько стоит QUICK vs PRODUCT vs ENGINEERING».
- **Parallel Ledger Fan-In.** `usage_ledger.merge_ledgers(child_root, source_roots)` — сводит
  usage-ledger из нескольких параллельных клонов в основной продукт. Дедупликация по
  (run_id, role, input_tokens, output_tokens, latency). Закрывает старый хвост: расходы
  parallel-пакетов записывались в ledgers отдельных клонов, но не сводились в родительский
  product ledger на fan-in.
- **Architecture Baseline Drift Detection.** `architecture_baseline.diff_baselines(old, new)` —
  сравнивает два baseline по 12 осям, возвращает `{axis: {added, removed, changed}}`. Пустой
  dict = нет дрейфа. Используется для обновления baseline при значимых изменениях.
- **Architecture Signals from Diff.** `architecture_baseline.architecture_signals_from_diff(changed_files)` —
  автоматически выводит сигналы (architecture_change, new_service, cross_boundary_change,
  breaking_api, data_migration, new_integration, deployment_change) из списка изменённых файлов.
  Закрывает риск: продакт может не понять, что задача архитектурно значимая, а классификатор
  может не выставить сигнал. Теперь сигналы выводятся детерминированно из путей файлов.

## [3.23.0] — 2026-08-05 — Engineering Advisor: слой «как лучше сделать»

Не добавляем новых проверок — добавляем слой рекомендаций, который отвечает на вопрос
«как лучше сделать эту задачу», а не только «прошла ли она гейты».

- **`ai-ops advise` — новый intent.** Инженерный совет без исполнения: `ai-ops advise "задача"`
  показывает рекомендации по трём осям. Read-only, не меняет код, не запускает движок.
- **Environment Recommendation.** На основе `environment_map` + `deploy_readiness`: какие окружения
  обнаружены, какая зрелость доставки (absent/configured/runnable/verified), какие пробелы
  (preview/staging отсутствуют, production без approvers, rollback не объявлен). Конкретные
  рекомендации: «добавьте PR-based preview», «объявите approvers для production».
- **Delivery Plan per Task.** На основе `project_detector` + `commit_policy` + `branch_policy` +
  `deploy_readiness`: branch strategy (`ai-ops/<wid>` от свежей main), commit boundaries (один
  коммит = один revertible шаг, не смешивать зоны), affected tests (какие команды запускать),
  deploy/rollback readiness, feature flag для PRODUCT/CRITICAL.
- **Economic Alternatives.** На основе `economic_preflight`: оценка стоимости из истории репозитория
  (медиана/худший/нижняя граница). Перед написанием кода — проверка альтернатив: (1) не делать
  сейчас; (2) настройка вместо кода; (3) переиспользование компонента; (4) меньший scope.
  Если `confirm_required` или `block` — явные рекомендации по снижению стоимости.
- **Композиция.** `tools/engineering_advisor.py` следует паттерну `cost_method.py`: собирает
  `{priority, category, advice, source}` tuples из существующих модулей, сортирует по приоритету.
  Advise, не block — рекомендации, а не требования.

## [3.22.0] — 2026-08-05 — Culture Runtime Integration: подключение культуры к реальной работе

Шаг 1 плана восстановления доверия. Не добавляем новые правила — подключаем уже существующие
к реальной работе сессии.

- **`ai-ops do` — автономный прогон.** Новый intent = `run --execute` с предустановленными флагами:
  `author=True`, `review=True`, `open_pr=True`, `review_fix_attempts=2` (авторазрешение блокировщиков).
  Команда, которую `session_guardrails` рекомендовала в Task Completion Ritual, теперь реально
  исполнима. `ai-ops do "задача"` — одна команда от намерения до draft PR.
- **Session guard ДО старта.** Перед запуском задачи `_session_guard_before_start()`:
  (1) `session_telemetry.snapshot()` — снимок текущего состояния сессии;
  (2) `session_boundary.classify()` — отношение новой задачи к текущей (не жёсткое
  `new_independent_task`, а по факту: same_task/continuation/adjacent/new_independent/new_product);
  (3) `session_guardrails.recommend()` — если контекст >250k или новая независимая задача в дорогой
  сессии, предупредить с точной командой (`/compact` или `/clear`); advise, не block.
  (4) `delegation_advisor.advise()` — если задача требует большой разведки (>8 файлов, >500 строк
  логов), рекомендовать сабагент.
- **Session Telemetry Provider (opt-in).** `tools/session_telemetry_provider.py` — контракт для
  чтения реальной Claude session metadata из `~/.claude/projects/*/sessions/*.jsonl`. Если данные
  есть — `started_at`, `session_id`, `message_count`, `input_tokens`, `output_tokens` становятся
  `measured`. Если нет (или структура изменилась) — честно `unavailable` (не 0, не partial).
  Интегрирован в `session_telemetry.snapshot()`.
- **Relation по факту.** `session_guardrails.recommend()` больше не получает жёсткое
  `next_relation="new_independent_task"` — вместо этого `session_boundary.classify()` определяет
  отношение по тексту задачи, WorkItem ID, пересечению scope. Рекомендация основана на реальных
  данных, а не на предположении.

## [3.21.1] — 2026-08-05 — Runtime Trust Recovery: claude-cli production-path regression

Шаг 0 плана восстановления доверия к флагманскому runtime. Находка живого прогона: любой вызов
`claude-cli` падал с `NameError('time')` ещё до обращения к модели, при этом selftest оставался
зелёным, потому что тестовый runner возвращал результат **до** production-path (time.monotonic,
json parse, _record_call, retries).

- **Что было сломано.** `_claude_cli_call` импортировал `time as _t`, но ниже использовал
  `time.monotonic()` и `time.sleep()` — имя `time` не было определено. Injected runner в selftest
  возвращал текст напрямую (`return runner(cmd)`), минуя весь production-path. Selftest зелёный,
  runtime мёртв.
- **Фикс production-path.** Runner теперь заменяет `subprocess.run`, а не весь вызов. Production-path
  (`time.monotonic`, `json.loads`, `_record_call`, retry-loop) проходит полностью в selftest. Если
  `import time` сломан — тест падает на `time.monotonic()`, а не проходит молча.
- **Две новые регрессии.** (1) `_record_call` действительно вызван: `input_tokens`, `output_tokens`,
  `latency`, `cost` записываются в `_CALL_STATS`. (2) Retry-loop: runner возвращает `returncode=1`
  первые 2 попытки → `returncode=0` на 3-й; `time.sleep()` вызывается без `NameError`.
- **Источники правды синхронизированы.** README: 179 → 193 проверки (фактическое число CI-шагов).
  ROADMAP: 28 → 31 gate (фактическое число из `quality/gates.yaml`). `release-claims.yaml`: комментарий
  про `generated-commands` обновлён на `first-class executing adapter` (v3.9.0).

## [3.21.0] — 2026-08-04 — Engineering Operating Model (срез 3): экономическая граница ДО траты

Финальный срез — закрывает всю фичу Engineering Operating Model (3.19 → 3.21).
- **Что было сломано.** Экономика кита была устроена так, что деньги узнавались ПОСЛЕ того, как их
  потратили: контекстный бюджет в `preflight` проверял, влезает ли задача в окно, но денег не касался;
  `Budget.charge_call` рвался ВНУТРИ прогона на N-м вызове, когда N−1 уже оплачены; `cost_account`
  сверял spent vs limit ПОСЛЕ прогона — это аудит, а не граница. Дорогая задача узнавалась по факту.
- **WP7 EconomicPreflight** (`tools/economic_preflight.py`, НОВОЕ, 29 selftest): оценка стоимости
  следующей задачи по фактической истории ЭТОГО репозитория (`usage_ledger`) против лимитов
  `RunPlan.execution_budget` — **до первого вызова модели**. Вердикты: `proceed`, `proceed_unknown`,
  `confirm_required`, `block`. **Решение по ХУДШЕМУ сравнимому прогону, а не по медиане:** если самый
  дорогой сравнимый прогон не влезает в лимит, трата началась бы и была бы прервана посередине —
  деньги потрачены, результата нет.
- **Три правила честности, важнее самой оценки.** (1) Нет истории → `unavailable`, **никогда 0**:
  ноль означал бы «задача бесплатна», и на такой лжи граница пропустила бы что угодно; при этом
  отсутствие истории НЕ блокирует — иначе первый прогон в репозитории был бы невозможен.
  (2) Задача, где хоть один вызов записан с `cost_status: unavailable`, даёт **нижнюю границу**, а не
  стоимость: считать неизвестное нулём и складывать — систематически недооценивать. Такая оценка
  помечается `estimated_lower_bound`, и вердикт прямо говорит, что граница может **не** сработать.
  (3) **Никаких выдуманных коэффициентов** вида «сильный writer в 3 раза дороже»: в `UsageRecord` нет
  ни класса задачи, ни writer-tier'а — разложить историю по ним нечем, и модуль этого не изображает.
- **Встроено в ядро**: `tools/preflight.py` получил шаг 7 (после approvals, до tool loop). На
  `reevaluate_only` не применяется — новой существенной траты там нет. Покрыто positive / fail-closed /
  **side-effect proof** (сначала доказывается, что ledger реально записан и читается, и только потом
  проверяется реакция гейта) + проверкой, что блокирует ИМЕННО экономика, а не соседний spec-first.
- **Поверхность**: ключ `economics` в `schemas/child-config.schema.json`; `validate_engops_policy`
  расширен до 54 selftest — в том числе ловит `require_estimate: true` при `enforce: advise`
  (политика заявлена как советующая, а фактически заблокирует любой первый прогон); команда
  `ai-ops engops cost`; строка в `doctor`.
- **ВСЯ ФИЧА ENGINEERING OPERATING MODEL ЗАКРЫТА** (3.19 коммит и ветка → 3.20 окружения и поставка
  → 3.21 экономика): кит теперь проверяет не только содержание изменения, но и операционную гигиену
  вокруг него — чем оно станет в истории, на какой ветке живёт, куда поедет и во сколько обойдётся.
- CI +1, AGENTS +1 (199). VERSION 3.20.1 -> 3.21.0.

## [3.20.1] — 2026-08-04 — патч честности deploy_readiness: подсказка ≠ вывод

Нашлось СРАЗУ на живом продукте владельца, по его реплике «да там не версель в деплое».
- **Что врало.** При `configured` инструмент писал: «Поставку ведёт внешняя платформа (vercel.json):
  путь существует, но он ВНЕ репозитория». Два необоснованных утверждения в одной фразе: (1) механизм
  поставки выводился из НАЛИЧИЯ конфига — файл может быть наследием или использоваться не для деплоя;
  (2) «путь существует» — инструмент этого не знает, он знает лишь, что пути НЕТ В РЕПОЗИТОРИИ.
  На реальном репозитории оба вывода оказались неправдой.
- **Что теперь.** Говорится только проверяемое: «исполняемого пути поставки В РЕПОЗИТОРИИ нет», далее
  честная развилка — либо поставки нет вовсе, либо она производится вне репозитория, **и различить это
  по коду нельзя**. Найденные конфиги платформ перечисляются как **подсказка, не доказательство**
  («может быть наследием»).
- Поле `platform_managed` → `deploy_path_unknown` + `platform_hints`; находка `platform_managed_deploy`
  → `deploy_path_unknown`. Переименование безопасно: 3.20.0 в дочки ещё не устанавливался.
- Урок зафиксирован в `rules/core/EngineeringOperatingModel.md` («Чего инструмент НЕ знает и не
  заявляет»): это ровно то враньё о готовности, против которого написан весь срез 2.
- Регрессия закрыта 5 новыми assertions (`deploy_readiness` 40 → 42 selftest). **Ступень лестницы
  не изменилась** — врала причина, а не вердикт: из репозитория поставку по-прежнему нельзя ни
  воспроизвести, ни откатить.


---

## Архив

История до v3.20.0 вынесена из этого файла — он вырос до 6623 строк за месяц и перестал
читаться. Разбиение не меняет содержание, только размещение:

- [v3.0 — v3.19](docs/changelog/v3.0-v3.19.md)
- [v2.x](docs/changelog/v2.md)
- [v0.x — v1.x](docs/changelog/v0-v1.md)

Правила ведения и каденция релизов — [docs/agent-guides/release-cadence.md](docs/agent-guides/release-cadence.md).
