# Чеклист обкатки: как метрики закрываются сами

Кит умеет сам копить статистику эффекта. Чтобы North Star (`autonomous_reviewable_pr_rate`)
и baseline начали считаться — не нужно ничего вести вручную, достаточно гонять реальные
задачи **через кит**. Держи этот чеклист под рукой в каждой сессии.

## Разово: держать кит свежим

```bash
rm -rf /tmp/ai-ops-kit && git clone --depth 1 <parent.source> /tmp/ai-ops-kit \
  && python3 /tmp/ai-ops-kit/installer/ai_ops.py update
git add -A && git commit -m "chore: AI Ops Kit -> <версия>" && git push
```
`<parent.source>` — из `.ai-ops.yaml` (`python3 -c "import yaml;print(yaml.safe_load(open('.ai-ops.yaml'))['parent']['source'])"`).

## На каждой задаче

1. **Запуск — через канонический вход, ПРИВЯЗАННЫЙ к именованной фиче.** Опиши задачу словами:
   `/ai-run` (или `/ai-start-task`). Важно: веди задачу на **именованной** фиче
   (`ai_ops_run.py run "<задача>" . --feature <имя-фичи>`), а не на ad-hoc `wi-<hash>` — иначе
   срез истории упадёт на новую фичу с 1 срезом и **не сдвинет baseline** (finding обкатки).
2. **Довести по стадиям:** `plan → implement → verify → finish`.
3. **В `finish` записать срез явно:** `tools/run_report.py features/<имя-фичи> --record`.
4. **Закрыть blueprint в том же PR, что и код** — иначе «реальность обогнала blueprint».

> **Честно про автозапись (по runtime):**
> - **generic-orchestrator** — оркестратор кита реально прогоняет стадии и пишет срезы сам;
> - **claude-code** (основной рантайм) — WorkItem/RunPlan создаются контроллером, но стадии
>   исполняет рантайм; срез в историю пишется, когда рантайм на стадии `finish` выполняет
>   `run_report.py --record` (шаг 3). То есть в claude-code «автозапись» = рантайм честно
>   исполняет процедуру `finish`, а не магия. Ad-hoc `wi-<hash>` baseline не двигает.

## Как проверить прогресс

```bash
python3 /tmp/ai-ops-kit/tools/effect_metrics.py .ai/project/report-history
```
- `baseline_ready: true` появляется при **3 фичах × ≥3 срезах** — порог, после которого
  baseline и North Star считаются сами.
- До порога — это нормально: просто продолжай вести задачи через `/ai-run`.

## Что закрывается попутно

- **North Star / baseline** — из накопленной истории (пункты выше).
- **Golden-repo / полный GitHub-lifecycle** — как только одна фича пройдёт весь путь до
  **мержа PR**, это и есть первый живой lifecycle-пример.
- **Interaction-log** — заполняется, когда подключён runtime-binding (сбор взаимодействий);
  без него история стадий всё равно копится.

## Простыми словами

От тебя: вести следующие задачи **через `/ai-run --feature <имя>`** (не ad-hoc) и на стадии
`finish` дать `run_report.py --record`. Через ~3 доведённые именованные фичи (×3 среза) baseline
и North Star начинают закрываться. В generic-orchestrator это происходит само; в claude-code —
когда рантайм честно исполняет `finish` (не полагайся на «магию»).
