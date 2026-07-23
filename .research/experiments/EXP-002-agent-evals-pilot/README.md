# EXP-002 — пилот DP-105: formats-first + мета-оценка судей

Проверка рекомендации [DP-105](../../decisions/DP-105.yaml). Итоги 2026-07-23 — в EV-335.

- `cases/code-reviewer.cases.yaml` — кейсы из evaluations/agents/code-reviewer.md в
  promptfoo-стиле (vars+assert; Forbidden → llm-rubric-инверсии + механические asserts).
  Ждёт спот-чека человеком: семантика не потеряна?
- `runner.py` — минимальный stdlib-раннер (fixture-режим outputs/<i>.md; механические
  asserts исполняет, llm-rubric выгружает судье в rubric_checklist.yaml). `--selftest`.
- `seeded/diffs.yaml` + `seeded/truth.yaml` — golden-set: 10 мини-диффов (6 seeded
  defects по зонам ревьюера, 4 чистых). Судье truth не показывать.
- `kappa.py` — recall/precision/raw agreement/Cohen's kappa. `--selftest`.
- `golden.yaml` — свод truth + вердикты слепого судьи-агента.

Результат: recall 0.83, precision 1.00, agreement 0.90, **kappa 0.80** (n=10 — сигнал,
не бенчмарк). Промах d10 — урок дизайна golden-set: дефект должен быть однозначен
относительно политики, выданной судье (политика новых зависимостей судье не выдавалась).

Не сделано: npx promptfoo прогон (нужен Node на dev-машине); расширение
validate_agent_evals.py до «md ИЛИ yaml» (шаг 4 DP-105 — правка CI кита, по решению Sasha).
