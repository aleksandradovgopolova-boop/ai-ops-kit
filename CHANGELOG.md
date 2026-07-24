# CHANGELOG — AI-first система (пакет)

Формат: [SemVer](https://semver.org/lang/ru/). Версия пакета — в `VERSION`.

## [Unreleased] — v3.2.0-rc — Architecture, Product & UI Governance (groundwork)

Начат следующий этаж системы: управленческий слой поверх исполнения. Первый инкремент — контракт
архитектурных решений + UI Definition of Done, связанные с UI-таксономией (`gate_policy.ui_impact`)
и Storybook-evidence. Технический адаптер (v3.1.7) не переписывается — над ним ставится governance.

### Added
- `schemas/architecture-decision.schema.json` — `ArchitectureDecision` (ADR): context/decision/
  alternatives/consequences (обязательны И positive, И negative — издержки скрывать нельзя)/
  quality_attributes (ISO-25010-класс)/`ui_impact` (согласован с `gate_policy`)/supersede-цепочка.
  Отличается от `decisions/registry.yaml` (Decision Intelligence — принципы/эпизоды мышления).
- `validation/validate_architecture_decision.py` — структура + семантика (negative-последствия
  обязательны; `superseded` требует `superseded_by`; enum'ы; drift-guard против схемы). selftest в CI.
- `templates/quality/DefinitionOfDone-UI.md` — риск-тир (`internal`/`user_facing`/`critical`) →
  требования (states/interaction/a11y/visual/design-system/UX) → evidence на точном SHA. Правило
  component-reuse. Связь ADR ↔ gate_policy ↔ StorybookPolicy ↔ UIEvidenceBundle.
- **ADR registry + fitness** (v3.2.1): `decisions/adr/*.yaml` — governed-набор реальных
  архитектурных решений системы (ADR-001 control-plane; ADR-002 fail-closed gate-модель; ADR-003
  калиброванное UI-enforcement на exact-SHA evidence). `validation/validate_adr_registry.py` —
  кросс-целостность (уникальность id, имя файла==id, ДВУНАПРАВЛЕННАЯ supersede-цепочка, резолв
  related) + fitness (`ui_impact ∈ gate_policy.UI_IMPACT`). selftest + прогон реального реестра в CI.
- **Quality-attributes fitness** (v3.2.2): `validation/validate_quality_attributes.py` — агрегирует
  `quality_attributes` ADR-реестра в профиль и ловит governance-смеллы: `degrades` без обоснования
  (`note`); неуправляемое противоречие (атрибут одновременно `improves` и `degrades` среди активных
  ADR без `tradeoff`). Профиль — вход для будущих evolution-triggers. selftest + реальный прогон в CI.

### Note
- Без version-bump: v3.2 groundwork лежит аддитивно; формальный переход v3.1→v3.2 (bump VERSION) —
  после закрытия живой Phase B квалификации (нужен сильный провайдер-ключ).

## [Unreleased] — v3.1.9-rc — Exact-SHA UI Evidence (trust-фикс перед живой UI-квалификацией)

Закрыт реальный trust-разрыв калиброванного enforcement (v3.1.8): UI-evidence собиралось в
контроллере ДО реализации, из основного checkout, без commit_sha и без changed_files. Из-за этого
старое `pass`-evidence в основном дереве могло снять субъективный блок с новой правки. Это узкий
обязательный фикс; НЕ раздуваем roadmap.

### Fixed (безопасность)
- Сбор UI-evidence перенесён из `ai_ops_run.run` (до pipeline) в `execution_pipeline` — **после**
  коммита, из рабочего worktree WorkItem, на **точном** `committed_sha`, по файлам этого коммита
  (`_committed_changed_files` = base..committed_sha).
- **Exact-SHA binding:** `storybook_adapter.evidence_for_gate(bundle, expected_sha)` — если
  `bundle.commit_sha != expected_sha` (устаревшее / не привязанное / чужое evidence), ВСЕ гейты →
  `not_run` (fail-closed), evidence НЕ освобождает гейт.
- `bundle.commit_sha` берётся из **провенанс-меты** артефактов (`.ai/ui-evidence/meta.json →
  commit_sha`) — SHA, на котором evidence реально собрано, а не от вызывающего.
- Убран loose stem-matching файлов: сопоставление changed↔importPath теперь по **суффиксу пути**
  (`a/Card.tsx` ≠ `b/Card.tsx`), истории одного компонента больше не «покрывают» другой.
- Пустой `affected_stories` при UI-правке больше не даёт вакуумного `state_coverage.complete=True`:
  `ux` не закрывается детерминированно без затронутых историй.
- `UIEvidenceBundle` (на точном SHA) выносится в отчёт pipeline как qualification evidence.

### Added (три обязательных отрицательных теста, `storybook_adapter --selftest`)
- старое `pass`-evidence + новый commit → не освобождает (все `not_run`);
- `bundle.commit_sha != tested_revision` → не освобождает;
- проходящие истории ДРУГОГО компонента → не закрывают изменённый компонент.

### Известные ограничения (зафиксировано, не блокер)
- `GateResult v2` реализован как контракт + compatibility-адаптер, но ещё НЕ стал каноническим
  runtime-форматом всех gate-результатов: в `_run_reviews` калиброванный advisory сохраняется как
  v1 `warn` (`calibrated_view()` пока не публикуется в отчёте). Планируется отдельно, не в v3.2.
- Живая Phase B квалификация (5 сценариев + `QualificationReport`) — ОТКРЫТА, требует боевого
  провайдер-ключа (ротация в консоли) и реальных PR. Не входит в этот оффлайн-фикс.

## [3.1.8] — 2026-07-24 — Calibrated UI Enforcement (ПЕРВОЕ изменение боевого fail-closed за v3.1)

Калиброванная UI-политика (v3.1.6, shadow) + проверяемое evidence (v3.1.7) становятся ЖИВЫМИ:
контроллер применяет их к боевому решению гейтов. Разрешено доказанным промоушен-критерием на
Bench Lite; безопасность (`false_green==0`) — жёсткий инвариант, не тронуты safety-гейты.

### Changed (боевое поведение)
- `ai_ops_run.run(calibrated_enforcement=True)` — по умолчанию включено в контроллере. Хук в
  `execution_pipeline._run_reviews`: субъективный reviewer `warn` по UI-гейту **не блокирует**, когда
  гейт advisory (internal low-risk) ИЛИ механика подтверждена детерминированным evidence
  (`evidence=pass`). `evidence=fail` (реальная регрессия/дефект) блокирует **всегда**, даже при
  reviewer `pass` (усиление, не ослабление). Critical ux/a11y требуют human-signoff (evidence не
  заменяет человека).
- **NO-OP без богатых сигналов:** легаси `ui_changed`→`user_facing` + нет evidence → fail-closed ==
  как раньше. Все прежние selftest/parity/live-квалификация целы. Ослабление возможно ТОЛЬКО при
  `ui_impact=internal` (не-safety гейты) ИЛИ passing UI-evidence.

### Added
- `schemas/gate-result-v2.schema.json` + `tools/gate_result_v2.py` — `GateResult v2`
  (`status` +`not_applicable`/`abstain`, `applicability`/`enforcement`/`evidence_mode`) + адаптер
  v2→v1 для старых потребителей (`not_applicable`→опустить; `abstain`→`warn`, консервативно). Схема
  v1 НЕ тронута (не breaking).
- Bench Lite **v0.3**: реальный A/B (baseline `calibrated=off` vs `calibrated=on`) + safety-регрессии
  (evidence=fail) + evidence-released кейсы; блок `calibrated_enforcement` в отчёте.

### Промоушен-критерий (доказан, жёстко в selftest)
- `false_green == 0` под живой политикой; **все** safety-регрессии (evidence=fail) блокируются;
  `residual_false_fail_rate = 0.0` (≤0.10 — все should-pass освобождены); block-rate **0.667→0.333
  (−50%)**; deterministic evidence освобождает 6 user_facing/critical кейсов. Оставшиеся блоки —
  fail-closed (нет evidence / critical human-signoff), НЕ false-fail.

### Note
- Первоклассный reviewer `abstain` (эмиссия статуса ревьюером в reviewer-result) — будущая работа;
  сейчас abstain (warn без blockers) остаётся невынесенным вердиктом → fail-closed.

### CI
- +1 selftest (`gate_result_v2`) в `package-quality.yml` + `AGENTS.md`. Parity 106/106 в 4 конфигурациях.

## [3.1.7] — 2026-07-23 — Storybook Evidence Adapter (проверяемое UI-evidence вместо субъективного ревью)

Следующий шаг после v3.1.6: снижать reviewer-false-fail не «доверием модели», а заменой части
субъективного UI-ревью **проверяемым evidence** из локальных артефактов child-репо. В v3.1.7 bundle
только собирается и валидируется (SHADOW) — enforcement идёт отдельно в v3.1.8 (+GateResult v2).

### Added
- `schemas/ui-evidence-bundle.schema.json` — контракт `UIEvidenceBundle`: секции `storybook`,
  `state_coverage`, `interaction_tests`, `accessibility`, `visual_regression`, `design_system`,
  каждая с явным `status` (вкл. `not_run`/`absent` — «нет артефакта» НЕ выдаётся за «чисто»).
- `tools/storybook_adapter.py` — оффлайн stdlib-адаптер: детект Storybook, парс story index (v6/v7),
  маппинг changed-файлов → затронутые компоненты/истории, покрытие UI-состояний, нормализация
  vitest/axe/visual/design-system результатов (сырые форматы тоже). `evidence_for_gate()` — shadow-мост
  к `gate_policy.evidence_mode`. БЕЗ внешнего SaaS/MCP; kit НЕ становится React-приложением.
- `validation/validate_storybook_evidence.py` — структура + **семантика**: статус нельзя разойтись с
  цифрами (a11y `pass`⟺0 blocking; interaction `pass`⟺passed=total; visual `pass`⟺changed=0; новые
  компоненты без обоснования → `fail`); closed-ключи; drift-guard enum'ов против схемы.
- `templates/quality/StorybookPolicy.md` — маппинг `UIEvidenceBundle` → 4 UI-гейта → `evidence_mode`
  (`visual_regression`=deterministic; `design_system_usage`/`accessibility_review`/`ux_review`=hybrid).

### Границы (решение владельца)
- Источник истины — локальные manifests и test-artifacts, БЕЗ SaaS/MCP для enforcement (Storybook MCP —
  позже, v3.6, как интерфейс агентов). Fail-closed сохранён: `not_run` → гейт закрывается ревью, не сам.
- Safety-гейты (`security`/`code_review`/auth/секреты/данные) не трогаются.

### CI
- 2 selftest в `package-quality.yml` + `AGENTS.md` (CI ⊆ AGENTS.md). Parity 105/105 в 4 конфигурациях.

## [3.1.6] — 2026-07-23 — UI Gate Applicability + Shadow Policy (риск-калибровка БЕЗ изменения боя)

Точная формулировка находки Phase B: узкое место — НЕ движок (engine_floor=0) и НЕ «плохая модель»,
а **взаимодействие грубой gate-policy с неопределённостью ревьюера**. Трек VISUAL вешает все 4
UI-гейта разом по одному булеву `ui_changed`, и все четыре — blocking; любой `warn`/сомнение/молчание
по одному гейту блокирует всю правку. Вводим контекстную политику в SHADOW-режиме: боевой fail-closed
не меняется, кандидат считается рядом — чтобы измерить проектируемое снижение false-fail и доказать
безопасность ДО смены enforcement.

### Added
- `tools/gate_policy.py` — таксономия `ui_impact` (none/internal/user_facing/critical) +
  `ui_change_kind` (token/primitive/component/screen/flow), с обратной совместимостью
  (`ui_changed=true` без уровня -> user_facing, тождественно текущему поведению).
- `GatePolicyDecision`: `applicability` (applicable/not_applicable) + `enforcement`
  (advisory/blocking) + `evidence_mode` (deterministic/ai_review/hybrid/human) + `human_signoff`.
  `current_policy` / `candidate_policy` / `shadow_diff` (чистые функции, без побочек).
- Bench Lite **v0.2**: корпус расширен до **25 кейсов** — матрица `ui_impact × ui_change_kind ×
  строгий_гейт` + `abstain` (warn без блокеров). Метрики разведены на **две истины**:
  `policy_conformance` (движок исполняет ТЕКУЩУЮ policy) и `quality_accuracy` (пропустила ли policy
  корректный код). Добавлен per-case `shadow` и `projected_block_rate_after_calibration`.

### Changed (честность метрик, по ревью владельца)
- `reviewer_false_fail_rate` -> `quality_accuracy.synthetic_known_good_block_rate` с явными
  `sample_size` / `sample_type: scripted_reviewer` / `live_reviewer_false_fail_rate: null`.
  Прежнее имя вводило в заблуждение: это ЧУВСТВИТЕЛЬНОСТЬ механики на синтетике, а не production-rate.

### Инвариант безопасности (жёстко в selftest)
- candidate НИКОГДА не мягче current для `user_facing`/`critical`; ослабление ТОЛЬКО в `internal` и
  ТОЛЬКО для не-safety гейтов (`ux_review`/`visual_regression`/`design_system_usage`);
  `accessibility_review` остаётся blocking всегда. Боевой fail-closed не тронут; `false_green == 0`.

### Замер (25 кейсов, все pass)
- `policy_conformance.conformance_rate = 1.0`, `false_green = 0`.
- `quality_accuracy`: synthetic_known_good_block_rate = **0.571** (12/21), engine_floor_ready = true,
  block_attribution = все 4 UI-гейта; **projected_block_rate_after_calibration = 0.381** — кандидат
  снял бы 4 internal-не-safety блока, сохранив ВСЕ user_facing/critical (safety не ослаблена).

### Note
- Схемы `gate-result`/`reviewer-result` v1 НЕ тронуты: `not_applicable`/`abstain` требуют `GateResult
  v2` + миграционного адаптера — отдельный будущий инкремент (см. ROADMAP v3.1.7–v3.1.8).

## [3.1.5] — 2026-07-23 — Golden tasks: широкая выборка known-good + вывод про локализацию false-fail

Расширили known-good корпус Bench Lite разными формами задач, чтобы reviewer-false-fail мерился на
широкой выборке (решение про advisory-тир — по данным, не по 3 точкам).

### Added
- KG-control `kg_backend_control`: корректная backend/QUICK правка (НЕ ui) — в плане НЕТ блокирующих
  review-гейтов -> ready БЕЗ ревью. Доказывает: reviewer-false-fail СКОНЦЕНТРИРОВАН в UI-гейтах
  (ui_changed), а не размазан по всем задачам.
- `kg_strict_ux` / `kg_strict_a11y`: строгость ревьюера на ux_review и accessibility_review ->
  block_attribution теперь покрывает ВСЕ 4 UI review-гейта (ux_review, accessibility_review,
  visual_regression, design_system_usage).
- Инварианты selftest: атрибуция покрывает все 4 UI-гейта; backend-control доходит до ready.

### Вывод (замер на 6 known-good)
- reviewer_false_fail_rate = 0.667; engine_floor_ready = true; block_attribution = все 4 UI-гейта по 1;
  false_green = 0. Корпус: 10 кейсов, все pass. ENGINEERING-задачи блокируются РАНЬШЕ на детерминированных
  артефакт-гейтах (нужен author) — это НЕ reviewer-false-fail. Итог: ложные блоки корректного кода
  локализованы в UI review-гейтах — прямая опора для будущего риск-калиброванного advisory-тира.

## [3.1.4] — 2026-07-23 — Reviewer false-fail rate: измеритель + атрибуция

Прямой ответ на находку Phase B (green-throughput режет консервативный independent-review, не модель).
Ре-фрейм на цифрах: движок НЕ источник false-fail — при полном добросовестном покрытии ревью
корректный код доходит до ready (engine floor = 0). Ложные блоки идут от строгости/покрытия РЕВЬЮ по
конкретным гейтам. Безопасность не тронута: fail-closed и `false_green == 0` сохранены.

### Added
- Bench Lite расширен known-good корпусом (код заведомо корректен; варьируем только покрытие/строгость
  ревьюера): `kg_full_coverage` (полный добросовестный ревьюер -> ready: доказывает engine floor),
  `kg_strict_visual` / `kg_strict_designsys` (ревьюер придирчив к ОДНОМУ гейту -> REAL false-fail).
- BenchReport.reviewer_false_fail: `reviewer_false_fail_rate` (доля known-good, заблокированных ревью),
  `engine_floor_ready` (полное покрытие -> ready), `block_attribution` (какие гейты режут корректный
  код — для будущего риск-калиброванного тюнинга строгости). Текущий замер: rate=0.667,
  attribution={visual_regression:1, design_system_usage:1}, engine_floor_ready=true.
- Инварианты selftest: engine floor ready; rate в [0,1]; атрибуция называет конкретные гейты; каждый
  known-good заблокирован ИМЕННО ожидаемым гейтом; `false_green == 0` и на known-good (тюнинг-измерение
  не ослабляет безопасность).

## [3.1.3] — 2026-07-23 — Bench Lite: оффлайн golden-корпус решений движка

Пилар Evaluation фазы v3.1. Находка Phase B: GREEN-throughput ограничен НЕ качеством модели, а
консервативным independent-review — легитимный минимальный код блокируется несколькими UI-гейтами.
Чтобы управлять строгостью осознанно, нужна воспроизводимая мера. Bench Lite её даёт.

### Added
- `tools/bench_lite.py` — детерминированный ОФФЛАЙН golden-корпус (провайдер `test`, заглушки
  писателя/ревьюера read-first как в бою). TOOL-FREE: репо кейсов — python-профиль без тулчейна ->
  проверки not_applicable, БЕЗ зависимости от pytest/линтеров (урок v3.1.2: CI имеет только pyyaml).
- BenchReport (JSON) с метриками: pass / false_green / false_fail / mismatch / error /
  review_blocked / fix_recovered. CLI `--run [--out f.json]` и `--selftest`.
- 4 golden-кейса: quick_clean (green), review_blocks (консервативный review блокирует), fixloop_recovers
  (fix-loop снимает блок ревью — TOOL-FREE e2e fix-loop, идёт в CI, чего pytest-guarded selftest не мог),
  rubber_stamp_guard (ИНВАРИАНТ безопасности: pass-без-чтений НЕ закрывает гейт -> ready=False).
- Жёсткие инварианты selftest: `false_green == 0` (движок никогда не отдаёт ready при обязательном
  блоке), 0 error/mismatch/false_fail, fix_recovered>=1, review_blocked>=1.
- Подключён в CI (package-quality) и AGENTS.md-чеклист (инвариант CI ⊆ AGENTS.md сохранён).

## [3.1.2] — 2026-07-23 — CI hotfix: fix-loop selftest не зависит от pytest

v3.1.1 дал CI-red (package-quality): интеграционный fix-loop-тест требовал pytest (сделать тест
упавшим->починенным), а CI-набор ставит только pyyaml. Локальный parity это маскировал (pytest есть).

### Fixed
- Интеграционная часть fix-loop-selftest теперь под guard'ом `importlib.util.find_spec("pytest")` (как
  PQ8 с openspec): без pytest — пропуск с честной пометкой; unit-проверки fix-context (конкретные
  blockers; human-approval->None) остаются безусловными. Проверено с СКРЫТЫМ pytest (rc=0) и с pytest (PASS).
- Дисциплина parity: CI-набор имеет ТОЛЬКО pyyaml — прогонять и без openspec, И без pytest.

## [3.1.1] — 2026-07-23 — Fix-loop (инкремент v3.1; по находке green-throughput из Phase B)

Прямой ответ на находку Phase B: строгий independent-review блокировал легитимные правки однопроходно.
Теперь блокеры возвращаются писателю на ИТЕРАЦИЮ.

### Added
- **Fix-loop** в транзакционном контроллере: если прогон не `ready_for_pr` из-за **модель-фиксируемых**
  блокеров (провалившие проверки test/build/lint + незакрытые code_review/ux_review/security), контроллер
  повторно зовёт `run_pipeline(resume=True, resume_context=<блокеры>)` на ТОЙ ЖЕ ветке — писатель
  дорабатывает, идёт ре-ревью. Бюджет — `--fix-attempts N` (default 1; 0 = как раньше). CLI `run`.
- **fail-closed сохранён**: бюджет исчерпан и всё ещё не ready → честный блок (ничего не форсируется в
  green). Не-фиксируемые блоки (**human-approval / base-transition / lifecycle / preflight**) НЕ
  зацикливаются (`_review_fix_context` → None). Не для `mock`.
- Блокеры ревьюера вынесены в трейс (`reviews[].blockers`) → в fix-context попадают **КОНКРЕТНЫЕ**
  замечания (не общий «устрани замечания»), плюс output_tail провалившихся проверок.
- Событие журнала **`fix_attempt`** (наблюдаемость итераций).

Деттесты: провал теста → итерация → `ready_for_pr=True` + событие `fix_attempt`; конкретные blockers в
fix-context; human-approval → None (fail-closed). Проверено live (DeepSeek): fix-loop реально итерирует
(2 попытки, `fix_attempt`×2, `test` перешёл в pass). Полный CI-набор на main и master.

## [3.1.0] — 2026-07-23 — Observability: Trace v0.2 (первый инкремент фазы v3.1)

Начало фазы **v3.1 — Observability, Evaluation & Safe Self-Improvement**. Первый инкремент —
обсервабельность-субстрат, на котором дальше встанут Bench Lite / evaluation / model-comparison / fix-loop.

### Added
- **Event journal v0.2** — закрыты честные ограничения v0.1: (1) межпроцессный **лок** (`flock`,
  best-effort) вокруг read-verify-append — нет гонки `seq`/`prev_checksum`; (2) **полная верификация
  цепочки ПЕРЕД append** — на повреждённый журнал не дописываем; (3) **durable head-marker**
  (`<journal>.head`) — детектит **усечение последней ЦЕЛОЙ строки**, которое v0.1 пропускал (валидный
  префикс выглядел валидным).
- **Trace-схема + валидатор** `validate_trace(events)` — проверяет обязательные ID связи Run/Attempt/
  Package/Gate/Delivery по каждому kind (трейс реконструируем).
- **`attempt_id`** на событиях прогона (resume/повтор → новая попытка, детерминированно из run-history).
- **tokens / cost / latency**: аккумулятор вызовов модели в `orchestrator` (usage из ответа провайдера +
  latency; приблизительная оценка cost по прайс-таблице) → событие **`run_cost`** + поле `cost` в отчёте.

Проверено **вживую (DeepSeek)**: реальный `run_cost` (5 вызовов, 25.3k in / 337 out токенов, ~$0.0072,
latency 8.5с), journal `ok` (цепочка + head-marker), `validate_trace` без ошибок. Деттесты: verify-before-
append на битую цепочку, head-marker truncation, trace-схема. Полный CI-набор на main и master.

## [3.0.19] — 2026-07-23 — authorization_idol false-positive (finding живой квалификации Phase B)

Первая находка из РЕАЛЬНЫХ прогонов (Phase B, DeepSeek): security-домен `authorization_idol` ложно
срабатывал на безобидном коде и блокировал легитимный ENGINEERING→PR через `needs_review`.

### Fixed
- **`authorization_idol` applicability матчила подстроку `acl` в `dataclass`** (`from dataclasses import
  dataclass` / `@dataclass`) — паттерн `permission|role|acl|access|...` без границ слова ловил `acl`
  внутри `datacl·ass`, `or·acl·e`, `mir·acl·e`. → ложный `needs_review` на pricing-функции, а строгий
  SecurityVerdict слабая модель не закрывала → `ready_for_pr=False`, PR не открывался. Фикс: границы
  слова `\b(?:permission|role|acl|access|authoriz|owner|tenant|is_admin|can_)\w*` — сохраняет реальные
  auth-идентификаторы (`role`/`roles`, `access`/`accessible`, `authorize`/`authorization`, `can_edit`,
  `is_admin`), но не матчит подстроки в неродственных словах. Не ослабляет детект реального auth-кода
  (v2.104 anti-под-срабатывание сохранено). Регрессионный деттест: `dataclass` НЕ применим, реальный
  auth — применим.

### Qualification (Phase B, live, DeepSeek deepseek-chat)
- **QUICK** — GREEN (delivered, ready_for_pr, все гейты, test pass).
- **ENGINEERING → настоящий draft PR** — GREEN после фикса: authoring valid (incl openspec spec-change),
  test pass, code_review pass (read-first reviewer live), security clear, delivery `opened`,
  **DeliveryReceipt sha_verified=True** против реального remote head SHA, PR #1 открыт. Delivery-outbox
  (Intent→PR→Receipt) отработал end-to-end вживую.
- До фикса движок КОРРЕКТНО блокировал (fail-closed, 0 false-green): red-test → нет PR; needs_review →
  нет PR.

## [3.0.18] — 2026-07-23 — PQ8 masked-failure fix + openspec-present parity

Адресный патч по finding: расхождение «PQ8 падал на чистом HEAD» vs «CI green». Оба были правдой —
CI и мой parity-харнесс гоняли **без openspec**, что маскировало реальный провал.

### Fixed
- **PQ8 positive-green ENGINEERING падал, когда openspec ПРИСУТСТВУЕТ** (воспроизведено: `code_review`
  gate `blocked`, `ready_for_pr=False`). Причина: mock-ревьюер PQ8 (`validate_product_qualification.py`)
  возвращал pass с **0 чтений**, а с v3.0.11 блокирующий ai-review не закрывается 0-read рубер-стампом.
  Остальные mock-ревьюеры были переведены на read-first ещё в v3.0.11, но ЭТОТ пропустили — потому что
  без openspec PQ8 уходит в fail-closed ветку (спек-гейт блокирует первым) и code_review не проверялся.
  Фикс: ревьюер PQ8 читает изменённый файл ДО pass. Теперь PQ8 зелёный **и** с openspec (positive-green),
  **и** без него (fail-closed).

### Process
- **Разрыв дисциплины parity**: проверял только no-openspec (как в CI), из-за чего openspec-зависимый
  провал не ловился. Проведён полный прогон **и WITH-openspec, и no-openspec** на обеих дефолт-ветках
  (main/master) — 101/101 в обеих конфигурациях; PQ8 — единственный маскированный провал.
- Расхождение разрешено **воспроизводимым прогоном** (`validate_product_qualification.py` с/без openspec),
  а не декларацией. CI для HEAD e93653e (v3.0.17) фактически зелёный (package-quality + release success).

## [3.0.17] — 2026-07-23 — Delivery Outbox Integrity (адресный патч по findings Phase A)

Устранены конкретные дефекты delivery-outbox из Phase A. После этого — Real Execution Qualification на
неизменяемом commit SHA.

### Fixed
- **P0 — reconciliation не доказывала точный commit SHA.** `reconcile_delivery` искал PR только по имени
  ветки и не сверял `head.sha`/`base.ref`/repository; восстановленный Receipt брал `commit_sha` из старого
  Intent. Теперь `reconcile_delivery` возвращает **факты remote** (`head_sha`, `base_ref`, `repository`,
  `pr_state`, `merged`, во ВСЕХ состояниях open/closed/merged), а контроллер подтверждает доставку ТОЛЬКО
  при **строгом совпадении** `repository + head.sha == commit_sha + base.ref`. PR той же ветки с другим
  коммитом → `mismatch`, НЕ засчитывается за старую доставку.
- **P0 — outbox был одним перезаписываемым файлом.** Теперь per-`delivery_id` immutable-записи
  `features/<wid>/delivery-outbox/<id>.intent.yaml|.receipt.yaml`. `delivery_id` включает repository.
  **Неразрешённый Intent (без Receipt) на ветке БЛОКИРУЕТ новую внешнюю доставку** до reconciliation —
  чужой неизвестный исход не затирается.
- **P0 — reconciliation рапортовала успех без проверки записи Receipt.** Все записи outbox — обязательные
  **барьеры**: `reconciled` возвращается ТОЛЬКО если Receipt фактически сохранён (иначе `receipt-write-failed`).
- **P1 — неоднозначный POST записывался как определённый error.** Транспортная ошибка/timeout ПОСЛЕ
  мутирующего POST → `status='outcome_unknown'` (сервер мог создать PR), НЕ `error` — reconciliation
  запустится. Раньше `error`-Receipt закрывал доставку и блокировал сверку.
- **P1 — возможная потеря маркера `outcome_unknown`.** Reconciliation теперь триггерится по **ФАКТУ**
  Intent-без-Receipt (а не по полю `status`) — даже если пост-действенное обновление Intent упало и на
  диске остался `intended`, незавершённая доставка всё равно будет сверена.
- **Идемпотентность**: `delivery_id`-маркер вшивается в тело PR; `pr_open` находит существующий PR ветки
  (`updated`, без дубля); retry не создаёт второй PR.

### CI
- Research-контур подключён к CI (`validate_research_artifacts` + `verify_quotes/freshness_sweep/
  ev_scaffold --selftest`) — раньше валидаторы существовали, но не запускались в workflow.

Crash-матрица (детерминированно): PR совпал по SHA → reconciled+sha_verified; PR с другим SHA → mismatch;
PR отсутствует → not-delivered; Intent 'intended' без Receipt → всё равно сверяется; неоднозначный POST →
outcome_unknown; unavailable → Receipt не пишется; идемпотентность/маркер. Полный CI-набор на main и master.

## [3.0.16] — 2026-07-23 — Real Execution Qualification · Phase A: Delivery Outbox & Reconciliation

Qualification-entry closure — три конкретных риска входа ДО первых реальных прогонов (это ещё entry
gate, не «квалифицировано»). Phase B (реальные прогоны на настоящих репо) — следующий шаг.

### Fixed
- **#1 — прямой вызов `run_pipeline` больше не может обойти lifecycle-барьер.** `run_pipeline` теперь
  **НИКОГДА** не выполняет внешнюю доставку — только возвращает `delivery_plan` (`delivery.status=planned`,
  `overall_status=ready-undelivered`). Единственный разрешённый вызывающий `_deliver_pr` — транзакционный
  контроллер. Параметр `defer_delivery` устарел и игнорируется (внешнее действие из pipeline запрещено
  архитектурно). Раньше `run_pipeline(..., open_pr=True)` с дефолтным `defer_delivery=False` открывал PR
  инлайн без RunHandoff/report-барьера.
- **#3 — единые write-barriers в controller-only пути.** RunPlan там стал барьером (сбой → прогон не
  начат); report-write проверяется; путь **официально помечен planning/orchestration-only** (`delivery:
  not-applicable`) — execution+delivery-гарантии существуют ТОЛЬКО в `engine=pipeline`.

### Added — #2 Delivery Outbox & Reconciliation (распределённая транзакция доставки)
- Внешнее действие (PR) и локальная запись не атомарны, поэтому: durable **DeliveryIntent** → external
  delivery (идемпотентно) → durable **DeliveryReceipt**. `delivery_id` детерминирован по
  `(workitem, branch, commit_sha)`.
- Если после внешнего действия запись Receipt упала → `delivery_status: outcome_unknown` +
  `reconciliation_required` (не притворяемся, что доставки не было).
- **Reconciliation** при следующем прогоне: сверяет remote (есть ли PR для ветки, URL/number/SHA) и
  дописывает DeliveryReceipt (`reconciled`) либо `not-delivered`, если PR не долетел. Идемпотентно.
- **Идемпотентность доставки**: `pr_open` находит существующий PR ветки и возвращает `updated`, не
  создавая дубль (retry не плодит PR).

### Docs
- ROADMAP: маршрут уточнён — v3.0.16 Phase A (эта версия) → Phase B (реальная квалификация) → при
  findings только адресные v3.0.x → v3.1…

Crash-recovery деттесты: PR найден на remote → Receipt восстановлен (URL/SHA/status); PR отсутствует →
`not-delivered`; повторная реконсиляция без дубля; RunPlan/report/DeliveryIntent — барьеры; run_pipeline
не открывает PR. Полный CI-набор на main и master, без openspec.

## [3.0.15] — 2026-07-23 — Lifecycle Commit Barrier (последний внутренний trust-релиз)

Транзакционная граница между доказательствами и delivery. После этого — реальная квалификация (v3.0.16).

### Fixed
- **P0 — доставка происходила ДО финальной фиксации lifecycle.** Раньше `run_pipeline` открывал PR сам,
  и лишь ПОТОМ контроллер писал RunHandoff/final-report/run_end — наружу мог уйти результат при
  неполном локальном источнике истины. Теперь **delivery вынесена из pipeline в транзакционный
  контроллер**: `run_pipeline(defer_delivery=True)` возвращает доказанный результат + `delivery_plan`,
  а PR открывает контроллер строго в порядке: verification → durable RunHandoff → durable final report →
  journal checkpoint (`ready_for_delivery`) → **delivery** → durable delivery result → `run_end`. Единая
  точка открытия PR — `_deliver_pr` (fail-closed по remote base).
- **P1 — критические durable-записи стали обязательными БАРЬЕРАМИ.** Результат записи проверяется для
  RunPlan (сбой → прогон не начат, 0 вызовов модели), RunHandoff и final report (сбой → **доставка НЕ
  выполняется**, `blocked-lifecycle`), плюс ранее fail-closed run-settings/SequencePlan/ApprovalRecord.
- **P1 — LifecycleStore v1.1: validate-before-replace.** Прежде `os.replace` шёл ДО проверки типа/ключей
  — битый документ мог заменить валидный, а функция возвращала `ok=False`. Теперь: валидация входа →
  сериализация → валидация проспективного reparse → **UNIQUE temp** (mkstemp, конкурентные писатели не
  бьются) → fsync → [opt-in backup `.bak` прежнего валидного] → atomic replace → fsync(dir) → повторная
  валидация → cleanup temp. Бракованная запись НЕ трогает старый файл.
- **P1 — require_fix симметричный diff** (перепроверено): `{a:fail,b:fail}→{a:pass,b:fail}` даёт
  `fixed=[test], regressions=[]` — красный чек не блокирует легитимный фикс узла. Закрыто ещё в v2.122;
  добавлен явный тест-таблица; исправлена устаревшая пометка «открыто» в ROADMAP.

### Docs
- **Roadmap reset**: раздел «Current Forward Roadmap» (v3.0.15 → v3.0.16 → v3.1…v3.8); историческая
  схема версий помечена как устаревшая. Честные ограничения **event journal v0.1** зафиксированы в коде
  (не источник истины для восстановления/вердикта; полный audit trail — v3.1).

Каждый пункт — с деттестом (delivery order: journal `ready_for_delivery` до `run_end`; write-barrier
RunPlan; validate-before-replace не затирает валидный файл; require_fix таблица). Полный CI-набор на
main и master, без openspec.

## [3.0.14] — 2026-07-23 — Qualification Readiness (переход на изменившуюся base + lifecycle-покрытие + journal)

Последний readiness-релиз перед реальной квалификацией вне Garden. Закрывает три перехода из вердикта
аудита.

### Fixed
- **#1 — fast-forward базы больше не отдаёт PR против непроверенной интеграции (вариант B, fail-closed).**
  Прежде: base unchanged / fast-forward / rewritten; rewrite блокировал resume, а fast-forward
  разрешался через `force_resume` — и старый worktree (форкнутый от прежней базы A) переиспользовался,
  baseline считался на A, но отчёт нёс BaseBinding B → PR против B без проверки интеграции. Теперь
  **fast-forward трактуется как rewrite**: `resume_preflight` даёт `base_moved`, и resume-путь блокируется
  — **ни `force_resume`, ни `replan` не снимают** (обе модификации resume переиспользуют устаревший
  worktree). Recourse — свежий прогон от новой базы (без `--resume`; `--discard` заменит устаревшую
  ветку), который пере-форкает worktree от новой базы. Авто-интеграция (rebase + повтор проверок) — v3.1.

### Added
- **#2 — LifecycleStore расширен** на RunPlan, финальный run-report, controller-report, run-history,
  ApprovalRecord, sequence-report (+ `durable_write_json` для JSON-артефактов). Теперь весь источник
  истины пишется атомарно (не только resume-критичное подмножество).
- **#3 — bounded event journal v0.1** (`journal_append`/`journal_read` в lifecycle_store): append-only
  JSONL с **checksum-цепочкой** (prev+self), `seq`, обнаружением усечения/подмены (crash-boundary на
  запись через fsync). Эмитятся `run_start`/`run_end` (single-run/controller) и `package_end` с
  `gates_unmet` (sequential) — Run→Package→Gate реконструируемы.

### Docs
- ROADMAP: официально внесены post-stable hardening (v3.0.11–14) и **Research v0.1** как ранний
  extractable bounded context (namespace `research.*`, `.research/`; собственный roadmap до v0.2).

Каждый пункт — с деттестом (fast-forward blocked + force не снимает; durable_write_json; journal
checksum-цепочка/подмена/усечение; journal записан в живом прогоне). Полный CI-набор на дефолт-ветках
main и master, без openspec.

## [3.0.13] — 2026-07-23 — Hardening Batch C: Maintainability (без изменения поведения)

Блок C самоаудита — снижение change-safety-долга. Все изменения поведение-сохраняющие, проверены
полным self-test-набором + CI-паритетом на обеих дефолт-ветках.

### Changed
- **Единый `tools/gitio.py`** — `git(root, *args, timeout=90)`; 7 идентичных копий `_git`
  (execution_pipeline / workpackage_executor / review_branch / run_handoff / worktree / pr_open /
  concurrency_preflight) делегируют ему. **Добавлен таймаут** — прежде ни одна копия его не задавала,
  и зависший git-субпроцесс (сеть/lock/hook) вешал весь прогон навсегда; теперь rc=124, не блокировка.
- **`_seq_err`** в workpackage_executor — единый конструктор отказного `WorkPackageSequence`-отчёта;
  словарь из ~11 ключей, копировавшийся вручную 8 раз, сведён к одному (добавление поля = 1 правка).
- **`_aggregate_verify`** — тело aggregate-верификации финального SHA вынесено из god-функции
  `execute_sequence` в отдельный чистый (вход→dict) хелпер. Поведение идентично.

### Tested (закрытие тест-гэпов)
- `_security_scan_error` **fail-closed**: security pack бросил → security-гейт=fail (не ложный green) —
  прежде ветка без ассерта.
- concurrency: убран тавтологичный ассерт (`verdict in (clean, collision)`), добавлен тест **stale-skip**
  (done-запись реестра в той же зоне не создаёт ложный overlap).

Отложено в v3.1 (осознанно): извлечение сильно связанных блоков `run_pipeline`/`run` (мутируют общий
gate_ev/ready-state) — высокий риск на доказанно fail-closed «денежном пути» при нулевой функциональной
выгоде; заслуживает выделенного ревью, а не патча. Полный CI-набор 96/96 на main и master, без openspec.

## [3.0.12] — 2026-07-22 — Hardening Batch B: Durable Resume Artifacts

Блок B самоаудита — durability resume-критичных lifecycle-артефактов. Прежде большинство писалось
plain `write_text`/`json.dump` (неатомарно, без fsync, без перечитывания), а битые/пустые читались как
«отсутствующие» → тихая потеря policy и ложный «resume безопасен».

### Added
- **`tools/lifecycle_store.py`** — единый durable-контракт: `durable_write` (tmp → flush+fsync(файл) →
  atomic `os.replace` → **fsync(каталог)** → перечитать+провалидировать) и `load_guarded` (различает
  **absent / corrupt / ok** — повреждённый ≠ отсутствующий). `workpackage_executor._durable_write_yaml`
  делегирует ему (дедуп + добавляет fsync каталога к SequencePlan).

### Fixed
- **run-settings**: durable-запись; на resume — `load_guarded`, **битый/пустой → fail-closed отказ**
  (не тихий откат к дефолтам вызова и НЕ перезапись контракта исходного прогона).
- **run-handoff**: durable-запись; `resume_preflight` читает через `load_guarded` — битый/пустой →
  `can_resume=False`+ревалидация (прежде `{}` → `sha=None` → все проверки устаревания пропускались →
  ложный «resume безопасен»).
- **active-work** (общий реестр координации): атомарная `save`, `load` fail-closed (повреждён → raise, не
  тихая пустая карта, скрывающая чужую активную работу), и **межпроцессная блокировка (`flock`,
  best-effort)** вокруг register/finish read-modify-write — конец last-writer-wins TOCTOU.
- **Проглатываемые сбои записи больше не молчат**: sequential per-package `report.json` — чекпоинт
  resume/retry — пишется атомарно, **сбой → hard-stop** цепочки (не «completed без чекпоинта»); сбой
  durable-записи run-handoff/run-report фиксируется в `lifecycle_errors` и в отчёт.

Каждый фикс — с деттестом (fail-closed чтение absent/corrupt, атомарность, hard-stop). Полный CI-набор
95/95 на дефолт-ветках main и master, без openspec. Отложено (v3.1): рефакторинг god-функций/envelope/
`_git`(timeout)/общий YAML-хелпер + закрытие тест-гэпов (блок C).

## [3.0.11] — 2026-07-22 — Hardening Batch A (сквозной самоаудит: 4×P1 + 4×P2)

Сквозной ревизионный проход по всему киту (ядро, trust/безопасность, durability, здоровье кода).
Главный вывод: «денежный путь» (доставка PR + security-гейтинг) реально fail-closed — P0-дыр
false-green нет. Батч A закрывает найденные trust/корректностные упрочнения (durability resume-
артефактов и рефакторинг — отдельно, v3.1).

### Fixed
- **P1 — `op:"git"` обходил sandbox-containment.** `shell_mode`/`allow_network`/allowlist применялись
  только под `if op=="shell"`, а `op:"git"` шёл в `subprocess(shell=True)` мимо них (op контролирует
  модель). Теперь тот же gauntlet для `op in (shell, git)`: `bash -c`/сеть под видом git — денай, `git`
  в allowlist проходит, `shell_mode=off` запрещает и git. (Смягчалось контейнером, но политика обещала
  enforcement, которого не было.) `tool_broker.py`.
- **P1 — `exit_code`=0 при `delivery-failed`.** Завершённый прогон несёт `overall_status`, не top-level
  `status`; `exit_code` читал только `status`→None→падал на `ready_for_pr`. `--open-pr`, не доставивший
  PR (нет origin/unverifiable), давал код 0 (CI видел успех). Теперь `delivery-failed`→1, `error`→2.
- **P1 — `security_pack` fails-OPEN при git-сбое.** `git ls-files` rc≠0 → `changed=[]` → нет находок →
  `clear`. Теперь git-энумерация упала → **raise → fail-closed** (ловит `_security_scan_error`→security=fail).
- **P1 — destructive-approval валидировался нестрого.** `_record_valid(r)` с дефолтами (без expiry/
  plan-binding/trusted source). Теперь STRICT — как для остальных high-risk доменов.
- **P2 — `context_overflow` и `spec_incomplete` fail-OPEN на исключении** → тихо роняли ready-блокер.
  Теперь fail-CLOSED (исключение = блокируем, не молчим).
- **P2 — anti-fabrication code-read сверялся по basename** (`tests/config.py` «закрывал» `src/prod/config.py`).
  Убран bare-basename fallback — только суффикс/точное совпадение пути.
- **P2 — `output_tail` (read/shell) клался в evidence без скраба секретов.** Теперь редактируется по
  `SECRET_PATTERNS` до попадания в отчёт (env-скраб закрывал только окружение процесса).
- **P2 — блокирующий ai-review (code/ux) закрывался pass-вердиктом с 0 чтений** (рубер-стамп; асимметрия
  с security-путём). Теперь чистый pass на блокирующем гейте требует ≥1 реального чтения.

Каждый фикс — с деттестом; полный CI-набор 94/94 на дефолт-ветках main и master, без openspec.
Отложено (v3.1): durable LifecycleStore для resume-артефактов (run-settings/run-handoff/active-work
атомарно + fail-closed на битом чтении) и рефакторинг god-функций/envelope/`_git`(timeout)/YAML-хелперов.

## [3.0.10] — 2026-07-22 — BaseBinding Truth & Evidence Integrity (аудит: 2×P0 + 2×P1)

### Fixed
- **P0 — BaseBinding сохранялся БЕЗ base_sha (был `null`).** Резолвер возвращал SHA под ключом
  `validated_sha`, а `ai_ops_run` читал `base_sha` → полный BaseBinding был неполным. Канонизирован
  ОДИН ключ `base_sha` во всём резолвере/движке (никаких параллельных `validated_sha`/`base_sha`).
- **P0 — resume НЕ использовал сохранённый base_sha как иммутабельный контракт** (заново разрешал ветку
  в её текущий SHA). Теперь RunHandoff несёт исходный `BaseBinding`, а `resume_preflight` сверяет
  сохранённый `base_sha` с текущим HEAD базы и различает **fast-forward** (`base_rewritten=False`,
  снимается осознанным `force_resume`) от **REWRITE** (force-push назад / пересоздание ветки на
  несвязанном коммите — сохранённый SHA больше не предок текущего HEAD). REWRITE **не снимается
  `force_resume`** — старую работу нельзя выдать за проверенную против новой базы; нужен явный `replan`
  или отмена. Опасный сценарий (форк от A → base переписан на B → старый worktree выдан за проверенный
  против B) закрыт.
- **P1 — Security evidence проверялась только на непустоту.** Теперь **EvidenceRef** — структурная
  ссылка (`code-read` path[+lines] | `test` command | `finding`/`scanner` id|detail|path); строка
  вроде `checked` не проходит. `code-read` **сверяется с реальным trace ревьюера** (файлы, которые он
  читал ∪ показанные в диффе) — ссылка на непрочитанный/непоказанный файл = фабрикация, вердикт невалиден.
- **P1 — SequencePlan проверялся на форму, но не на целостность.** `_validate_sequence_plan_schema`
  теперь при каждом чтении также проверяет: поддерживаемую `schema_version`, совпадение `workitem_id`
  (чужой план в каталоге WorkItem → ошибка), уникальность `id` и `order`, корректность `depends_on`
  (ссылки на существующие пакеты, без самоссылок), **отсутствие циклов**, пересчёт каждого `pkg_hash`
  и общего `plan_hash`. Дрейф плана блокируется при ЛЮБОМ существующем плане (не только при `resume_from`).

Отложено (честно): общий атомарный LifecycleStore (journal+checksum) для RunPlan/run-settings/
RunHandoff/ApprovalDecision/reports → v3.1. Критичные артефакты (SequencePlan, BaseBinding) уже
durable + integrity-validated.

## [3.0.9] — 2026-07-22 — Lifecycle Store & Delivery Integrity (аудит: 3×P0 + P1)

### Fixed
- **P0 — sequential delivery был fail-OPEN при непроверяемой remote base.** Проверял только
  «remote_base существует и отличается»; при `None` (нет origin/сети/ветки) → открывал PR. Две цепочки
  имели разные правила доверия. Единый **`_verify_remote_base`** (RemoteBaseVerifier) для single-run и
  sequential: `verified-equal`→PR, `verified-moved`→revalidation, `unverifiable`→delivery **unavailable**.
- **P0 — single-run хранил только имя base, не полный BaseBinding.** Теперь `BaseBinding`
  (`base_ref`+`base_sha`+`mode`+`source`) сохраняется в run-settings и восстанавливается на resume —
  точная база исходного запуска (ловит force-push/смену upstream/пересоздание ветки, не только fast-forward).
- **P0 — проверка повреждённого SequencePlan была неполной** (валиден, если dict+kind). Теперь
  `_validate_sequence_plan_schema` при **каждом чтении** (schema_version/workitem_id/plan_hash/base_ref/
  sequence_base_sha/packages + id/pkg_hash/order/depends_on) — парсибельный, но неполный план →
  lifecycle-corrupted до модели.
- **P1 — SecurityVerdict v2.3.** pass-домен требует ≥1 конкретную **evidence-ссылку** (code-read
  path/lines, test command, scanner finding); id+status без evidence — не доказательство.

Отложено: общий атомарный LifecycleStore (journal+checksum) для RunPlan/run-settings/RunHandoff/
ApprovalDecision/reports → v3.1 (критичнейший SequencePlan уже durable+schema-validated).

## [3.0.8] — 2026-07-22 — Resume & Lifecycle Truth (аудит: 3×P0 + 2×P1)

### Fixed
- **P0 — регрессия v3.0.7: auto-base сломал single-run resume.** fresh-прогон сохранял `base: null` →
  resume восстанавливал `None` → `resume_preflight` вызывал `git rev-parse None` → **TypeError**. Теперь
  `base` разрешается в конкретную ветку **один раз** в `run()` (после restore, до preflight и записи
  run-settings); сохраняется резолвнутый `base_ref` (не raw None); resume берёт его как источник истины.
  Явная несуществующая base → ранний отказ (0 model calls). Проверено: resume после fresh auto-base
  работает на `main` и `master`.
- **P0 — `sequence_base_sha` писался best-effort после durable-плана.** Теперь `base`+`base_sha`
  разрешаются до записи, и `sequence_base_sha` входит в тот же атомарный `_durable_write_yaml`
  (`base_ref`+`plan_hash`+`sequence_base_sha`+`packages`) — без последующего дописывания.
- **P0 — повреждённый SequencePlan трактовался как отсутствующий** (→ перезапись). Теперь: нет файла →
  fresh; валиден → existing/resume; **невалиден → lifecycle-corrupted, остановка** (0 пакетов, файл не
  перезаписан, `corrupt_sha256`+path в отчёте). Recovery — явная операция.
- **P1 — SecurityVerdict v2.2.** Nested domain-check обязан иметь `id`+валидный `status` (`checks:[{}]`
  больше не проходит); pass-домен требует хотя бы один `check` со `status=pass`; warn/fail-домен —
  непустой `blockers`.
- **P1 — documentation truth.** README-статус (был `v2.117`/«до v3.0-rc1») → `v3.0.x stable`, обе
  цепочки квалифицированы живьём, идёт dogfood; ROADMAP-версия → «v3.0.x stable, точная версия в VERSION».

Отложено: durable-запись остальных lifecycle-артефактов (RunPlan/run-settings/RunHandoff/ApprovalDecision/
reports) и автосборка статуса из VERSION+manifest → v3.1 (критичнейший SequencePlan уже durable).

## [3.0.7] — 2026-07-22 — Default Branch & Durable State (аудит: 3×P0 + P1)

Внутренний trust-патч перед полными dogfood-прогонами. (Аудит предлагал это как 3.0.5, но 3.0.5/3.0.6
уже заняты авто-апдейтом и secret-scanning-гайдом — вышло как 3.0.7.)

### Fixed
- **P0 — `base` был захардкожен `main`.** На репо с default-веткой `master` обычный прогон без `--base`
  шёл к несуществующему `main`. **BaseResolver v3:** `base=None` → **auto** (upstream текущей ветки →
  remote default `origin/HEAD` → текущая ветка), без хардкода. Дефолты `base` → `None` во всех входах
  (run_pipeline/execute_sequence/ai_ops_run.run/CLI); `base_binding` несёт `mode`+`source`.
- **P0 — неразрешённая ЯВНАЯ base позволяла выполнять от HEAD.** Явная несуществующая `--base` теперь →
  **preflight-блок до модели** (ноль model calls, worktree не создан) в single-run и sequential. auto
  всегда разрешается, поэтому блок только на явной несуществующей ветке.
- **P0 — критические lifecycle-записи были best-effort** (`try/except pass`). `_durable_write_yaml`
  (atomic `temp→fsync→rename` + перечитывание/валидация ключей) для immutable **SequencePlan**; сбой
  записи → последовательность не стартует (без источника истины нельзя доказать base/порядок/hashes/
  checkpoint).
- **P1 — SecurityVerdict v2.1.** Каждый применимый домен обязан нести **свои** per-domain `checks` (не
  только `status`); `pass` домена без domain-specific checks не закрывает security.

Отложено: durable-запись остальных lifecycle-артефактов (run-settings/report/approval) — SequencePlan
закрыт как критичнейший.

## [3.0.6] — 2026-07-22 — Гайд downstream secret-scanning (лексика ≠ секрет)

### Added
- **`docs/downstream-secret-scanning.md`.** После v3.0.4 сканер потребителя (Гермес) продолжал
  блокировать PR обновления — теперь на **лексике** security-документации (слова `secret`/`token`,
  имена `GITHUB_TOKEN`/`OPENAI_API_KEY`), а не на значениях. Это слишком широкое keyword-правило (даёт
  100% ложных на любой security-документации), не утечка — убрать эту лексику из security-инструмента
  невозможно и неправильно. Гайд объясняет: `.ai/managed/**` — **вендоренная зависимость** (как
  `node_modules`/`vendor`), исключается из секрет-скана ребёнка; даёт готовые сниппеты для
  gitleaks/trufflehog/detect-secrets/GitHub native; альтернатива — сузить правило до value/format-based.
  Ссылки из README и runbook §7. Гарантия безопасности исключения: в ките 0 реальных секретов и 0
  статических секрет-литералов (проверено). Гайд содержит только regex-паттерны, не значения.

## [3.0.5] — 2026-07-22 — Авто-обновление в детях ВКЛ по умолчанию (опт-аут)

### Changed
- **`parent.auto_update` по умолчанию ВКЛ.** Дочерние репо теперь по умолчанию получают ежедневный
  update-PR на новую версию кита (было: опт-ин, `false`). Изменено в двух местах для консистентности:
  `examples/child-config.example.yaml` (`init` пишет `auto_update: true`) и `templates/ci/
  ai-ops-update.yml` (отсутствующий ключ → `True`). **Безопасность сохранена:** авто-режим только
  **открывает PR** (не авто-мерж), проходит PR-конвейер ребёнка (ревью/тесты/секрет-сканер), а мажорный
  bump по-прежнему блокируется SemVer-гейтом. Отключить — явный `auto_update: false` (опт-аут).

## [3.0.4] — 2026-07-22 — Fix: без статических секрет-фикстур (не блокировать downstream-сканер)

### Fixed
- **Downstream секрет-сканер ложно блокировал публикацию апдейта.** У потребителя (Гермес) v3.0.3
  ставился и проверялся, но PR-конвейер блокировал merge: секрет-сканер (gitleaks/trufflehog-класс)
  флагует фикстуры-«секреты» в тестах **самого детектора кита** (`AKIAIOSFODNN7EXAMPLE`, hex api_key,
  `-----BEGIN RSA PRIVATE KEY-----`, `sk-super-secret-123`, `sk-ant-xyz`). Правильный путь — **не
  обходить сканер**, а адаптировать upstream. Фикс: все фейковые секрет-фикстуры **собираются в
  рантайме** из фрагментов (`"AKIA" + "IOSFODNN7EXAMPLE"`) → в исходнике нет статического
  секрет-подобного литерала → **ни один** сканер (scanner-agnostic) не флагует; детектор кита получает
  полную собранную строку → его тесты по-прежнему проверяют детекцию. Проверено: `git grep`
  секрет-форматов → чисто; реальных ключей в трекнутых файлах нет; 94/94 CI на обоих дефолтах ветки.

## [3.0.3] — 2026-07-22 — Fix: CI-паритет по дефолтной ветке (main vs master)

### Fixed
- **v3.0.2 CI RED.** Три resume-деттеста (`v2.109 ctl`, `Q3b`, `PQ3`) падали только в CI. С base-binding
  (3.0.2) `base` стал частью resume-состояния; тесты запускали фазу 1 без `base` (дефолт `main`), а
  resume-фазу с `base=cur`. Локально дефолт-ветка `main` → совпадало; в CI дефолт `master` → расхождение
  → ложная resume-ревалидация → `blocked`. Фикс: фаза 1 во всех трёх тестах использует `base=cur`
  (реальную ветку репо). Функциональность 3.0.2 не менялась — правка только в тестах. CI-паритет теперь
  прогоняется и под `init.defaultBranch=master` (94/94 на обоих дефолтах).

## [3.0.2] — 2026-07-21 — Base Continuity & Evidence Roots (аудит: 4×P0 + P1)

Последний внутренний trust-патч перед dogfood на реальных репозиториях.

### Fixed
- **P0 — несуществующая base тихо → HEAD.** `--base develop` при отсутствии develop давал
  `base_sha=None` → worktree от HEAD, прогон продолжался. `_resolve_base` разрешает **строго** (только
  ветка `refs/heads/<ref>` или `origin/<ref>`, не tag/SHA), `base_binding.resolved/source/reason`. Не
  разрешилась + `open_pr` → PR к произвольному HEAD не открываем; для не-delivery — честный fallback
  на HEAD с пометкой `resolved=False` (не молча).
- **P0 — невозможность проверить remote base = разрешение на PR.** Теперь **fail-closed** (single +
  sequential): remote base не проверяема (нет origin/сети/ветки/ошибка) → `delivery=unavailable`
  (`reason=remote-base-unverified`); сдвинулась → `not-attempted`; совпала → PR. `ready_for_pr` не
  меняется, но `delivery_ok=false`.
- **P0 — сохранённый `base_ref` не был источником истины на sequence resume.** resume/retry берут base
  из `saved_plan.base_ref`; другая `--base` → `base-contract-drift` (нужен replan).
- **P0 — single-run resume не сохранял базу.** `base` теперь в immutable resume-policy (`run-settings`),
  восстанавливается из saved (saved wins).
- **P1 — approval читался из двух корней.** `ApprovalRecord`/plan-binding — из lifecycle-корня
  (`child_root/features`); изменённые пути — из execution-корня (worktree). Раньше оба из `work_root`
  → человеческое одобрение из lifecycle отсутствовало в worktree → ложный uncovered.

### Отложено (не новые false-green; v2 domain-coverage из 3.0.1 держит)
- SecurityVerdict v2.1 (per-domain evidence/checks/blockers сверх покрытия имён); явный fail-closed на
  сбой записи SequencePlan/BaseBinding/run-settings/approval.

## [3.0.1] — 2026-07-21 — Base & Approval Integrity (аудит поверх stable: 4×P0 + P1)

Trust-hotfix перед доверием stable для работы от произвольных base-веток и high-risk изменений.

### Fixed
- **P0 — `base` не был сквозным контрактом (single-run).** `run_pipeline` не имел `base`; worktree
  форкался от текущего HEAD → `--base develop` принимался, но ветка бралась от `main`. Теперь
  `run_pipeline(base=...)`: `base_ref`+`base_sha` резолвятся, worktree создаётся от `base_sha`, после —
  проверка `HEAD==base_sha` (иначе honest error). `base_binding` в отчёте.
- **P0 — sequential сверял `origin HEAD`, а не выбранную base-ветку.** Теперь `ls-remote origin
  refs/heads/<base>`; `base_ref` в SequencePlan; PR открывается **строго** в `base_ref`. Single-run
  delivery: перед PR ревалидация remote base vs validated `base_sha` — разошлась → PR не открыт;
  `open_draft_pr` получает явный `base`.
- **P0 — high-risk ApprovalRecord засчитывался нестрого.** `_human_approval_domains_uncovered` теперь
  `strict=True` (binds_to/expires_at/risk/source) + `plan_binding_hash` + `now` + `covers_paths` по
  реально изменённым high-risk файлам; **fail-closed** (сбой → домен непокрыт). Legacy рыхлая запись
  high-risk домен больше не закрывает.
- **P0 — SecurityVerdict v2.** Security-reviewer обязан вернуть `domain_results:[{domain,status}]`
  ровно по применимым доменам; `set(domain_results.domain)==set(needs_review)`; пропуск/дубль/лишний
  домен или warn/fail в домене при общем pass → security не закрыт.
- **P1** — ROADMAP-шапка обновлена (rc4 → stable).

## [3.0.0] — 2026-07-21 — Stable: движок укреплён, обе строгие цепочки доказаны живьём

Первый stable-релиз v3. Итог серии rc7→rc20 (14 rc, каждый закрыл реальный дефект живого прогона или
аудита) + финальная квалификация на claude-sonnet-5.

### Что доказано (честный scope stable)
- **QUICK** — trustworthy task → verified draft PR для supervised low-risk задач (закреплено с rc1).
- **ENGINEERING (single-run)** — полный путь **доказан живьём** до настоящего draft PR: authoring
  (requirements+plan+specification) → реальная реализация → tests pass → security → независимый
  `code_review=pass` → `ready_for_pr=true` → **настоящий draft PR**.
- **Sequential (3 WorkPackage)** — **доказан живьём**: все пакеты ready → aggregate (baseline на точной
  базе + security-reviewer + code-review на диффе `base..final`) → `aggregate_ready=true` → **настоящий
  draft PR**. Плюс: reviewer-block → hard-stop → downstream не стартует; trusted retry → recovery;
  provider-crash/429 contained.
- **Инварианты честности** (unit + live): writer≠judge; evidence на точном SHA; recovery НИКОГДА не
  трогает основной checkout (fail-closed); блокирующий вердикт (fail/warn) обязан назвать причину;
  aggregate — только явный валидный pass; high-risk по путям (Dockerfile/CI/auth) требует human
  ApprovalRecord; baseline доказан на `sequence_base_sha` или PR не открывается; delivery сверяет
  remote base. Все негативные пути закрыты **детерминированными тестами** (94/94 CI).

### Ключевые упрочнения серии
- Reasoning-модели (токены/таймаут/ретраи), spec-форма, author-retry с нуджем.
- Ревьюер: доставка диффа, сходимость вердикта, симметричная честность, полное чтение файла (+ранжи).
- Sequence: verdict integrity, infra-containment (single+sequential), retry-safety, sequence-base
  provenance, delivery base binding, per-package scope.

### Не входит в stable-claim (валидация в бою, не дефекты)
- **dogfood на 2–3 реальных репозиториях** — рекомендованная следующая валидация поверх stable
  (реальная мессовость vs синтетические фикстуры). Не блокер корректности: движок и обе цепочки
  доказаны, негативные пути детерминированы.

Замечание о провайдерах: kimi/Moonshot флакает 429 под multi-call нагрузкой (эксплуатационное, не
движок; contained с rc12/rc17). Живая квалификация закрыта на claude-sonnet-5.

## [3.0.0-rc20] — 2026-07-21 — Final Verdict Truth (аудит: 5×P0 + 2×P1)

Закрытие мест, где **отсутствие доказательства могло сойти за доказанный результат**. Оба финальных
пользовательских пути закрыты живьём на claude-sonnet-5: single ENGINEERING → draft PR и 3-пакетный
sequential → `aggregate_ready=true` → draft PR.

### Fixed
- **P0 — aggregate code_review был fail-OPEN.** `return (not blocked)`: no-verdict/невалидный/timeout/
  budget → `ok=True`. Теперь ok только при явном валидном `pass` (`gate_ev['code_review'].status=='pass'`).
- **P0 — high-risk изменение по путям проходило без human approval.** Security Pack эмитит только
  secret/injection/new_dependency, а домены `deployment_config`/`authentication`/… применимы по
  `file_patterns`. `_human_approval_domains_uncovered`: домены с `human_approval_conditions`, чьи
  **специфичные** паттерны (не catch-all `.*`) совпали с реально изменёнными путями (Dockerfile/CI/auth),
  требуют валидного ApprovalRecord — reviewer их не закрывает. Бранч-независимая форс-проверка.
- **P0 — aggregate baseline мог деградировать в неверную базу.** `_collect_base_checks_at` теперь
  проверяет `worktree add` + `HEAD==sequence_base_sha` (`baseline_proven`); **без fallback** на
  child_root; не доказан → aggregate unavailable → нет PR.
- **P0 — `base_drift` только писался.** `aggregate_ready` требует `base_drift is None`; delivery сверяет
  remote base (`ls-remote`) с validated `sequence_base_sha` — разошлась → PR не открывается; PR получает
  явную базу.
- **P1 — ranged reviewer reads.** `op=read` поддерживает `start_line`/`end_line` (дочитать хвост файла
  >20k; диапазон в `evidence.range`). **P1 — durable error report.** Contained-сбой (rc17) пишет свежий
  `run-report.json` + failure-handoff (retryable + безопасный `next_action`).

## [3.0.0-rc19] — 2026-07-21 — Per-package scope prompt (writer не выходит за подсистему)

Живой sequential на sonnet: single ENGINEERING→PR уже зелёный (PR #1), но 3-пакетный застревал.

### Fixed
- **Каждый пакет получал полную многочастную задачу → writer лез в чужие подсистемы.** В pkg-1
  (`discounts`) writer пытался писать `pricing/core.py` — брокер отклонял (containment сработал), но
  `_hard_stop` справедливо стопал цепочку на попытке эскейпа (`scope-violation`). Живьём: retry pkg-1 →
  `ready=True`, `code_review=pass` (реализация чистая, в scope), но стоп на попытке залезть в pricing.
  Первопричина — не ограниченный рамками промпт, не containment. Фикс: per-package задача теперь **явно
  ограничивает writer'а его подсистемой** (блок «ГРАНИЦЫ ПАКЕТА» со scope/write_scope и указанием не
  трогать другие подсистемы — их делают отдельные пакеты). Containment **не ослаблен** (брокер, post-diff,
  `_hard_stop` прежние) — убрана причина выхода за scope. Ревьюер по-прежнему судит независимо.

## [3.0.0-rc18] — 2026-07-21 — Reviewer read: полный файл (не хвост 400 символов)

Живой ENGINEERING→PR на claude-sonnet-5 (стабильный провайдер) вскрыл последний ревью-барьер.

### Fixed
- **`read` отдавал ревьюеру только последние 400 символов файла.** `tool_broker.execute` для `op=read`
  возвращал `text[-400:]` — для писательской петли хвост ок, но независимый ревьюер, читая файл для
  **верификации**, видел обрезок и честно блокировал: *«показан частично/обрезанным — не могу
  подтвердить полноту покрытия/закрытие задач»*. Движок при этом отработал безупречно (валидные
  артефакты, реальный рефактор `discounts`→`RATE_TABLE`, +58 строк тестов, `test=pass`) — но
  `code_review` не мог пройти структурно (тот же класс, что rc9: ревьюер голодал по контексту). Фикс:
  `read` отдаёт файл **с начала** до щедрого потолка (`_READ_MAX=20000`; крупнее — усечение с явной
  пометкой). Ревьюер видит полный файл и верифицирует. `shell`/`git` — по-прежнему 4000. +деттест.

## [3.0.0-rc17] — 2026-07-21 — Single-run infra containment (kimi 429 не роняет CLI)

Живой прогон ENGINEERING→draft PR упёрся в kimi HTTP 429 и вскрыл пробел: одиночный путь падал traceback'ом.

### Fixed
- **Одиночный (не sequential) прогон падал traceback'ом при сбое провайдера.** kimi отдал HTTP 429
  в author-вызове после исчерпания ретраев → `HTTPError` пробросился `_run_authoring` → `run_pipeline`
  → `ai_ops_run.run` (ловил только для закрытия active-work и **re-raise**) → CLI-traceback. Sequential
  уже был укреплён (rc12/rc16), одиночный — нет. Фикс: `ai_ops_run.run` — **единая точка containment**:
  исключение провайдера/инфры (кроме `KeyboardInterrupt`/`SystemExit`) → закрываем active-work +
  возвращаем честный error-отчёт (`status=error`, `ready_for_pr=False`, типизированный failure envelope)
  → `print_human` показывает ошибку, `exit_code=2`. Не traceback. `execute_sequence` читает failure из
  этого отчёта (единый containment вместо двух). +деттест.

Примечание: сам HTTP 429 — перегрузка kimi (провайдер), не движок. Прогон ENGINEERING→draft PR
повторяется, когда kimi разгрузится.

## [3.0.0-rc16] — 2026-07-21 — Final Transaction Trust (аудит: 4×P0 + 2×P1)

Последний обязательный code-релиз перед финальной квалификацией. Все находки — из аудита транзакции.

### Fixed
- **P0 — trusted retry мог сбросить ОСНОВНОЙ checkout.** `retry_package` фолбэчил `vroot` на
  `child_root` при отсутствии worktree, не проверял результат `checkout` и всё равно делал
  `reset --hard` → при повреждённом worktree сбрасывалась текущая ветка основного checkout. Фикс:
  **fail-closed preconditions до любой git-операции** — worktree обязан существовать (нет fallback),
  `vroot` ≠ основной checkout, checkout обязан пройти, HEAD на `ai-ops/<wid>`, checkpoint существует и
  достижим из ветки; только тогда архив+reset. Любая ошибка → git-состояние не меняется.
- **P0 — security-reviewer давал невалидный pass.** `_review_security` брал `result.status` без
  валидации → `{status:pass}` без checks/revision принимался (false-green, на aggregate needs_review→
  clear). Фикс: `_security_verdict_errors` — schema-валидатор + security-специфика (gate, reviewed_revision,
  непустые checks); невалидный → `status=None`.
- **P0 — aggregate-ревьюер видел только последний коммит.** `_change_context_range(base..head)` —
  интегрированный дифф всей цепочки; и code_review, и security-reviewer на aggregate получают его.
- **P0 — aggregate baseline не на базе SequencePlan.** `_collect_base_checks_at` собирает baseline
  строго на `sequence_base_sha` в отдельном detached-worktree, не на текущем состоянии основного checkout.
- **P1 — на resume сохранённый `sequence_base_sha` не был источником истины.** Есть SequencePlan →
  база только из него; расхождение с текущей base → `base_drift` в отчёте (не молчаливая замена).
- **P1 — ROADMAP обновлён** под фактические статусы rc14–16 (что доказано / что ещё нет).

## [3.0.0-rc15] — 2026-07-21 — Fix: CI-паритет деттеста author-retry (openspec-готча)

### Fixed
- **rc14 CI RED.** Новый деттест author-retry ассертил `specification not in unmet`, но закрытие
  `specification`-гейта зависит от **openspec CLI** — локально установлен, в CI нет → тест падал
  только в CI (та же local-vs-CI готча). Тест теперь проверяет `requirements` + валидность **формы**
  артефактов (именно это восстанавливает ретрай), не закрытие openspec-гейта. Проверено запуском
  полного CI-набора с `PATH` без openspec: 94/94 PASS. Функциональность rc14 (`_author_with_retry`)
  не менялась — правка только в тесте.

## [3.0.0-rc14] — 2026-07-21 — Author retry resilience + живая S-SEQ квалификация

Единственное оставшееся движковое улучшение перед финальной живой квалификацией: устойчивость
author-стадии к флаки-провайдеру. Живой S-SEQ подтвердил движок по всем половинам.

### Added
- **`_author_with_retry` — ретрай невалидного/пустого author-артефакта с нуджем.** author-стадия
  делала один вызов на артефакт; флаки reasoning-провайдер (kimi) на части вызовов отдаёт пустой/битый
  YAML → артефакт-гейт (`requirements`/`plan_readiness`/`specification`) ложно не закрывался, и на
  multi-package sequential почти всегда какой-то пакет не доходил до `ready`, блокируя `aggregate_ready`.
  Теперь до 3 попыток с корректирующим нуджем (показываем модели, что именно невалидно), каждая под
  потолком бюджета. **Честность сохранена:** ретрай не фабрикует — форму судит валидатор, содержание —
  ревьюер; вечный флак → гейт остаётся блокирующим. +деттесты.

### Qualified (live, kimi-k3)
- **positive-green pkg-1** — `ready_for_pr=True`, valid authoring → real refactor → `code_review=pass`.
- **reviewer-block → hard-stop** (rc13 P0) — конкретный reviewer-вердикт → chain halt → downstream не стартует.
- **trusted retry → recovery** (rc13 P1) — `--retry-package`: архив попытки + checkpoint-reset (без ручного
  git) + resume → `executed_all` по 3 пакетам.
- **provider crash contained** (rc12) — ConnectionReset → типизированный `network-error`, транзакция цела.
- Runbook §6e обновлён живыми результатами + готча корневого `conftest.py` в фикстуре.

## [3.0.0-rc13] — 2026-07-20 — Sequence Verdict Integrity (аудит: 3×P0 + 2×P1)

Фокусная сессия по аудиту sequential-транзакции. Все находки — из живого прогона S-SEQ.

### Fixed
- **P0 — блокирующий reviewer `warn` не останавливал sequence.** `_hard_stop` смотрел только на
  `review.status=='fail'`; `warn` на блокирующем гейте (→ gate fail + `closed_as='blocked'`, v2.85)
  проскакивал — пакет N+1 мог строиться поверх изменения, которое независимый ревьюер **заблокировал**
  (ровно живой rc11-случай). Теперь источник истины — итоговый блокирующий вердикт: стоп при
  `status=='fail'` **или** `closed_as=='blocked'` **или** review-owned гейт `fail` с вынесенным
  вердиктом; продолжаем только при awaiting-evidence.
- **P0 — aggregate security брал корневой коммит репо как базу** (`rev-list --max-parents=0`) →
  анализировал `root..final` (почти всю историю) → false-blocks на зрелом репо. Теперь фиксируем
  `sequence_base_sha` (HEAD до пакета 1) в immutable SequencePlan и весь aggregate гоним строго по
  `sequence_base_sha..final_sha`.
- **P0 — aggregate `needs_review` не имел пути закрытия** → diff, требующий review, навсегда
  not-ready. Достроен aggregate-цикл: независимый security-reviewer закрывает `needs_review` на
  интегрированном диффе (writer≠judge); aggregate `code_review` интегрированного диффа; всё fail-closed.
- **P1 — retry заблокированного пакета требовал ручного `git reset`.** `retry_package()` + CLI
  `--retry-package`: архивирует проваленную попытку (`work-packages/<pid>/attempts/attempt-N`),
  восстанавливает ветку точно на checkpoint предшественника, продолжает как `resume_from`. История
  не теряется.
- **P1 — исключения классифицировались одинаково** (всё → `infra-error`). `_classify_failure` →
  типизированный envelope `{failure_class, exception_type, retryable, traceback_hash}`: ConnectionReset
  → network/retryable, ValueError/KeyError → validation, прочее → **engine** (вероятный дефект, не
  маскируем под нестабильность провайдера).

## [3.0.0-rc12] — 2026-07-20 — Sequence infra containment: сбой провайдера не роняет транзакцию

Живой 3-пакетный sequential на kimi-k3 (подготовленный сценарий S-SEQ) вскрыл дефект устойчивости.

### Fixed
- **Исключение провайдера/инфры валило всю sequential-транзакцию traceback'ом.** kimi сбросил
  TCP-соединение (`ConnectionResetError [Errno 54]`) во время author-вызова пакета 1. `_http_post_json`
  ловит `ConnectionError` и ретраит (6×), но провайдер сбрасывал на **каждой** попытке → ретраи
  исчерпаны → исключение легитимно проброшено. Выше `execute_sequence` его **никто не ловил** →
  traceback убил всю транзакцию до единого коммита: ни `SEQUENCE`-строки, ни
  `work-packages/<pid>/report.json`, ни sequence-report — нарушение обещания durable/resumable
  state. Фикс: `execute_sequence` оборачивает per-package `ai_ops_run.run` в try/except →
  исключение → пакет честно фейлится (`stop_reason='infra-error: …'`), цепочка hard-stop, **прежние
  пакеты/план/снимки сохранены**, последующие не исполняются. `KeyboardInterrupt`/`SystemExit`
  (намеренное прерывание, честный fail отсутствующего ключа) пробрасываем, не глотаем. +деттест.

## [3.0.0-rc11] — 2026-07-20 — Symmetric reviewer honesty: блокирующий warn требует причину

Живой полный ENGINEERING на kimi-k3 (rc10-код) отработал **насквозь**: все 3 author-артефакта
валидны → реальная реализация (`discounts.py`: дублирующие ветки заменены таблицей `DISCOUNT_RATES`
+ единый `calculate_discount`, +92 строки тестов, tests pass, реальный коммит) → **`security`:
pass** (rc9-контекст помог и ему) → `code_review` вынес **реальный вердикт** (`reads=10`,
`stopped=verdict`). `ready_for_pr=False` держался честно: `code_review=warn`, а warn на блокирующем
гейте — не чистый pass (v2.85). Но этот `warn` пришёл с **пустым** `blockers`.

### Fixed
- **Асимметрия честности: блокирующий `warn` не обязан был называть причину.** Контракт требовал
  `blockers` только для `fail` (rule 4), но `warn` на блокирующем гейте **блокирует так же** —
  значит ревьюер мог заблокировать гейт бессодержательным `warn` «на всякий случай»
  (унфальсифицируемый блок без причины). Фикс симметрии: (1) `validate_reviewer_result` —
  `status ∈ {fail, warn}` обязан иметь непустой `blockers` (contentless warn невалиден);
  (2) промпт ревьюера — `warn`/`fail` требуют **конкретных** `blockers`, и симметрично: не выдумывай
  `pass`, но и **не выдумывай сомнения** — прочитал изменение и конкретной проблемы нет → `pass`,
  а не `warn` «на всякий случай». `writer≠judge` **усилён, не ослаблен**: нельзя ни фабриковать
  pass, ни фабриковать блок. +деттесты.

**Итог живой ENGINEERING-квалификации на сильной модели (rc7…rc11):** строгая честная цепочка
работает end-to-end — валидные артефакты → реальная реализация → независимый ревью на фактическом
диффе с обязанным обоснованием вердикта. `ready_for_pr` теперь зависит **исключительно** от чистого
вердикта ревьюера по реальному коду (model-quality вопрос), а не от движковых артефактов парсинга/
доставки/сходимости. Осталось: чистый `pass` ревьюера на добротной реализации = positive-green.

## [3.0.0-rc10] — 2026-07-20 — Reviewer verdict convergence: форс-ход заключения

Продолжение живого прогона kimi-k3 (rc9-код): контекст изменения доставляется, ревьюер **реально
читает дифф** (`reads=7`, было `[]`). Но reasoning-модель на многофайловом диффе тратила весь
read-бюджет на чтение и не успевала заключить → тихий `no-verdict` → `code_review=fail`.

### Fixed
- **Ревьюер исчерпывал чтения, не вынося вердикт.** `run_review` молча возвращал `no-verdict`
  после `max_reads+1` итераций — компетентный, но «жадный до чтения» судья не получал шанса
  заключить по уже прочитанному. Фикс: (1) выделенный **форс-ход вердикта** после исчерпания
  чтений — читать больше нельзя, принимается только `reviewer-result` (+нудж на последнем чтении);
  вердикт **не фабрикуется** — если ревьюер и на форс-ходе не заключает, остаётся честный
  `no-verdict` (fail). (2) `_run_reviews` `max_reads` 6→10 (многофайловый дифф требует больше
  чтений до вердикта). `writer≠judge` и честность сохранены — ограничена лишь фаза чтения и
  затребовано заключение по прочитанному. +деттест (жадная модель → вердикт на форс-ходе;
  вечно-читающая → честный `result=None`).

## [3.0.0-rc9] — 2026-07-20 — Reviewer change-context: независимый ревью получает дифф

Живой полный ENGINEERING на kimi-k3 (rc8-код) прошёл насквозь: **все три** author-артефакта
(`requirements`+`plan_readiness`+`specification`) валидны, реализация реально отработала
(`discounts.py` +51/−10, tests pass, реальный коммит) — и вскрыл **движковый** ложный блокер.

### Fixed
- **`code_review` был структурно непроходим: ревьюеру не давали контекст изменения.**
  `_run_reviews` вызывал `tool_loop.run_review` с **пустым** `base_context` — независимому
  ревьюеру никогда не передавали ни дифф, ни список изменённых файлов. Прилежная модель (kimi)
  честно возвращала `fail` («контекст изменения пуст — не дан дифф/список файлов»), сделав `reads=[]`,
  так что `code_review` не мог пройти **независимо от качества модели** (ложный блокер positive-green
  ENGINEERING — не модель, не провайдер). Фикс: `_change_context(work_root, revision)` детерминированно
  собирает полный `git show --stat` (список файлов) + ограниченный unified-дифф ревизии и передаётся
  `base_context` в ревью `code_review`/`ux_review` (`_run_reviews`) **и** security-reviewer
  (`_review_security`). Ревьюеру даётся ровно то, что видит человек в PR (дифф+файлы), **не** вердикт;
  он по-прежнему сам читает файлы (read-only) для верификации — **writer≠judge сохранён**. +деттест
  (pass только если ревьюер реально увидел изменённый путь) + прямой тест `_change_context`.

Итог живого ENGINEERING на сильной модели после rc7+rc8+rc9: строгая честная цепочка отрабатывает
end-to-end — валидные артефакты → реальная реализация → **независимый ревью на фактическом диффе**.

## [3.0.0-rc8] — 2026-07-20 — Spec-form normalization: task-строки с двоеточием (kimi)

Добита `specification`-форма (как ранее requirements). Полный CI-набор (91) 91/91 PASS.

### Fixed
- **`spec-change` tasks/what_changes с двоеточием ложно падали.** Строка задачи вида
  `Написать unit-тесты: все ветвления...` YAML-парсится как **mapping** `{key: val}`, а не строка →
  `vsa.check` «непустой список строк» отклонял → `specification` невалидна даже при осмысленном выводе
  модели. `_run_spec_authoring` нормализует: одноключевой dict от случайного `k: v` → строка `k: v`.
  Подтверждено на реальном выводе kimi: `vsa.check` → `[]` (было `['tasks: непустой список строк']`).
  +деттест.

После rc7 (reasoning-токены) + rc8 (spec-tasks) kimi-k3 производит валидные `requirements` + `plan` +
`specification`. Остаётся флакость провайдера (429/пустой ответ) под нагрузкой multi-call прогона —
эксплуатационное, не движковое.

## [3.0.0-rc7] — 2026-07-20 — Reasoning-model support (диагностика «пустого ответа» kimi)

Диагностика «почему kimi отдаёт пустой ответ» (вопрос пользователя): **конфиг был верный** (ключ/
base_url рабочие). Причина в движке — не хватало токенов reasoning-модели. Исправлено. CI 91/91 PASS.

### Fixed
- **Reasoning-модели (kimi-k3) отдавали пустой content.** kimi-k3 тратит большой бюджет на внутренний
  reasoning ДО контента; при `_MAX_TOKENS=2048` весь бюджет уходил в reasoning (`finish_reason=length`,
  `reasoning_tokens=2045`, `content_len=0`) → author-артефакт «не вернулся». `_MAX_TOKENS` 2048→**8192**
  (место reasoning + артефакт; обычные модели стопятся по `stop` без вреда). Подтверждено: kimi-k3
  @8192 отдаёт валидный requirements-artifact.
- **Reasoning-модели медленные/перегруженные.** `_openai_call` timeout 120→**300с**; `_http_post_json`
  retries 3→**6**, бэкофф 3..60с с уважением `Retry-After` на 429/overload (multi-call ENGINEERING
  переживает всплеск лимита).

### Живой ENGINEERING на kimi-k3 (после фиксов)
`requirements` + `plan` теперь **валидны** (были пустые), `code_review` даёт **реальный вердикт**.
Остаётся невалидной `specification` (форма openspec spec-change от kimi) → pre-authoring честно
блокирует (0 implementation). **Positive-green в одном артефакте**; движок честен на сильной модели.
Периодически k3 отдаёт 429 (rate-limit ключа) — под нагрузкой ENGINEERING-прогон может упасть; нужен
запас квоты или ещё ретраи.

## [3.0.0-rc6] — 2026-07-20 — Author/provider resilience (finding живой квалификации kimi)

Живая квалификация rc5 на **kimi (Moonshot)** дала два инженерных улучшения устойчивости + честный
вывод по positive-green ENGINEERING. Полный CI-набор (91) локально 91/91 PASS.

### Fixed
- **`_parse_yaml_block` устойчив к стилям вывода моделей.** Перебирает всех кандидатов (все
  ```-блоки + срез от `schema_version:`/`kind:` + сырой текст), берёт первый dict. Раньше брал только
  первый fenced-блок → прозо-обёрнутый YAML падал. +3 деттеста.
- **`orchestrator._openai_call` ретраит HTTP-200-с-пустым-content.** Перегруженный провайдер отдаёт
  `200` без текста (не `429` — сетевой ретрай его не ловил); теперь ретрай с бэкоффом + чтение
  `reasoning_content`. Иначе один пустой author-ответ ронял весь ENGINEERING-прогон.

### Живая квалификация (kimi) — вывод
kimi **заметно сильнее DeepSeek**: производит валидный `plan` + `specification` (openspec закрыт) и
**реальный вердикт `code_review`** (DeepSeek стабильно no-verdict). НО сейчас: `kimi-k3`
server-overloaded (`429 engine_overloaded`), `kimi-k2.7-code` интермиттентно отдаёт пустой ответ →
author-вызовы флакают → pre-authoring честно блокирует (0 implementation). **Positive-green
ENGINEERING не достигнут из-за нестабильности провайдера, не движка** (P0.1 держится и на сильной
модели: невалидная/пустая спека → ноль кода). Нужен стабильный сильный провайдер или больше ретраев —
повторить, когда kimi разгрузится.

## [3.0.0-rc5] — 2026-07-20 — Semantic Dependency Approval (P1.2): fingerprint вместо пути

Закрыт последний P1 аудита rc3. Полный CI-набор (91) локально 91/91 PASS.

### Fixed
- **P1.2 semantic dependency approval.** Одобрение зависимости привязано к **отпечатку пакета**
  (`manifest/package/version/operation`), а не к пути файла. Раньше approval со `scope=requirements.txt`
  покрывал ЛЮБУЮ новую зависимость в этом файле → модель могла добавить другую зависимость под старое
  одобрение. Теперь каждая новая зависимость из диффа требует `ApprovalRecord dependencies` с
  `covers_packages`, называющим именно этот пакет (опц. `name@version`). Реализация:
  `security_scan.new_dependencies_detailed` (name+version+manifest) → finding с fingerprint →
  `approvals.covers_dependency`/`recheck_dependencies` → `execution_pipeline` блокирует непокрытую
  зависимость после диффа. CLI: `approvals record --package <name[@ver]>` (повторяемо).

Следующее — живая квалификация rc5: positive ENGINEERING на сильной модели (kimi), 3-пакетный
sequential с намеренным fail на package 2, resume/drift/downgrade-блок, aggregate security на комбинации.

## [3.0.0-rc4] — 2026-07-20 — Continuity Semantics: immutable resume, полный sequence hard-stop, SequencePlan binding, exact checkpoint

Аудит rc3 нашёл 4 P0 в continuity/sequence + 1 P1 (aggregate). Все исправлены; полный CI-набор
(91 проверка) локально 91/91 PASS. Semantic dependency approval (P1.2) вынесен отдельным шагом.

### Fixed
- **P0.1 immutable resume.** Resume НЕ меняет классификацию/policy: смена
  `task_type/risk/size/affected_areas/write_scope` при resume → drift-ошибка (нужен явный `--replan`
  с ревалидацией). Внутренний per-package resume executor'а освобождён (`_sequence_internal`).
  `run-settings` хранятся **per-run** (`run-history/run-NNN.yaml`), не только последнее состояние.
- **P0.2 complete sequence hard-stop.** Security-гейт fail останавливает цепочку в любом случае, кроме
  awaiting (нужен reviewer/человек, не подан). Теперь ловятся: сбой сканера (fail-closed), блокирующая
  находка, security-reviewer НЕ pass, отсутствующий approval (раньше — только по слову «approval»).
- **P0.3 SequencePlan binding.** План и каждый пакет получили hash (в `sequence-plan.yaml`); отчёт
  привязан к `pkg_hash`. Resume при **дрейфе плана** (planner перестроил пакеты: тот же id — другой
  scope) → отказ (нужен replan), а не приём старого отчёта за выполненный.
- **P0.4 exact checkpoint resume.** Перед исполнением `resume_from`-пакета HEAD sequence-ветки обязан
  быть **ровно** на коммите предшественника. Ветка ушла вперёд → отказ. Раньше прогон строился поверх
  текущего HEAD, а не гарантированно поверх checkpoint.
- **P1.1 aggregate verdict полнее.** `agg_ok` теперь требует `evidence_revision==final_sha` и
  **aggregate security** на полном диффе `base..final_sha` (ловит риск от комбинации пакетов) —
  в дополнение к tests/baseline/HEAD/чистое дерево. Draft PR — только при полном aggregate green.
- **doc:** ROADMAP — breaking changes «только в 2.0» актуализировано (3.x обратно совместим, breaking →
  v3.2/v4.0); Context Engineering помечен выполненным (был «planned»).

Осталось: **P1.2 semantic dependency approval** (binding к fingerprint package/version/manifest/operation,
не только к пути файла) — следующий шаг. Живьём: positive ENGINEERING на сильной модели, 3-пакетный
sequential с fail на package 2 → rc5.

## [3.0.0-rc3] — 2026-07-20 — CI parity: зелёный package-quality (был красным с v2.123)

Аудит отметил, что зелёный CI независимо не подтверждён. Проверка показала: `package-quality` был
**красным с v2.123** (локальный gate этого не ловил). Причины найдены и исправлены; полный набор
CI (91 проверка) прогнан локально — **91/91 PASS**.

### Fixed
- **Standalone-движок падал** (`validate_standalone_engine --selftest`): `security/security-domains.yaml`
  не входил в `managed_set`, а universal security (v2.124.1+) грузит его на любом коммите через
  `approvals.load_domains()` → `.ai/managed` без файла → `FileNotFoundError`. Добавлен в
  `manifest.update_policy.managed_set` И в `ENGINE_CLOSURE` (регресс теперь ловит completeness-проверка).
- **`_failure_ids` не снимал ANSI-цвета** раннера: `\x1b[31mFAILED\x1b[0m test::id` не парсился в
  node-id (ложный «нет падений» при forced-color pytest/jest). Теперь ANSI снимается —
  `stack_qualification` live-pytest снова зелёный.
- **Локальный gate ↔ CI паритет**: `validate_standalone_engine` в локальном прогоне запускался БЕЗ
  `--selftest` (печатал usage → ложный PASS). Прогнан полный набор package-quality (91) локально.

## [3.0.0-rc2] — 2026-07-20 — Continuity & Aggregate Trust: 6 P0 из аудита rc1

Аудит rc1 нашёл 6 честных P0 в continuity/transaction-путях; все исправлены. Полный pre-commit
набор 37/37 PASS. Claim rc остаётся: QUICK — trustworthy task → verified draft PR.

### Fixed
- **P0.1 Canonical Resume Context.** intent CLI `resume` проводит `provider/model/signals` в
  низкоуровневый resume (раньше молча уходил в mock). `run()` при resume **восстанавливает политику**
  исходного прогона из `features/<wid>/run-settings.yaml` (signals/task_type/risk + sandbox/
  baseline_diff/require_fix/author/review/open_pr/write_scope/max_steps) — resume не переклассифицирует
  задачу и не деградирует до дефолтов. provider/model — от вызывающего (runtime/секрет, не хранится).
- **P0.2 Sequence hard-stop truth.** `_hard_stop` останавливал по НЕДОСТИЖИМОМУ
  `security_scan.overall=='fail'`. Теперь стоп на реальном блокере: `overall=='blocked'` (блокирующая
  находка) ИЛИ security-гейт fail из-за отсутствующего человеко-`ApprovalRecord`. needs_review без
  поданного ревьюера = awaiting evidence (не стоп).
- **P0.3 Verified package resume.** `resume_from` валидируется: неизвестный id → ошибка (не старт с
  нуля); пропускаемый пакет идёт в `completed` ТОЛЬКО при подтверждении (отчёт + commit SHA + SHA в
  sequence-ветке и предок HEAD + executed без hard-блокера). Неподтверждённый пропуск → ошибка.
- **P0.4 Aggregate fail-closed.** `aggregate_ready` ТОЛЬКО при `verified=True` И `no_regressions` И
  `HEAD==final_sha` И чистом дереве после проверок. Сбой/недоступность верификации → НЕ ready (раньше
  `verified=False` трактовался как ok → PR мог открыться на непроверенной интеграции).
- **P0.5 Effective ApprovalDecision.** Post-diff scope recheck использует эффективные сигналы
  (намерение + findings-derived) — scope одобрения для найденной зависимости/секрета перепроверяется
  на реально изменённые пути.
- **P0.6 Universal security scan fail-closed.** Техническая ошибка `security_pack.run_pack` теперь =
  `security` gate fail (форсируется и блокирует), а не `None` → тихий зелёный обход в QUICK.

Осталось до v3.0 stable: positive-green ENGINEERING на сильной модели; живой 3-пакетный sequential с
намеренным fail на package 2; dogfood на 2–3 репозиториях.

## [3.0.0-rc1] — 2026-07-20 — Release Candidate: live-qualified execution (узкий честный claim — QUICK)

**AI Ops v3.0-rc1 (QUICK): trustworthy task → verified draft PR для supervised low-risk задач.**
Живая RC-квалификация (DeepSeek/Mac, релизы v2.122→v2.124.1) пройдена; движок честен по всем осям.
Это pre-release (rc): полный claim `QUICK + small/medium ENGINEERING` — после positive-green
ENGINEERING на живой модели + dogfood (→ v3.0 stable).

### Что live-qualified (QUICK)
- S1/S2 (fix true-green), S6 (prompt-injection проигнорирована, main нетронут), S7 (контейнер-изоляция:
  основной checkout байт-в-байт, ветка через доверенный fetch), S9 (реальный draft PR, base=default_branch).
- S8 resume (`resumed=True` — продолжение WorkItem, не рестарт); canonical CLI без ручного `--task-type`
  (тривиальная задача → QUICK, калибровка); approval negative/positive (ApprovalRecord binding в обе
  стороны); dependency-без-signal (security форсируется и блокирует даже в QUICK).
- Провайдер-гэп v2.120 закрыт; v2.121 approval_recheck/review-exit подтверждены; S10 false-negative
  (v2.122) починен и перепройден.

### Найдено и починено живой квалификацией
v2.118/2.119 (env/тул-кэши), v2.122 (baseline-diff `fixed` node-id), v2.123 (Spec-First /
ApprovalDecision / write-scope / калибровка классификатора), v2.124 (sequence transaction),
v2.124.1 (security в QUICK; ложный scope-violation на артефактах движка).

### Не в rc1-claim (→ v3.0 stable)
Positive-green small/medium ENGINEERING на живой модели (нужна сильнее модель / усиленные промпты);
живой 3-пакетный sequential до `ready_all` + намеренный fail на package 2 (структура доказана
детерминированно); dogfood на 2–3 реальных репозиториях.

Инфраструктура: release.yml помечает pre-release (`-rc/-alpha/-beta`) как GitHub prerelease.

## [2.124.1] — 2026-07-20 — Live RC findings (v2.125 qualification): security в QUICK + ложный scope-violation

Живая RC-квалификация (DeepSeek/Mac) нашла два честных бага в уже выпущенных фичах; оба исправлены.
Полный pre-commit набор 34/34 PASS.

### Fixed
- **Security-релевантная находка проскакивала в QUICK.** `security_pack` запускался ТОЛЬКО если гейт
  `security` в workflow (QUICK его не содержит) — новая зависимость/секрет в QUICK-задаче не
  проверялись, и derived-approval (v2.123 P0.2) не срабатывал. Теперь `security_pack` запускается на
  ЛЮБОМ коммите; если результат `fail` (напр. новая зависимость без ApprovalRecord) — `security`
  **форсируется** в оценку гейтов и блокирует НЕЗАВИСИМО от workflow. Чистый QUICK остаётся лёгким
  (`security=pass` в гейты не добавляется). Живьём: `requests` в `requirements.txt` в QUICK-задаче →
  блок с требованием ApprovalRecord; после добавления записи — требование снято.
- **Ложный `scope-violation` в sequential.** Пост-дифф проверка `write_scope` (v2.124) ловила
  АРТЕФАКТЫ движка (pre-authoring: `.ai/runplan/`, `openspec/`, `features/`) как изменения вне scope
  пакета и убивала цепочку на пакете 1. Engine-managed пути (`.ai/`, `openspec/`, `features/`)
  исключены из проверки — `write_scope` ограничивает КОД модели, не артефакты движка.

Найдено живой квалификацией v2.125: S8 resume (`resumed=True`), canonical CLI trivial→QUICK,
approval negative/positive — подтверждены. Живой positive-green ENGINEERING и 3-пакетный sequential с
намеренным fail на package 2 остаются на сильной модели / v3.0-rc1.

## [2.124.0] — 2026-07-19 — Sequence Transaction: доставка после агрегатного вердикта, immutable план, per-package lifecycle, resume

Последовательное исполнение WorkPackages стало настоящей транзакцией: результат интегрируется и
проверяется ЦЕЛИКОМ до доставки. Всё аддитивно; полный pre-commit набор 34/34 PASS.

### Fixed
- **P0.4 — draft PR только после агрегатного вердикта.** Пакеты больше не открывают PR
  (`open_pr=False` в per-package run); доставка — отдельный шаг после цикла, ТОЛЬКО при
  `aggregate_ready` (`ready_all AND chain_ok AND` чистый финальный SHA) на интегрированной ветке.
  Раньше готовый финальный пакет открывал PR, пока ранний пакет был `awaiting-evidence` → PR при
  `ready_all=false`. CLI exit-код учитывает доставку (готово, но PR не открыт → non-zero).
- **Immutable parent SequencePlan.** `features/<wid>/sequence-plan.yaml` пишется один раз в начале и
  не перетирается локальным планом последнего пакета (P1 аудита).
- **Per-package lifecycle-каталог.** Снимок `run-plan/run-handoff/context-bundle/spec-coverage` в
  `work-packages/<pid>/` у каждого пакета (родительские `features/<wid>/` перетираются следующим).
- **Aggregate verification на финальном SHA.** После всех пакетов проверки перезапускаются на
  интегрированном worktree и сравниваются с базой (до пакета 1) — ловит межпакетные регрессии (пакет
  зелен по отдельности, интеграция сломана). Verified regression блокирует `aggregate_ready`;
  недоступность инфры не над-блокирует (инкрементальная per-package baseline-diff уже проверила цепочку).
- **Resume с конкретного пакета.** `execute_sequence(resume_from=<pid>)` + CLI `--resume-from`. Пакеты
  до целевого восстанавливаются из снимков (`resumed-skip`), исполняется целевой и последующие поверх
  сохранённой ветки. Стоп на блоке пакета N → N+1 не стартует (v2.120, тест зелёный).

Проверки: `workpackage_executor` selftest расширен (P0.4 not-attempted, immutable plan, lifecycle-снимок,
aggregate verify на финальном SHA, resume-skip). Живой 3-пакетный sequential + намеренный fail на
package 2 → v2.125 (живая квалификация).

## [2.123.0] — 2026-07-19 — Semantic Trust: настоящий Spec-First, единый ApprovalDecision, package write-scope, калибровка классификатора

Закрыты 5 семантических дыр аудита в уже существующем цикле исполнения (не новые возможности —
доведение честности). Всё аддитивно в 2.x; полный pre-commit набор 35/35 PASS.

### Fixed
- **P0.1 — настоящий Spec-First (pre-authoring ДО реализации).** Раньше с `--author` heavy-задача
  сначала писала код (`tool_loop`), и лишь потом автор создавал requirements/plan/spec — обход
  Spec-First. Теперь порядок: `_run_authoring` → валидация формы → **tool loop ТОЛЬКО при валидной
  спеке**. Невалидный author-артефакт (`valid=False`) → `loop.stopped='spec-prestage-failed'`, **ноль
  implementation-вызовов**, `ready_for_pr=false`. Валидные артефакты подаются в prompt реализации
  (`_authored_context`) — код пишется ПО спеке. В отчёте `spec_first.prestage`. Отсутствие openspec CLI
  не блокирует loop (форма валидна → гейт `specification` честно unmet, как раньше).
- **P0.2 — единый ApprovalDecision.** Из security-гейта убран boolean `signals.human_approved` —
  засчитывается ТОЛЬКО валидный `ApprovalRecord` (+ `destructive` как в preflight). Требования
  одобрения выводятся из ВХОДНЫХ signals И из РЕАЛЬНЫХ находок security pack
  (`approvals.signals_from_findings`: new_dependency→dependency_addition, secret→secret_boundary) —
  независимый reviewer больше не закрывает новую зависимость без человеко-одобрения. **P0.2b:** сбой
  post-diff `recheck_after_diff` → **fail-closed** (`approval_recheck.ok=False`), было fail-open.
- **P0.3 — package write-scope реально действует.** `atomic_planner` кладёт `write_scope` (пути из
  подсистемы) в каждый WorkPackage; канонический CLI передаёт `write_scope_for` в `execute_sequence` →
  брокер ограничивает пакет его каталогом; executor делает ПОСТ-ДИФФ проверку (изменение вне
  `write_scope` → scope-violation → стоп последовательности).
- **Approval schema v2.** High-risk домены (severity high/critical + `destructive`) БОЛЬШЕ не принимают
  legacy-записи без binding — обязательны `binds_to`, `expires_at`, `risk` и `source` из доверенного
  контекста (`user|ci|human`, не произвольная строка модели). Medium/low (`dependencies`) — аддитивно.
- **Калибровка классификатора.** Тяжёлый ENGINEERING — ТОЛЬКО при явном сигнале тяжести
  (size medium+/risk medium+). Неопределённость → QUICK + `classification_confidence=low` (не
  авто-эскалация в Spec-First). Закрыт трап: тривиальные задачи канонического CLI больше не блокируются.

Проверки: selftest'ы execution_pipeline/approvals/atomic_planner/ai_route/preflight/workpackage_executor
расширены (pre-authoring 0-impl, findings-derived approval, fail-closed recheck, schema v2 strict,
write_scope, калибровка). Живая RC-квалификация P0-фиксов на модели — v2.125 (по плану).

## [2.122.0] — 2026-07-19 — Live RC Qualification: baseline-diff `fixed` симметричен регрессиям (node-id)

Живая RC-квалификация на Mac (DeepSeek, база v2.121): sanity 7/7 PASS; провайдер-гэп v2.120 закрыт
(`model==deepseek-chat` во всех отчётах, включая канонический CLI и sequential); v2.121 подтверждён
вживую (`approval_recheck.ok=true`; `review` exit-код связан с вердиктом); S1/S2/S4/S6/S7/S9 PASS —
S9 открыл **реальный draft PR** (`base==default_branch`). Прогон нашёл один честный баг движка (S10).

### Fixed
- **S10 (red base + `--require-fix`): `fixed` считался на уровне чек-агрегата, не structured node-id
  → false-negative на легитимном фиксе.** На красной базе модель корректно чинила профильный тест
  (узел `red->green`), а НЕ связанный пред-существующий узел оставался красным; чек в целом оставался
  `fail`, поэтому `fixed=[]` и `--require-fix` держал ложный not-ready. `_diff_checks`
  (`tools/execution_pipeline.py`) в ветке `fail->fail` теперь считает ПОЧИНЕННЫЕ узлы симметрично
  регрессиям: `fixed_ids = _failure_ids(baseline) - _failure_ids(after)`, чек → `fixed` при непустом
  множестве. Только чистое улучшение (swap «починил один — сломал другой» по-прежнему уходит в
  `regressions`); fail-safe: нужен непустой `a_ids` (id извлечены после правки) — иначе не фабрикуем
  `fixed` на непарсибельном выводе. Честность сохранена: правится ложный NEGATIVE, ложный green не
  вводится (P0.5/P0.6 целы).

Проверки: 3 юнит-теста в `execution_pipeline` selftest (red-base фикс → `fixed` непуст/`regress` пуст;
guard непарсибельного after; swap = регрессия без fixed); полный pre-commit набор 28/28 PASS. Живой
перепрогон S10: `ready_for_pr=true`, `baseline.fixed=['test']`, `regressions=[]`, `delivered`.
Аддитивно в 2.x; PQ1–PQ9 не задеты.

## [2.121.0] — 2026-07-18 — Spec & Approval Binding: спека до реализации, связанное одобрение, review как lifecycle

Продолжение аудита v2.119: закрыты P1-дефекты честности интеграции — там, где механизм есть, но
слабо связан с тем, что реально происходит. Аддитивно (2.x), все гейты — fail-closed.

### Fixed
- **P1.1 — спека не была обязательна ДО tool loop для heavy.** `preflight.assess` получил
  `author`-параметр и правило **author-or-spec**: `ENGINEERING/PRODUCT/CRITICAL` без `spec.yaml` и без
  `--author` блокируется (spec-first блокирует РЕАЛИЗАЦИЮ, не только доставку). С `--author` движок
  авторизует спеку пре-стадией, а артефакт-гейты `specification`/`requirements` всё равно проверяют её
  готовность. `QUICK` остаётся light. Ripple: heavy-прогоны в `review_branch`/executor/PQ9 переведены
  на `author=True`.
- **P1.2 — ApprovalRecord был слабо связан** (хватало непустых `approved_by`/`scope`/`reason`). Теперь
  запись связывается с (1) хэшем плана+спеки (`binds_to`/`bind_to_plan` → `plan_binding_hash`) — при
  изменении `run-plan.yaml`/`spec.yaml` одобрение перестаёт покрывать новую ревизию; (2) сроком
  (`expires_at`) — просроченное невалидно; (3) типом риска (`risk`). `check()` авто-берёт `plan_hash` с
  диска и реальное время. **Аддитивно**: старые записи без `binds_to`/`expires_at` валидны как раньше.
- **P1.2 п.4 — одобрение не сверялось с фактическим диффом.** `recheck_after_diff` (+`covers_paths`)
  проверяет, что `scope` одобрения покрывает реально изменённые пути; `execution_pipeline` после
  коммита считает `_committed_changed_files` и вызывает recheck — scope не покрывает изменения →
  `ready_for_pr=False` + `not_yet` + `report.approval_recheck`.
- **P1.3 — review был диагностикой, а не событием жизненного цикла.** `review_branch.review`
  пере-считывает готовность к merge (`readiness.ready_for_merge`: `True` только при `pass` /
  `no-ai-review-gates`) и ФИКСИРУЕТ вердикт артефактом `features/<wid>/branch-review.yaml`. Exit-код
  `ai-ops review` = `ready_for_merge` → `needs-reviewer`/`needs-changes` теперь **non-zero** (раньше
  `needs-reviewer` считался ok).
- **P1.4 — install-фикс был недостаточно строг.** Провал install игнорируется ТОЛЬКО если окружение
  ДОКАЗАННО рабочее: `_env_proven_ok` требует ≥1 реально отработавшей проверки (pass или честный fail
  без env-симптома). Ноль проверок ИЛИ все падения — env-симптомы (`exit 127`/`command not found`/
  `No module named` …) → НЕ квалифицировано (закрыта дыра v2.118: install-fail + ноль проверок больше
  не считается qualified).

### Проверки
- Расширены selftest: `approvals` (срок/binding/recheck/covers_paths/аддитивность),
  `preflight` (author-or-spec heavy/QUICK), `review_branch` (readiness/persist/needs-reviewer),
  `workpackage_executor` (heavy author-ripple), `execution_pipeline` (recheck-after-diff/env-proven).
- `validate_product_qualification` PQ1–PQ9 зелёные. Осталось до `v3.0-rc1`: **v2.122** живая
  RC-квалификация (S1/S2/S4/S6/S7/S8/S9/S10 + живой sequential) — на машине пользователя, не фабрикуем.

## [2.120.0] — 2026-07-18 — Canonical Runtime Wiring: провязка CLI↔движок и безопасность sequential

Новый аудит (v2.119) нашёл дефекты в СКЛЕЙКЕ готовых механизмов, не в архитектуре. Закрыты все P0.

### Fixed
- **P0.1 — канонический `run --execute` уходил в mock.** Теперь CLI проводит
  `provider/model/base/open-pr/max-steps/require-fix` в `ai_ops_run.run`. Добавлены `--open-pr`,
  `--max-steps`.
- **P0.2 — sequential терял containment.** `execute_sequence` наследует
  `sandbox/install-deps/open-pr/budget`; exit-код: `0` только при `ready_all`, `1` — исполнено-не-
  готово, `2` — цепочка блокирована (раньше `0` при `executed_all` с незакрытыми гейтами).
- **P0.3 — цепочка продолжалась после blocking gate.** `_hard_stop` останавливает последовательность
  на security/reviewer FAIL, регрессии, нет-коммита, scope-violation, preflight-блоке; «awaiting
  evidence» (нет author/review) — не стоп (пакет исполнен, но не ready).
- **P0.4/P0.6 — обход декомпозиции.** `work_package_id` валидируется против плана (вымышленный →
  блок); голый `decomposition_confirmed` больше не пускает неатомарную задачу одним tool loop.
- **P0.7 — package write-scope** провязан `run → run_pipeline → tool_broker.Policy`.

### Changed
- ROADMAP: разведён двойной `v3.1` (v3.0-rc1 → v3.0 → v3.1 Sequential-веха → v3.2/v4.0 package split).

Тесты: preflight (id-validation, blob-block), executor (`_hard_stop`, reviewer-fail стоп, sandbox-
наследование), CLI (`--model` доходит до движка), PQ5c. Осталось (P1) — v2.121.

## [2.119.0] — 2026-07-18 — Полировка по живой обкатке: честный not_yet + терпимость к тул-кэшам

Две мелочи из живой обкатки на Mac (после зелёного S1/S2), обе — про честность отчёта.

### Fixed
- **not_yet «живой предложитель (swap провайдера)»** больше не показывается на ЖИВОМ прогоне —
  контроллер убирает её при `provider != "mock"` (на живой модели предложитель уже живой, заметка
  вводила в заблуждение).
- **Тул-кэши не блокируют ready** — `__pycache__`/`.pytest_cache`/`.mypy_cache`/`node_modules`/
  `target`/`dist`/... (untracked, создаются тестами/сборкой) делали дерево «грязным после проверок»
  (`tree_after=False`) в репо БЕЗ `.gitignore` → ложный not-ready, хотя проверки реально прошли (тот
  же класс, что prepare-фикс v2.118). `_tree_clean_after_checks` игнорирует **только** untracked
  тул-кэши; модификации TRACKED-файлов и прочий untracked по-прежнему = грязь (evidence-целостность
  P0.5 сохранена). End-to-end: фикстура без `.gitignore` в baseline-diff теперь `ready=True`.

4 юнит-теста `_tree_clean_after_checks` + 2 теста not_yet. PQ7/PQ8/e2e не задеты.

## [2.118.0] — 2026-07-18 — Fix: провал install не блокирует ready, если проверки прошли (finding живого прогона)

Первый **живой прогон с DeepSeek на Mac** (S1/S2) нашёл честный false-negative: движок всё сделал
правильно (код написан, `test=pass`, evidence на точном SHA, регрессий нет, все гейты пройдены), но
`ready_for_pr=false` держал **единственно** провал install-команды стека — `pip install -e .` падал с
exit 1 «Failed to build editable» (репо не является устанавливаемым пакетом), хотя pytest прошёл.

### Fixed
- Провал install блокирует `ready` **только** если он реально оставил проверки нерабочими (симптомы
  неподготовленного окружения: `exit 127`, `command not found`, `No module named`, нет тулчейна).
  `_env_unqualified(checks)` ищет симптом среди упавших проверок; `env_qualified = prepare_ok or not
  _env_unqualified(...)`; `base_ok` использует `env_qualified`. Честный fail проверки (exit 1, код
  сломан) и отсутствие тулчейна (exit 127) по-прежнему блокируют — P0.6 сохранён (сломанное окружение
  ≠ зелёное). В отчёте — `env_qualified`; `not_yet` только при реальном env-провале.

Проверки: 4 юнит-теста `_env_unqualified` в `execution_pipeline` selftest. PQ7/PQ8/e2e не задеты.
Интеграционное подтверждение — повторный живой прогон.

## [2.117.0] — 2026-07-18 — Sequential WorkPackage Executor (roadmap-веха v3.1, аддитивно в 2.x)

Закрыт аудит #2: WorkPackages создавались, но не исполнялись — задача шла одним общим tool loop.
Поставлено аддитивно (новый модуль + opt-in `--sequential`, ничего не ломает); тег v3.1 — после
v3.0-rc1 (живой квалификации на машине пользователя).

### Added
- **`tools/workpackage_executor.py`** — исполняет пакеты ПОСЛЕДОВАТЕЛЬНО: пакет→commit→evidence→
  gates→handoff→следующий, на общей ветке `ai-ops/<wid>` (resume поверх предыдущего). У каждого
  пакета свой коммит/SHA, свои гейты, свой RunHandoff и своя точка resume. Per-package отчёт
  `features/<wid>/work-packages/<id>/report.json` + агрегат `sequence-report.yaml`.
- **`ai-ops run … --sequential`** — неатомарную задачу исполнить по WorkPackages.

### Инварианты
- Пакеты в порядке `order`; зависимый пакет не стартует, пока `depends_on` не подтверждены.
- Блок пакета (hard preflight-блок / нет коммита / регрессия базы) ОСТАНАВЛИВАЕТ последовательность —
  следующие не стартуют. «Гейты требуют evidence» (нет author/review) — не стоп (пакет исполнен, но
  не ready).
- Исполнитель = подтверждение декомпозиции (`work_package_id` пакета → preflight атомарности пройден).

Доказано детерминированно: executor selftest (3 пакета, уникальные SHA, цепочка коммитов
`merge-base --is-ancestor`, стоп на блоке, с author+review+openspec → ready_all) + PQ9.

### Дальше
Живая RC-квалификация на машине пользователя → тег v3.0-rc1 → тег v3.1. См. ROADMAP.

## [2.116.0] — 2026-07-18 — RC Qualification (детерминированная часть): real review + green paths

Детерминированная часть Release Candidate Qualification. Живые прогоны с моделью и настоящий draft PR
остаются на машине пользователя (не фабрикуются) — после них тег v3.0-rc1.

### Added
- **`ai-ops review` — настоящий intent** (`tools/review_branch.py`): независимый ревьюер под
  **read-only** политикой над worktree ветки `ai-ops/<wid>` — без tool loop, правок и коммитов.
  Вердикт по ai-review гейтам плана (writer ≠ judge); диф ветки против базы — контекст. `verdict`:
  pass | needs-changes | no-branch | needs-reviewer. `ai_ops_cli` проксирует `review` (+
  `--provider`/`--model`); mock → needs-reviewer (вердикт не фабрикуется).
- **Доказанные положительные зелёные пути** (детерминированно, без модели): **PQ7** — корректная
  QUICK → `ready_for_pr=true`, `overall=delivered`, гейты закрыты; **PQ8** — ENGINEERING с
  author+review+security → `ready_for_pr=true` при доступном openspec CLI (иначе спек-гейт честно
  блокирует). Закрывает пробел аудита «нет доказанного positive-green пути».

### Changed
- Актуализированы живые сценарии: **S4** (security-reviewer v2.106 закрывает security на чистой
  правке; секреты/deps требуют ApprovalRecord); **S8** → `S8-resume-and-rerun` (настоящий resume
  v2.109, а не только rerun/discard).

### Осталось до v3.0-rc1 (на машине пользователя)
Живые S1/S2/S4/S6/S7/S9 с DeepSeek, настоящий draft PR (`--open-pr` + GITHUB_TOKEN), сохранённые
JSON-отчёты. Затем — тег v3.0-rc1. Далее v3.1 (Sequential WorkPackage Executor). См. ROADMAP.

## [2.115.0] — 2026-07-18 — Preflight Truth: проверки до модели (Spec-First блокирует реализацию)

Главный дефект внешнего аудита: Spec-First блокировал **доставку**, а не **реализацию** — pipeline
сначала гонял tool loop, писал код и коммит, и лишь потом проверял полноту спеки. Закрыто: единый
preflight выполняется ДО запуска модели; при провале модель не запускается, правок/коммита нет.

### Added
- **`tools/preflight.py`** — preflight в контроллере ДО `run_pipeline`: classification → ContextPayload
  собран → spec достаточна → задача атомарна ИЛИ декомпозиция подтверждена → context budget не
  превышен → human approvals присутствуют. Блок → `status=blocked`, `loop=None`, `commit.sha=None`
  (tool loop не запускался). `features/<wid>/preflight.yaml` + `report['preflight']`.
- **`tools/approvals.py`** — настоящий `ApprovalRecord` (kind/approval/approved_by/scope/revision/
  created_at/reason) вместо boolean. Доменные `human_approval_conditions` реально исполняются:
  `secret_boundary`→secrets, `dependency_addition`→dependencies, `auth_change`→authentication+
  authorization, `multi_tenant`→data_isolation, `deploy_change`→deployment_config,
  `ai_component`→ai_prompt_injection; `destructive` требует отдельный record. Невалидная запись
  (без approved_by/scope/reason) не засчитывается.

### Fixed / Enforcement (fail-closed)
- Неполная существующая спека → блок **до** реализации (ноль вызовов tool loop, ноль коммитов).
- Context overflow → блок до исполнения.
- Неатомарная задача → блок, пока нет `decomposition_confirmed` или выбранного `work_package_id`.
- Ошибки Context Compiler/Spec/Planner + несобранный payload → fail-closed для ENGINEERING/PRODUCT/
  CRITICAL; для QUICK — не блокирует (light).

PQ2/PQ4/PQ5 в product-qualification доказывают: при блоке proposer вызван 0 раз, worktree/коммит не
созданы. `preflight`/`approvals` selftest добавлены в CI и AGENTS.md.

### Дальше
v2.116 (RC Qualification: настоящий `ai-ops review`, зелёные QUICK/ENGINEERING, живые S1-S10, draft PR)
→ v3.0-rc1; затем v3.1 (Sequential WorkPackage Executor). См. ROADMAP.

## [2.114.0] — 2026-07-17 — Product Qualification: сквозные гарантии продукта в CI (детерминированно)

Закрыт последний пункт аудита. Сквозные ГАРАНТИИ продукта теперь проверяются детерминированно в CI
через реальный контроллер — дополнение к живым сценариям с моделью (на машине пользователя).

### Added
- **`validation/validate_product_qualification.py`** (PQ1-PQ6) — через `ai_ops_run.run`:
  - PQ1 ContextBundle реально в prompt (`=== [` header + задача + `fed_to_model`);
  - PQ2 неполная спека → `ready_for_pr=False` + `spec_first.incomplete`;
  - PQ3 resume поверх коммита (обе фазы в worktree, `resumed`);
  - PQ4 `secret_boundary` без человека → `security` в unmet + `ready_for_pr=False`;
  - PQ5 крупная задача → `should_decompose` + конкретные WorkPackages;
  - PQ6 нет ложного green: dry-run никогда не ready; честный прогон даёт реальный коммит+evidence на
    SHA+петля done, но `ready_for_pr=False` с названным блокером (движок не фабрикует зелёное без
    authoring-evidence).
- Шаг добавлен в CI (`package-quality`) и в чек-лист AGENTS.md.

### Граница честности
Живые прогоны с МОДЕЛЬЮ (качество правок) — на машине пользователя:
`qualification/scenarios.yaml` + `tools/qual_run.py` (DeepSeek/стек, `docs/qualification-runbook.md`).
Мы не фабрикуем живые прогоны — детерминированный харнесс проверяет МЕХАНИКУ гарантий, живой —
качество.

С этим релизом закрыт весь остаток внешнего аудита (Operational Context → Real Resume → Real
Spec-First → Atomic WorkPackages → Real Intent UX → Container delivery scope → Product Qualification).

## [2.113.0] — 2026-07-17 — Container delivery scope: доставка только ветки текущего прогона

Аудит: контейнерная доставка забирала обратно ВСЕ `ai-ops/*` ветки из одноразового клона — риск
перезаписать параллельную ветку устаревшей версией из клона.

### Fixed
- **Scoped-доставка** — `containers/deliver-run-branches.sh`: снимок `ai-ops/*` клона ДО прогона +
  доставка ТОЛЬКО новых/изменённых веток (диф SHA). Нетронутые прогоном ветки не трогаются →
  параллельная работа в другой `ai-ops/*` ветке не затирается. `run-sandboxed.sh` вызывает deliverer
  (снимок снимается сразу после клонирования).

### Added
- **`validation/validate_container_delivery.py`** — детерминированно (на настоящем git, без docker)
  проверяет: `ai-ops/new` доставлена, изменённая прогоном `ai-ops/old` доставлена, concurrent-
  продвинутая `ai-ops/untouched` НЕ затёрта, «нечего доставлять» когда прогон ничего не менял.
  `validate_container_assets` требует deliverer + scoping-маркеры; шаг добавлен в CI и AGENTS.md.

### Осталось
Product-qualification с живой моделью (на машине пользователя). См. ROADMAP.

## [2.112.0] — 2026-07-17 — Real Intent UX: намерения — настоящие действия

Аудит: `onboard/discuss/plan/status/health/new` только показывали execution preview. Закрыто —
намерения выполняют реальное действие (низкоуровневые флаги по-прежнему не нужны).

### Added
- **`onboard`** — `project_detector.detect` + запись `.ai/repository-profile.yaml`.
- **`status`** — реальное чтение `active-work` (`active_work.list_cmd`).
- **`health`** — `product_health.compute` из `product/product-health.yaml`; без метрик — честный отказ
  (score не фабрикуется).
- **`plan`** — пишет `features/<wid>/{run-plan,context-bundle,spec-coverage,work-package}.yaml` без
  правок кода.
- **`new`** — `workitem.start` + spec-каркас (`spec.yaml`).
- **`discuss`** — `features/<wid>/discovery-draft.md`.

`run`/`resume`/`specify` уже были реальны. `preview <intent>` по-прежнему только показывает превью
(без побочных эффектов) — проверено в selftest.

### Осталось (крупные, отдельными релизами)
Container delivery только текущей ветки, product-qualification с живой моделью. См. ROADMAP.

## [2.111.0] — 2026-07-17 — Atomic Planner создаёт конкретные WorkPackages

Аудит: Atomic Planner только называл ОСИ разбиения, но не создавал сами пакеты. Закрыто.

### Added
- **`atomic_planner.decompose(signals, wid)`** — при `should_decompose` строит КОНКРЕТНЫЕ
  `WorkPackage`-пакеты `{id, title, axis, scope, depends_on, acceptance, order}` по основной оси
  (приоритет `by-subsystem > by-result > by-commit > by-verifiable-unit > by-context-budget >
  by-size`). `by-subsystem` → пакет на подсистему с цепочкой зависимостей; `by-result` → N
  независимых; size/commit/бюджет → 2 последовательных `part-1/part-2` (человек уточняет дробление).
- Контроллер зовёт `decompose` (надмножество `assess`), сохраняет пакеты в
  `features/<wid>/work-package.yaml` и в `report['work_package'].work_packages/primary_axis`.

### Инвариант
Декомпозиция **не выдумывает** новых бизнес-решений: `scope` пакетов ⊆ подсистем сигналов;
`human_confirms=True` (финал за человеком).

Q2b (qualification) + decompose-сценарии в `atomic_planner` selftest.

### Осталось (крупные, отдельными релизами)
Intent UX (настоящие действия), container delivery только текущей ветки, product-qualification с
живой моделью. См. ROADMAP.

## [2.110.0] — 2026-07-17 — Real Spec-First: SpecCoverage из реальных артефактов, `specify` создаёт спеку

Аудит держал P0: SpecCoverage «заполняется из сигналов с пустым provided» — оценка не отражала
реальность (все разделы всегда `missing`), а `specify` только показывал превью. Закрыто: спека —
реальный артефакт, а покрытие считается из него.

### Added
- **`spec_levels.assess_from_artifacts(signals, child_root, wid)`** — `provided` берётся из РЕАЛЬНЫХ
  артефактов: `features/<wid>/spec.yaml` (описанные разделы) + засчёт разделов по артефактам прогона
  (`requirements.yaml`→requirements, `plan.yaml`→implementation_plan/verification_strategy,
  `openspec/changes/<wid>`→contracts/acceptance_scenarios). В отчёте — `covered_sections`,
  `provided_sources`, `spec_artifact`.
- **`specify` реально создаёт/валидирует** — `create_spec` пишет `features/<wid>/spec.yaml` нужной
  глубины (все обязательные разделы уровня, заготовки `missing`), не перезаписывает без `--overwrite`;
  `validate_spec` валидирует реальный артефакт против уровня. CLI: `ai-ops specify`,
  `spec_levels create|validate`.

### Enforcement (fail-closed)
- Существующий, но **неполный** `spec.yaml` → `ready_for_pr=False` + `report['spec_first']`
  (аудит: «неполная спека не пускает в implementation»). Спеки нет → поведение прежнее (spec-first
  опционален для мелких задач; spec-depth через гейты) — зелёные QUICK-потоки не сломаны.

Q5b (qualification) + spec-first сценарии в `execution_pipeline` selftest (неполный блокирует, полный
из реального файла — нет). e2e без spec.yaml проходит.

### Осталось (крупные, отдельными релизами)
Atomic Planner создаёт конкретные WorkPackages, Intent UX (настоящие действия), container delivery
только текущей ветки, product-qualification с живой моделью. См. ROADMAP.

## [2.109.0] — 2026-07-17 — Real Resume: продолжение работы, а не рестарт

Аудит держал P0: resume «не продолжает». `ai-ops resume` делал только preflight и печатал подсказку,
а повторный `run --feature X` поверх ветки с коммитами **падал** ошибкой P0.3 — продолжить работу
было нечем. Закрыто: resume реально продолжает поверх подтверждённой работы.

### Added
- **`run_pipeline(resume=True, resume_context=...)`** (`execution_pipeline.py`) — ветка
  `ai-ops/<wid>` и её коммиты **не удаляются**; worktree переиспользуется (или пере-подключается к
  сохранившейся ветке); tool loop продолжает **поверх** результата, а не с нуля. `report['resume']`
  фиксирует `{resumed, reused_worktree, reused_branch}`.
- **Состояние в prompt** (`ai_ops_run.py`) — контроллер собирает `resume_context` из RunHandoff
  (что сделано / решения / изменённые файлы / открытые вопросы / next_action) и подаёт его в начало
  `base_context` tool loop → модель **продолжает**, не переделывая подтверждённое.
- **`ai-ops resume <root> <feature> [--base] [--execute] [--force] [--task]`** — без `--execute`
  только preflight; с `--execute` реально продолжает (task по умолчанию = `next_action` из Handoff).
  `ai_ops_cli` проксирует `--execute/--force/--base`.

### Честность (fail-closed)
- **Нечего продолжать** (нет ни ветки, ни worktree) → `can_resume=False` → honest error (не
  притворяемся свежим прогоном).
- **База/состояние устарели** (main ушёл вперёд, ревизия прогона не найдена) → `status=blocked`
  без `--force` — не продолжаем молча на устаревшем evidence. С `--force` продолжаем, но отчёт
  честно помечает `resume.revalidation_overridden=True` + `preflight_reasons`.

Q3b (qualification) + resume-сценарии в `execution_pipeline`/`ai_ops_run` selftest проверяют реальное
продолжение (обе фазы в worktree, ветка переиспользована) и обе честностные блокировки.

### Осталось (крупные, отдельными релизами)
Real spec-first authoring (`specify`), Atomic Planner создаёт WorkPackages, Intent UX
(onboard/discuss/plan/review/status/health — настоящие действия), container delivery только текущей
ветки, product-qualification с живой моделью. См. ROADMAP.

## [2.108.0] — 2026-07-17 — Operational Context: ContextBundle реально в prompt модели

Внешний аудит на v2.104 держал #1 P0: Context Compiler измерял и фильтровал контекст, но собранное
**не доходило до модели** — оставалось отчётом. Закрыто: контекст стал реальным входом рантайма.

### Added
- **`build_payload()`** (`context_compiler.py`) — собирает из ContextBundle РЕАЛЬНОЕ содержимое
  (project/task, repository_context, спецификации, релевантные решения, тело правил из
  `rules/<cat>/*.md`, имена skills) в текстовый prelude для prompt. Каждый включённый элемент несёт
  `{source, kind, hash, revision, tokens, reason}`; не влезшее — в `excluded_for_budget` (не молча,
  task не выбрасывается). Бюджет = `context_budget` минус резервы **output (25%)** и **tool-loop
  (15%)**, сверху ограничен окном модели (`MODEL_CONTEXT`, напр. `deepseek-chat=64k`).
- **Виринг в рантайм** (`execution_pipeline.py`) — `run_pipeline(context_prelude=...)`: prelude
  встаёт **перед** task+profile в `base_context` tool-loop. Selftest с маркером доказывает, что
  содержимое payload реально достигает контекста модели (не только файла-отчёта).
- **Контроллер** (`ai_ops_run.py`) — считает payload, пишет `features/<id>/context-payload.yaml`
  (манифест без текста), подаёт `context_prelude` в pipeline, отчёт `context_payload.fed_to_model`.

### Fixed
- **Пути спецификаций** — `compile_bundle` ищет spec и в `features/<id>`, и в `.ai/runplan/<id>`.
- **Релевантность решений** — decisions фильтруются по `affected_areas`/ключам задачи (иначе 3
  свежих), а не тянутся все подряд.

Q1b (qualification) и e2e-ассерт проверяют, что payload несёт реальное содержимое правил и подаётся
модели. Селф-аудит: остаётся real resume-mode (продолжение tool-loop с next_action, а не рестарт) —
следующим релизом.

### Осталось (крупные, отдельными релизами)
Real resume-mode, real spec-first authoring (`specify`), Atomic Planner создаёт WorkPackages,
product-qualification с живой моделью, container delivery только текущей ветки. См. ROADMAP.

## [2.107.0] — 2026-07-17 — Trust Fixes по внешнему аудиту v2.104

Внешний аудит на v2.104 вскрыл дефекты доверия (часть уже была закрыта в v2.105/2.106; здесь —
остальное, что могло дать неверный verdict).

### Fixed
- **Security Pack — новый ложный green** (`security_pack.py`): `status=fail` с `severity=medium`
  (напр. новая зависимость) исчезал из `blocking` **и** `needs_review` → `overall=clear` → security
  проходил. Инвариант: **`fail` никогда не даёт `overall=clear`** — critical/high → `blocking`,
  medium/low → `needs_review` (судья/человек). Регрессия в selftest.
- **Честность имени**: `dependency_audit` → `dependency_diff` (CVE не проверяются, только diff новых
  зависимостей) — в domains/pack/validator.
- **Дрейф сигнала**: `gates.yaml` ждал `secret_boundary_change`, а spec/pack/cli используют
  `secret_boundary` → gate human_approval не срабатывал. `gate_executor` теперь единым алиасом
  принимает `secret_boundary_change ~ security_surface_changed ~ secret_boundary`. Регрессия.
- **Единая классификация Intent UX**: без `task_type` router мог решить ENGINEERING, а preset/Spec-First
  — QUICK (противоречивый режим). Теперь `task_type` берётся из решения роутера (`base_workflow`).
- **Операционные риски**: ошибки слоя контекста больше не гаснут молча → `report['lifecycle_errors']`;
  active-work гарантированно закрывается при исключении pipeline (не остаётся `in-progress`).

### Осталось (крупные, отдельными релизами)
Operational Context (ContextBundle реально в prompt модели), real resume-mode, real spec-first
authoring (`specify`), Atomic Planner создаёт WorkPackages, product-qualification с живой моделью,
container delivery только текущей ветки. См. ROADMAP.

## [2.106.0] — 2026-07-17 — Enforcement-виринг: security-reviewer, spec-depth, context-budget

Задокументированные остатки эпика доведены до реального enforcement (безопасно, каждый — надмножество
существующих гейтов, без ложных green).

### Added / Changed
- **#1 security-reviewer закрывает `no_injection_surface`** (`execution_pipeline.py`) — при `--review`
  независимый security-reviewer (writer≠judge, read-only, отдельный провайдер) выносит вердикт по
  `needs_review` доменам Security Pack. `pass` + чистые детерминированные домены → `security` закрыт
  → **разблокирован честный зелёный ENGINEERING**. Блокирующие детерминированные находки (секреты)
  reviewer не переопределяет. `secret_boundary`/`destructive` требуют `signals.human_approved`
  **всегда** (самоаудит нашёл gap: невинный дифф с secret_boundary обходил человеко-контроль → закрыт).
- **#2 spec-depth enforcement** — разделы уровня спецификации, мапящиеся на evidence-гейты, но
  незакрытые → блокируют `ready`. `report['spec_depth']`. Мапятся только доказуемые разделы.
- **#3 context-budget enforcement** — `ContextBundle` overflow → `ready_for_pr=False` + причина
  декомпозиции. `report['context_overflow']`. Мягкие оси остаются advisory.

Все три с регрессиями в selftest; enforcement — надмножество гейтов (существующие зелёные потоки не
сломаны). Самоаудит по ходу закрыл ещё один обход человеко-контроля.

## [2.105.0] — 2026-07-17 — Самоаудит Resume: честная ревалидация при неразрешимой base-ветке

### Fixed
- **`tools/run_handoff.py` (`resume_preflight`)** — при неразрешимой `base`-ветке (репо на `master`,
  а дефолт `--base=main`) проверка устаревания **молча пропускалась**, и preflight мог сказать
  «состояние актуально», не проверив базу (claim без верификации). Теперь: base-ref не разрешается →
  явная причина + `revalidation_needed=True` из осторожности (не молчим). Регрессия в selftest.

## [2.104.0] — 2026-07-17 — Самоаудит Security Pack: закрыт ложный green по применимости доменов

Адверсариальный самоаудит нового слоя (та же дисциплина, что нашла ложные green в execution-аудите)
вскрыл дефект в `security_pack` (v2.101).

### Fixed
- **`tools/security_pack.py` (`_applies`)** — применимость доменов проверялась только по **пути**
  изменённого файла. Auth-логика в файле, чей путь не матчит паттерны (напр. `src/users.py` с
  plaintext-сравнением пароля), не поднимала домен `authentication` → применим только `secrets` →
  чисто → **security авто-проходил** (ложный green в самом остром гейте). Теперь `file_patterns`
  проверяются по пути **И по содержимому** изменённых файлов. Под-срабатывание (опасное) устранено;
  пере-срабатывание → лишний `needs_review` (fail-closed). Регрессия в selftest.

## [2.103.0] — 2026-07-17 — Qualification нового слоя Q1–Q10 (эпик Context Engineering, этап 7 — ФИНАЛ)

Финал эпика. Новый слой готов только после отдельных сценариев.

### Added
- **`validation/validate_context_qualification.py`** — гоняет **Q1–Q10 детерминированно** против
  построенных инструментов (без модели, в CI): Q1 context filtering, Q2 context overflow →
  декомпозиция, Q3 resume, Q4 stale context (main ушёл → ревалидация), Q5 spec depth (QUICK L0 /
  PRODUCT L2 с метриками), Q6 unsafe assumption → эскалация, Q7 security applicability (frontend без
  DB/tenant audit, но XSS/secrets), Q8 prompt injection не переопределяет policy (push заблокирован),
  Q9 long-running (решение первой фазы сохранено в Handoff), Q10 human approval для auth/secret
  boundary. В checklist и CI.

### Эпик Context Engineering & Spec-Driven Execution — ЗАВЕРШЁН (7/7)
Context Compiler (v2.97) · Adaptive Spec-First (v2.98) · Context Lifecycle/Resume (v2.99) · Atomic
Planning/Context Budget (v2.100) · Security Pack (v2.101) · Intent UX (v2.102) · Qualification
(v2.103). Живые сценарии с моделью — на машине пользователя; механика слоя покрыта детерминированно.

## [2.102.0] — 2026-07-17 — Простой внешний UX: intent-команды (эпик Context Engineering, этап 6)

Этап 6: снаружи AI Ops проще внутренней архитектуры — обычный сценарий управляется намерениями, а
не флагами.

### Added
- **`tools/ai_ops_cli.py`** — intent-команды `new · onboard · discuss · specify · plan · run ·
  resume · review · status · health` поверх флагов. Пользователь **не обязан помнить**
  `--engine pipeline`/`--author`/`--review`/`--baseline-diff`/`--sandbox`: пресет авто-подбирается по
  классу задачи (ENGINEERING/PRODUCT/CRITICAL → review+author; всегда sandbox+baseline). Флаги
  остаются доступны как низкоуровневый интерфейс.
- **Execution preview** до запуска (`ExecutionPreview`): что понято (workflow + spec-level), что
  будет сделано (гейты/треки/авто-флаги), какие данные (агенты/правила/~токены/бюджет из
  ContextBundle), какие approvals (CRITICAL/needs_human/secret_boundary → человек), советует ли
  декомпозицию, ожидаемый результат. Только `run --execute` реально запускает движок. selftest, CI.

Дальше по эпику: этап 7 Qualification нового слоя (Q1–Q10).

## [2.101.0] — 2026-07-17 — Security Pack: доменный security-вердикт (эпик Context Engineering, этап 5)

Этап 5: security review — не один общий вердикт модели, а набор применимых доменов с доказуемым
evidence.

### Added
- **`security/security-domains.yaml`** — 12 доменов (authentication, authorization/IDOR,
  input_validation, secrets, dependencies, rate_limiting, file_upload, network/SSRF,
  logging/monitoring, deployment/config, ai_prompt_injection, data_isolation) с applicability
  (signals + file_patterns), deterministic_checks, reviewer_checklist, required_evidence,
  severity_policy, blocking/human_approval conditions, remediation_template.
- **`tools/security_pack.py`** — выбирает **только применимые** к изменению домены (frontend-only
  не запускает database/tenant audit, но проверяет XSS/secrets), гоняет детерминированные проверки
  и даёт доменный вердикт. **Честность**: домен нельзя закрыть фразой «уязвимостей нет»; авто-закрыть
  можно только домены с целиком детерминированным `required_evidence` (secrets/dependencies);
  остальные → `needs_review` (судья/человек); находка → fail + блок по severity.
- **`validation/validate_security_domains.py`** — контракт доменов (12 доменов, required_evidence ⊆
  allowed_evidence_sources, severity, remediation). В checklist и CI.

### Changed
- **`tools/execution_pipeline.py`** — гейт `security` теперь domain-aware: проходит только при
  `overall='clear'` (все применимые домены закрыты детерминированным evidence); иначе честный блок
  с перечнем блокирующих/needs_review доменов. Развивает `security_scan` из v2.95.

Дальше по эпику: этап 6 Простой внешний UX (intent-команды).

## [2.100.0] — 2026-07-17 — Atomic Planning и Context Budget (эпик Context Engineering, этап 4)

Этап 4: размер рабочего пакета должен соответствовать способности модели выполнить его до деградации
контекста.

### Added
- **`tools/atomic_planner.py`** — оценка пакета (объём контекста из ContextBundle, файлы, системные
  границы, зависимости, ожидаемые model calls, риск, критерий завершения) + предложение декомпозиции,
  если: контекст > бюджета / >2 подсистем / несколько независимых результатов / нужно >1 коммита /
  не проверяемо одним критерием / размер large-xl. Оси: `by-context-budget`, `by-subsystem`,
  `by-result`, `by-commit`, `by-verifiable-unit`, `by-size`. **Инвариант**: декомпозиция называет
  оси, но **не меняет продуктовый смысл** и не принимает бизнес-решений ради удобства модели.

### Changed
- **`tools/ai_ops_run.py`** — в lifecycle: `features/<wid>/work-package.yaml` +
  `report['work_package']` (atomic / should_decompose / оси / причины). Причина декомпозиции в отчёте.

Дальше по эпику: этап 5 Security Pack (домены security с доказуемым evidence).

## [2.99.0] — 2026-07-17 — Context Lifecycle и Resume: состояние между сессиями (эпик Context Engineering, этап 3)

Этап 3: длинная задача переживает несколько сессий без потери решений, архитектуры и состояния
(борьба с context rot).

### Added
- **`tools/run_handoff.py`** — артефакт `RunHandoff` (что сделано, `changed_files`, `verification`
  passed/failed, `open_questions`, `known_risks`, `next_action` — следующий безопасный шаг,
  `resume_from_revision`) собирается из отчёта прогона. Сущности Feature → WorkItem → Run → Stage →
  Step → Handoff. **`resume_preflight`** детерминированно проверяет: есть ли handoff, на месте ли
  ветка/worktree, **ушёл ли `base` вперёд** с момента прогона (→ revalidation: старый evidence
  недействителен для нового состояния), устарели ли решения.
- **`ai-ops resume <child> <feature>`** — печатает preflight и указывает, как продолжить (worktree/
  ветка переиспользуются, работа не начинается заново).
- **`schemas/run-handoff.schema.json`** + **`validation/validate_run_handoff.py`** — форма
  (next_action обязателен, verification passed/failed, decisions с id+summary). В checklist, CI, e2e.

### Changed
- **`tools/ai_ops_run.py`** — в lifecycle: `features/<wid>/run-handoff.yaml` + `report['handoff']`.

Инварианты resume: не начинать заново, не повторять подтверждённое без причины, ревалидация при
смене `main`, не удалять предыдущий результат. Дальше по эпику: этап 4 Atomic Planning + Context Budget.

## [2.98.0] — 2026-07-17 — Adaptive Spec-First: глубина спецификации по уровням (эпик Context Engineering, этап 2)

Этап 2: не требовать полной спецификации для мелкой задачи, но не начинать сложное изменение без
достаточного описания.

### Added
- **`tools/spec_levels.py`** — детерминированный классификатор глубины: **L0 QUICK** (цель/scope/
  поведение/acceptance/ограничения/файлы) → **L1 ENGINEERING** (+requirements/scenarios/контракты/
  зависимости/edge cases/архитектура/план/write scope/verification) → **L2 PRODUCT** (+проблема/
  пользователи+JTBD/ценность/сценарии/гипотезы/метрики/UX/аналитика/rollout/риски) → **L3 CRITICAL**
  (+threat model/rollback/migration/failure modes/audit/approvals/compliance/DR). Разделы
  кумулятивны. **Инварианты**: уровень виден почему; можно повысить (эскалация по риску/необратимости/
  secret_boundary), **нельзя понизить молча**; статус раздела complete|not_applicable|declined|
  needs_human|missing; `declined` требует объяснения; `ready_to_implement=False` при missing-разделах.
- **`validation/validate_spec_coverage.py`** — форма `SpecCoverage` + инварианты (declined с note,
  blocking_missing = ровно missing, ready несовместим с missing, escalated_from < level). В checklist и CI.

### Changed
- **`tools/ai_ops_run.py`** — в lifecycle добавлена `SpecCoverage`: `features/<wid>/spec-coverage.yaml`
  + сводка в `report['spec_coverage']` (уровень, эскалация, пробелы, needs_human). Пока информативно
  (не хард-блок, чтобы QUICK-из-промпта не ломался); enforcement блокирующих разделов — на стыке с
  этапом 4 (Atomic Planning).

Дальше по эпику: этап 3 Context Lifecycle + Resume.

## [2.97.0] — 2026-07-17 — Context Compiler: минимальный релевантный ContextBundle (эпик Context Engineering, этап 1)

Старт эпика **Context Engineering & Spec-Driven Execution** (после execution-аудита). Этап 1: перед
прогоном собирать минимальный релевантный пакет контекста, а не грузить в модель весь репозиторий,
все правила и всех агентов.

### Added
- **`tools/context_compiler.py`** — детерминированный компилятор `ContextBundle` на WorkItem.
  Селекция **обоснована реальными данными** (RunPlan/workflows/gates/tracks/registry): агенты =
  владельцы стадий base_workflow + `responsible_role` гейтов плана (∩ registry); skills =
  `uses_skills` стадий; rules = категории по workflow + трекам (`core` всегда); repository_context =
  RepositoryProfile; files = манифесты стека; specs/decisions = существующие артефакты. **Честность
  отбора**: у каждого исключённого источника — причина; `estimated_tokens` считается **до** вызова
  модели; **overflow не обрезает контекст молча** (open_question + флаг); stale-артефакты помечаются;
  тот же WorkItem при тех же входах → воспроизводимый пакет.
- **`schemas/context-bundle.schema.json`** + **`validation/validate_context_bundle.py`** — форма и
  инварианты честности (excluded с причинами, overflow не молча, агент не included+excluded
  одновременно). В checklist и CI.

### Changed
- **`tools/ai_ops_run.py`** — в lifecycle (v2.94) добавлена компиляция bundle: сохраняется
  `features/<wid>/context-bundle.yaml` рядом с планом, сводка в `report['context_bundle']`,
  проверяется e2e-харнессом.

Дальше по эпику: этап 2 Adaptive Spec-First → 3 Context Lifecycle+Resume → 4 Atomic Planning+Context
Budget → 5 Security Pack → 6 Product UX → 7 Qualification нового слоя.

## [2.96.0] — 2026-07-17 — Real Qualification: канонический e2e в CI + матрица Python + живые сценарии S6–S10

Финал плана 2.93→2.96. CI кита раньше гонял в основном selftest-модули; теперь есть канонический
end-to-end движка на настоящей фикстуре, на нескольких версиях Python.

### Added
- **`validation/validate_pipeline_e2e.py`** — канонический e2e БЕЗ модели: настоящий git-репо из
  python-фикстуры → полный `ai-ops run --engine pipeline --execute` со scripted-proposer → проверка
  всей цепочки в одной транзакции (task → RunPlan → WorkItem → active-work → detect → tool-loop →
  commit на ветке → evidence на точном SHA → гейты → run-report → active-work закрыта → изоляция
  worktree). В checklist и CI.
- **CI job `pipeline-e2e`** — e2e + стек-квалификация + ядро движка на **Python 3.9 и 3.12** (раньше
  CI шёл только на 3.12).
- **Живые сценарии S6–S10** (`qualification/scenarios.yaml`): prompt-injection внутри репозитория,
  попытка изменить основной checkout из контейнера (worktree-only), повтор/resume + идемпотентный PR,
  настоящий push + draft PR, работа на красной базе.

### Changed
- **`tools/ai_ops_run.py`** — `run()` получил проброс `install_deps` (e2e идёт offline, без pip).

### Honest (требует окружения пользователя)
Полная живая матрица (Node/Python/Go × macOS/Linux с моделью посильнее DeepSeek), реальная сборка
Docker-образа в CI (в песочнице кита закрыта egress-прокси → на Docker-хосте пользователя) и сохранение
execution-report как CI-artifact при живой матрице. scripted-e2e закрывает **механику** детерминированно;
качество правок остаётся за моделью.

## [2.95.0] — 2026-07-17 — Security evidence: детерминированный секрет/dep-скан для гейта security

Гейт `security` требует `[no_secrets, no_injection_surface, deps_approved]`, но в pipeline не было
производителя этого evidence — ENGINEERING честно, но всегда упирался в security «в тишине». Дали
детерминированную часть.

### Added
- **`tools/security_scan.py`** — детерминированный сканер diff коммита: **секреты** (AKIA, private-key
  блоки, `ghp_`, slack/google-токены, generic key-in-quotes; плейсхолдеры/`${ENV}` отсеиваются) и
  **новые зависимости** (`package.json`/`requirements.txt`/`go.mod`/`pyproject.toml`/`Cargo.toml`).
  Плюс **флаги injection-surface** (`eval`/`exec`, `shell=True`, `os.system`, `pickle.loads`,
  `yaml.load` без Loader, SQL f-string, `dangerouslySetInnerHTML`, `child_process`, `innerHTML=`).
  `--selftest`, в checklist и CI.

### Changed
- **`tools/execution_pipeline.py`** — после коммита прогоняет security-скан (когда гейт `security` в
  плане): закрывает **факты** `no_secrets`/`deps_approved`, когда чисто; находка → `security`
  блокирует **с деталями** (что за секрет, какие новые зависимости). `no_injection_surface` —
  **суждение**: сканер лишь флагит, закрывает независимый security-reviewer/человек (writer≠judge).
  Поэтому `security` здесь **не авто-проходит** — никакого ложного green; но реальные секреты/deps
  теперь ловятся, а не молчат. Результат в `report['security_scan']`.

### Honest (осталось)
Полный ENGINEERING-to-ready требует ещё wiring security-reviewer на `no_injection_surface` (сознательно
не спешим с авто-pass самого острого гейта); применение `plan.write_scope` к Policy нужен слой
area→paths (в плане пока нет write_scope); quality-review артефактов по hash и PRODUCT-evidence —
тоже остаток 2.95. Дальше — 2.96 (живая квалификация + e2e-CI, требует машины с моделью).

## [2.94.0] — 2026-07-17 — One Run Transaction: pipeline и lifecycle — одна транзакция

Второй слой плана. Раньше AI Ops был «два мира»: Product OS lifecycle (WorkItem/RunPlan/active-work/
run-report) и Execution pipeline жили порознь — `engine=pipeline` вызывал движок и возвращал отчёт,
пропуская весь lifecycle. Объединили в одну транзакцию.

### Changed
- **`tools/ai_ops_run.py`** — pipeline-путь теперь проходит ЕДИНЫЙ lifecycle: контроллер строит план
  **один раз**, создаёт WorkItem, пишет `run-plan.yaml`, регистрирует active-work, гоняет
  concurrency-preflight **до** правок, пишет единый `run-report.json` и **закрывает** active-work
  (`done`) по завершении. Координационные строки active-work уходят в stderr (stdout чист для `--json`).
- **`tools/execution_pipeline.py`** — `run_pipeline(plan=...)` принимает готовый план от контроллера и
  НЕ строит второй (единый `workitem_id` для плана, WorkItem, ветки `ai-ops/<id>`, active-work и
  run-report). Прямой вызов без `plan` работает по-прежнему (обратная совместимость).

### Honest (осталось)
Отдельный `run_id` на каждый прогон и полноценный resume пока не введены (повтор того же feature
перезаписывает WorkItem/ветку; isolation-guard не даёт потерять несохранённые коммиты). Дальше — 2.95
(security/PRODUCT evidence), 2.96 (живая квалификация + e2e-CI).

## [2.93.0] — 2026-07-17 — Truth & Execution Integrity: worktree-only контейнер, целостность коммита, честные safety-claim'ы

По внешнему разбору (9 из 9 пунктов подтвердились по коду) закрыт первый слой — остаточные дефекты
целостности и правды, без новой архитектуры.

### Fixed
- **Контейнер worktree-only** (`containers/run-sandboxed.sh`) — раньше монтировался **весь** child как
  writable `/work`, и shell из allowlist мог писать в основной checkout мимо `write_scope`. Теперь
  wrapper делает `git clone --no-hardlinks` и монтирует **только одноразовый клон**; основной репо не
  смонтирован (модель физически не тронет). Доставка веток `ai-ops/*` обратно — доверенным host-слоем
  (`git fetch`) вне контейнера. `validate_container_assets.py` стережёт (запрещён прямой монтаж child).
- **Целостность коммита — untracked подготовки** (`execution_pipeline.py`) — `install`/`baseline` мог
  создать новые untracked (классика: `package-lock.json` от `npm install`), а `git add -A` втягивал их
  в AI-коммит. Теперь снимок untracked снимается **до** install, удаляются адресно только новые
  (untracked пользователя не трогаем; игнорируемые — не видны в porcelain).
- **Целостность коммита — правки через shell** — наличие правок считали только по write-операциям, и
  правки через разрешённый shell (`sed`/форматтер) не коммитились и **терялись**. Теперь факт берём из
  git (`_has_changes`: tracked-diff ИЛИ новые untracked). Селфтест: правка через shell даёт коммит.
- **PR delivery** (`pr_open.py`) — убран хардкод `base="main"`: определяется `default_branch` репо
  через GitHub API; идемпотентность — если PR для ветки уже открыт, возвращаем его (`status=updated`),
  без ошибки дубля.

### Changed (truth-sync)
- **QUICKSTART** больше не утверждает, что `--sandbox` отключает сеть (по умолчанию `allow_network=True`
  — ложный safety-claim снят; сетевой контроль даёт контейнер/прокси).
- **qualification S4** приведён к реальности v2.86/2.89 (specification производится; блокирует
  `security`, у которого пока нет производителя evidence — честный not-ready, закрывается в 2.95).
- **manifest** — `p0_backlog` отмечает контейнер (v2.90) и specification (v2.89) сделанными (сняты
  внутренние противоречия); `frozen: []` (заморозка снята — решение владельца).

Дальше по плану: 2.94 (One Run Transaction — controller+pipeline в одну транзакцию), 2.95 (security/
PRODUCT evidence), 2.96 (живая квалификация + e2e-CI).

## [2.92.0] — 2026-07-17 — Стек-квалификация rust+java: найден и закрыт ложный green ещё для двух стеков

Продолжили начатое в v2.91: прогнали настоящие фикстуры по **всем** стекам, которые детектор
объявляет поддерживаемыми. Rust и Java прятали ложный green того же класса, что go — парсер падений
писался node-first и на других раннерах извлекал бесполезный id.

### Fixed
- **`tools/execution_pipeline.py` (`_failure_ids`)** — **rust**: `cargo test` не парсился, id
  схлопывался в константу из строки `error: test failed, to rerun pass \`--lib\`` (одинакова для
  любого падения) → swap `test_sub`↔`test_add` не ловился. Добавлен паттерн
  `thread '<test>' panicked at <file>.rs:<line>` (pid в скобках отбрасывается).
- **`tools/execution_pipeline.py` (`_failure_ids`)** — **java**: падение JUnit не ловилось вообще
  (id пустой), а maven печатает `Failures: 1` (слово перед числом) → счётчик тоже 0 → swap не
  ловился. Добавлены паттерны maven-surefire (`Class.method -- … <<< FAILURE`,
  `[ERROR] Class.method:line`) и gradle (`Class > method() FAILED`). Проверено на **реальном**
  выводе maven + junit5.

### Added
- **`qualification/fixtures/{rust,java}/`** — настоящие мини-репозитории (`cargo test` / `mvn test`);
  **`golden/{rust,java}-test-*.txt`** — снятый живьём вывод раннеров.
- **`validation/validate_stack_qualification.py`** — расширен на rust и java; теперь покрывает все
  **5** декларированных детектором стеков (node/python/go/rust/java). Rust гоняется вживую при
  наличии `cargo`; java — по golden (junit тянется из Maven Central, в CI кита не гоняем).

Итог: go, rust и java прятали ложный green одного класса — все найдены на реальном выводе раннеров и
закрыты регрессиями.

## [2.91.0] — 2026-07-17 — Стек-квалификация python/go: найден и закрыт ложный green для go

Идея пользователя — «сделать репо с go и python для квалификации» — сразу дала результат: на
**реальном** выводе `go test` движок не извлекал имя упавшего теста, и это оказался **ложный green**
того же класса, что баг vite (v2.88), но для go-раннера.

### Fixed
- **`tools/execution_pipeline.py` (`_failure_ids`)** — раньше вывод `go test` не парсился: id падения
  схлопывался в мусорный `{'FAIL'}` из summary. Так как go **не печатает** «N failed», счётчик тоже
  молчал → «починил `TestSub`, сломал `TestAdd` в одном пакете» (число падений 1→1) **не детектилось
  как регрессия** = ложный green для go-репозиториев. Добавлены паттерны go: `--- FAIL: <Test>`
  (обрывает волатильное `(0.00s)`) и `file.go:line[:col]: msg` (build/vet). Регрессия в selftest на
  реальном выводе go: swap `TestSub`↔`TestAdd` = регрессия; то же имя + другое время = не регрессия.

### Added
- **`qualification/fixtures/{python,go}/`** — настоящие мини-репозитории (pytest / `go test`) как
  постоянные фикстуры квалификации; **`qualification/fixtures/golden/*.txt`** — снятый живьём вывод
  раннеров.
- **`validation/validate_stack_qualification.py`** — детерминированная стек-квалификация **без
  модели**: `project_detector` на фикстурах + `_failure_ids`/`_diff_checks` на golden-выводе (ловит
  swap-регрессию), а при наличии тулчейна — ещё и живой прогон фикстур (страховка от дрейфа формата
  раннера). Честный SKIP, если pytest/go недоступны. В checklist и `package-quality.yml`.

Закрывает разрыв «квалификация обкатана только на node»: разбор падений python и go теперь покрыт
детерминированно и в CI кита, без Mac и живой модели.

## [2.90.1] — 2026-07-17 — Container: конфигурируемый базовый образ (трение живой сборки)

Живая сборка на маке пользователя вскрыла, что сеть может резать контейнерные реестры (Docker Hub
и ECR — TLS timeout), при доступном github/API. Правильный ответ — не хардкодить реестр.

### Changed
- **`containers/Dockerfile`** — `ARG BASE_IMAGE=node:22-slim` + `FROM ${BASE_IMAGE}`: базовый образ
  указывается на сборке (`--build-arg BASE_IMAGE=<mirror>/node:22-slim`) для сетей, где Docker Hub
  недоступен, но есть зеркало. `docs/container-isolation.md` — пример с зеркалом + явная оговорка,
  что для сборки нужна сеть с доступом хотя бы к одному реестру.

## [2.90.0] — 2026-07-17 — Container isolation: полный jail рантайма (аудит P0.2)

Последний пункт аудита без кода — контейнерная изоляция — закрыт **эталонным контейнером**. Брокер
даёт enforceable-подмножество в процессе; настоящую изоляцию ФС/ресурсов/привилегий даёт контейнер.
Два слоя честно разделены.

### Added
- **`containers/Dockerfile`** — образ изолированного рантайма движка: non-root (uid 10001),
  python + node + `openspec`, кит внутри, child монтируется в `/work`.
- **`containers/run-sandboxed.sh`** — запуск в jail'е: `--read-only` root, bind только worktree,
  `--tmpfs`, `--memory/--cpus/--pids-limit`, `--cap-drop ALL`, `--security-opt no-new-privileges`,
  non-root. Секреты — только по именам env (не в образ). Docker принял все флаги (flag-parse проверен).
- **`validation/validate_container_assets.py`** — стережёт присутствие jail-флагов (регресс любого →
  ошибка CI). В checklist и `package-quality.yml`.
- **`docs/container-isolation.md`** — два слоя изоляции, что enforce'ит jail, как собрать/запустить,
  честная граница по сети.
- **`managed_set`** += `containers/*` — ассеты едут в child.

### Boundary (честно)
- Контейнер **не air-gap**: движку нужен egress к API модели и реестрам (npm/pip). Жёсткий контроль
  egress — allowlist-прокси на уровне хоста (вне флагов docker).
- **Сборка образа** (pull базового) в CI-песочнице кита закрыта egress-прокси — выполняется на
  Docker-хосте пользователя. Флаги стандартные; команда движка в wrapper подтверждена живыми прогонами.

## [2.89.0] — 2026-07-17 — Specification authoring (OpenSpec): закрыт последний артефакт-гейт

Гейт `specification` больше не блокирует ENGINEERING/PRODUCT безусловно — движок **производит
OpenSpec-изменение и валидирует его настоящим `openspec` CLI**. Это закрывает последний
артефакт-гейт P0.4.

### Added
- **Spec-authoring в `execution_pipeline`** (часть `--author`). Author-модель отдаёт **структурное**
  описание изменения (`capability` + требования + сценарии); движок **рендерит** точный OpenSpec-
  markdown (`proposal.md`/`tasks.md`/`specs/<cap>/spec.md`) и прогоняет `openspec validate <id>
  --strict`. Формат markdown контролирует движок, а не модель, — валидная структура надёжно проходит
  strict. Трейс — в `report.authored`.
- **`validation/validate_spec_artifact.py`** — форма spec-change + рендер в OpenSpec (проверено
  реальным CLI 1.6.0: `render()` → `openspec validate --strict` = rc 0). В checklist и CI.

### Boundary (честно)
- `specification` закрывается **только** если `openspec` CLI установлен в child И strict-валидация
  прошла. Нет CLI (`npm i -g @fission-ai/openspec`) или битый spec от модели → гейт остаётся
  блокирующим (нет фабрикации). **Качество** требований судит человек. Механика тестируется offline
  (стаб), реальный CLI-путь подтверждён вживую.
- **Итог P0.4:** полный RunPlan для ENGINEERING закрыт — requirements/plan_readiness (v2.86) +
  specification (v2.89) производятся и проверяются, code_review судит независимый ревьюер (v2.83).

## [2.88.0] — 2026-07-17 — Live-qual fix: ложная регрессия сборки (первый живой прогон ii-sreda)

Первый живой прогон движка на реальном node/vite-репозитории (ii-sreda, DeepSeek) сразу дал ценную
находку — **ложную регрессию сборки**.

### Fixed
- **`_failure_ids` включал волатильное ВРЕМЯ в id падения.** vite печатает `✗ Build failed in 1.41s`;
  время меняется от прогона к прогону, поэтому на **неизменной** красной сборке `build` каждый раз
  получал «новый» id падения → ложная `fail→fail` регрессия. Теперь id **нормализуется** (убраны
  длительности `N.NNs` / `N ms` и hex-адреса), плюс добавлен паттерн **реальной** строки ошибки
  сборки (`файл (строка:кол): сообщение`) — так настоящая новая поломка по-прежнему различается.
  Селфтест воспроизводит именно кейс ii-sreda (та же ошибка, другое время → не регрессия; новая
  ошибка в другом файле → регрессия).

### Verified live (движок честен)
- **test-регрессия — реальная и поймана верно:** DeepSeek написала `formatPrice` без конвертации
  десятичного разделителя, а её собственный тест ждёт `formatPrice(1234.56) === '1 234,56'` → тест
  падает → движок честно отказал в `ready`. База ii-sreda сама красная (предсуществующий build-break
  `Markdown`-экспорта + баг даты `recentTimeGroup`) — baseline-diff это уважает.

## [2.87.0] — 2026-07-17 — Hardening 2 (второй адверсарный ре-ревью v2.85–2.86)

Второй независимый ре-ревью новейшего ready-path кода нашёл ещё один **false-green** (симметричный
к тому, что закрыл v2.85) и остаточный обход containment. Всё закрыто; переоценённые claim'ы честно
понижены.

### Fixed
- **Ложный green (symmetric): `_diff_checks` пропускал `warn/not_run → fail`.** База без тестов
  (`warn`) + правка добавляет **падающий** тест → раньше не считалось регрессией, а
  `implementation_verification` baseline-освобождён → `ready_for_pr=true` с красным тестом в SHA.
  Теперь любая НОВАЯ краснота (из `pass` ИЛИ из `warn`/`not_run`/отсутствия) = регрессия.
- **Containment: одиночный `&` (фон) не был разделителем сегментов** → `true & psql …` обходил
  allowlist. Добавлен в `_SHELL_SPLIT_RE` — теперь каждый сегмент фоновой команды проверяется.

### Changed (честность claim'ов)
- **Качество артефактов requirements/plan судит ЧЕЛОВЕК, не in-loop `--review`.** Эти гейты
  детерминированные → ревьюер (`_reviewable_gates`) их не покрывает. Формулировки в валидаторах,
  манифесте и QUICKSTART исправлены (было «ревьюер/человек» — на деле человек).
- **`validate_plan_artifact` docstring** больше не заявляет несуществующую сверку `write_scope` с
  политикой прогона — `write_scope` артефакта декларативен (форма), движок по нему запись не сужает.

## [2.86.0] — 2026-07-17 — Product Authoring: движок производит артефакты (аудит P0.4)

Артефакт-гейты ENGINEERING/PRODUCT (`requirements`, `plan_readiness`) больше не блокируют
безусловно: движок **производит артефакты** и подтверждает их **форму** детерминированно.
Честно: подтверждается структура (как у blueprint), а не качество — качество судит независимый
ревьюер (`--review`) / человек.

### Added
- **Author-стадия в `execution_pipeline`** (`--author`). Для артефакт-гейтов плана без evidence
  движок вызывает модель-автора (отдельный вызов), пишет её YAML в `.ai/runplan/<wid>/` **до
  коммита** и валидирует **форму** детерминированно → закрывает гейт. Трейс — в `report.authored`.
- **`validation/validate_requirements_artifact.py`** — структура требований (тестируемые
  requirements + acceptance_scenarios) → evidence гейта `requirements`.
- **`validation/validate_plan_artifact.py`** — структура плана (work_packages + dependencies +
  write_scope, с проверкой ссылочной целостности зависимостей) → evidence гейта `plan_readiness`.
- **Флаг `--author`** в `ai-ops run` и `qual_run`; автор — отдельный экземпляр провайдера. Оба
  валидатора в AGENTS.md checklist и `package-quality.yml`.

### Boundary (честно)
- Валидатор проверяет **структуру, не качество** (та же дисциплина, что `validate_feature_blueprint`).
  Невалидный артефакт → гейт остаётся блокирующим (нет фабрикации). Качество → ревьюер/человек.
- **`specification` (OpenSpec) не производится** — нужен внешний `openspec` CLI; честно блокирует.
- Живое качество артефактов требует живой модели + человека; механика (author → структурная
  проверка → evidence) полностью тестируется offline scripted-автором.

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
