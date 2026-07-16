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

1. **Запуск — через канонический вход.** Опиши задачу словами: `/ai-run` (или `/ai-start-task` —
   тот же поток). Он сам создаёт WorkItem, RunPlan, регистрирует работу и **пишет срез в
   историю** — вручную записывать не нужно.
2. **Довести по стадиям:** `plan → implement → verify → finish`. Автозапись срезов вшита в
   стадии — история копится в `.ai/project/report-history/`.
3. **Закрыть blueprint в том же PR, что и код** — иначе «реальность обогнала blueprint».

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

От тебя: обновиться и вести следующие задачи **через `/ai-run`**, а не в обход. Дальше кит
сам пишет историю → через ~3 доведённые фичи метрики начинают закрываться.
