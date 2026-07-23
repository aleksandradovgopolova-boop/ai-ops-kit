# Acceptance criteria — Research v0.2

Зафиксировано 2026-07-23 по итогам семи боевых прогонов (RR-001…RR-007).
Статус: **v0.2 ПРИНЯТ** — все критерии закрыты проверяемыми артефактами.

| # | Критерий | Чем закрыт | Проверка |
|---|---|---|---|
| 1 | Контракты RR/EV/DP версионированы и валидируются | schemas/research-{request,evidence}.schema.json, decision-package.schema.json (schema_version 1; поля v0.2: quote, decision_brief, cost_of_recommendation, constraints_addressed) | CI: validate_research_artifacts.py |
| 2 | Ссылочная целостность RR → EV → DP | request_id/evidence_ids/derived_from/superseded_by + правило «EV-упоминания в тексте DP ⊆ evidence_ids» | CI: validate_research_artifacts.py (link-чек) |
| 3 | Quote grounding | citation.quote в схеме (optional v0.2, конвенция для новых первичных EV, required с v0.3) + механическая проверка verify_quotes.py (re-fetch, substring/difflib); ретро-прогон: fetch_fail 0/41, пойман реальный дефект атрибуции (EV-312) | CI: структурная конвенция (warning) + selftest; сетевой прогон — еженедельный watch |
| 4 | Freshness lifecycle | volatile→expires_at обязателен (CI, error); просроченный active — warning в CI, обработка — scheduled task research-freshness-sweep (Mon 9:00): stale/supersede/re-verify, лог в .research/watches/ | CI (структурно) + freshness_sweep.py --selftest; temporal — watch |
| 5 | Адверсариальное ревью writer≠judge | 6 DP прошли 2-раундовый цикл (needs_work→fix→approved), review-блок вносит координатор; анти-self-preference рубрика (мин. дефекты + опровергающее evidence) | история DP-102…DP-107 (review.notes) |
| 6 | Writer-preflight | research/writer-preflight.md, 16 пунктов из классов judge-находок; живой (пп. 15-16 добавлены из RR-007) | judge проверяет заявку прохождения попунктно |
| 7 | Research memory работает | memory_check обязателен в RR; переиспользование EV между запросами (EV-101 в DP-106); grep-протокол проверен 5/5 known-items (EV-312) | validate_research_artifacts (memory_check в схеме RR) |
| 8 | Decision-first выход | DP: decision_brief (однооконно), cost_of_recommendation, alternatives/risks/unknowns/proposed_validation с фальсифицируемыми порогами; outcome замыкает контур (3 accepted DP с outcome) | схема + DP-101…DP-107 |
| 9 | Процессные инварианты кодифицированы | research/README.md «Процессные инварианты» (координатор пишет review; 1 источник = 1 EV; self-evidence под спот-чек; негатив ≤ medium с квалификаторами; единый критерий к себе) | текст + соблюдение проверяется judge'ами |
| 10 | Экономика конвейера | EV-ready разведка + ev_scaffold.py (19 EV за 2 команды в RR-007); роутинг по workflow_hint (quick/comparison/deep) | README роутинг-таблица; ev_scaffold --selftest в CI |
| 11 | ≥2 домена обкатаны | technology (RR-001…006) + product (RR-007, с доменно-специфичными уроками в preflight) | артефакты .research/ |
| 12 | Инструменты самопроверки центра | стресс-тест собственного гайда интервью на синтетических персонах → v2 (гайд, лист, счётчик) | EXP-003/interviews, коммит 327f820 |

Отложено осознанно (не входит в v0.2): required-статус quote (v0.3), Watch beyond freshness
(конкурентные/технологические watches), contradiction detection как capability, калибровочный
леджер (ждёт ≥10 DP с outcome), установка .research/ в child-репозитории (v0.3).
