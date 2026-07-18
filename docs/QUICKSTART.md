# Quickstart — первый день с AI Ops Kit

Требования: python3 (3.9+) и pyyaml. Node.js нужен только для OpenSpec-опции
(включена по умолчанию, выключается `openspec.enabled: false` в `.ai-ops.yaml`).

## 1. Установка в ваш репозиторий (child)

```bash
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
cd <ваш-репозиторий>
python3 <путь>/ai-ops-kit/installer/ai_ops.py init .
python3 <путь>/ai-ops-kit/installer/ai_ops.py doctor
```

Появятся: `.ai/` (managed-слой с реестрами и контрактами; не редактируйте — правки
кладите в `.ai/custom/`), `.ai-ops.yaml` (отредактируйте `project.name` и providers)
и `.github/workflows/ai-ops-update.yml` (ежедневный PR с обновлением кита).

## 1a. Задача одной командой (intent UX, v2.117)

Движок управляется **намерениями**, а не флагами — не нужно помнить
`--engine`/`--author`/`--review`/`--sandbox`. Один вход:

```bash
python3 .ai/managed/tools/ai_ops_cli.py <intent> "<задача>" . [--feature NAME] [--execute]
```

Типовой поток продуктовой задачи:

```bash
# 1. один раз на репозиторий — определить стек и команды
python3 .ai/managed/tools/ai_ops_cli.py onboard .

# 2. спецификация нужной глубины (создаёт features/<id>/spec.yaml — заполните разделы)
python3 .ai/managed/tools/ai_ops_cli.py specify "добавить фильтр заказов по статусу" . --feature orders-filter

# 3. план без правок кода (RunPlan + контекст + WorkPackages)
python3 .ai/managed/tools/ai_ops_cli.py plan "добавить фильтр заказов по статусу" . --feature orders-filter

# 4. исполнить (preflight → tool-loop → commit → evidence → гейты → draft PR)
python3 .ai/managed/tools/ai_ops_cli.py run "добавить фильтр заказов по статусу" . --feature orders-filter --execute

# 5. независимый read-only ревью действующей ветки (writer ≠ judge)
python3 .ai/managed/tools/ai_ops_cli.py review "проверь ветку" . --feature orders-filter --provider openai-compatible --model deepseek-chat
```

Другие намерения: `new` (каркас фичи), `discuss` (черновик discovery), `status` (активная работа),
`health` (Product Health), `resume … --execute [--force]` (продолжить прерванную работу поверх коммита,
**не рестарт**), `preview <intent> …` (показать план без выполнения).

**Preflight Truth (v2.115):** перед запуском модели проверяются classification → контекст → достаточность
спеки → атомарность/декомпозиция → бюджет → human-approvals. Если спека неполна или нужен человек
(secret-boundary/деструктив/новая зависимость) — **модель не запускается, правок и коммита нет**. Одобрение —
настоящий `ApprovalRecord` (`tools/approvals.py record …`: автор/scope/причина), не флаг.

Крупную неатомарную задачу можно исполнить **по WorkPackages последовательно** (пакет→commit→
evidence→gates→следующий): добавьте `--sequential`.

## 2. Первая фича

Задача запускается каноническим входом **`ai-run`** (в раннтайме — `/ai-run`): опиши задачу
словами → классификация/маршрут → RunPlan → WorkItem → исполнение → отчёт. `/ai-start-task`
остаётся совместимым алиасом того же потока. Артефакты фичи готовятся так:

```bash
# прототип/MVP — lean-профиль (5 стадий, 10 артефактов);
# зрелый продукт — без --profile (full: 11 стадий)
python3 <kit>/tools/generate_artifacts.py new features my-feature "Моя фича" --profile lean
python3 <kit>/tools/generate_artifacts.py scaffold features/my-feature --stage discovery
```

Заполните `discovery/problem-statement.md` и `discovery/hypotheses.md` по существу
(шаблон подсказывает разделы). Дальше двигайтесь по стадиям: `scaffold --stage <стадия>`
→ заполнить → поднять `feature.current_stage`.

Два железных правила:
- каждый артефакт достигнутой стадии **заполнен или declined с причиной** —
  молчаливых пропусков нет;
- blueprint закрывается **в том же PR, что и релиз кода** — иначе «реальность
  обогнала blueprint» (см. типовые ошибки).

## 3. Проверка «хорошо или плохо» — одной командой

```bash
python3 <kit>/tools/run_report.py features/my-feature --graph knowledge/graph.yaml
```

Вердикт OK / WARN / PROBLEM: валидность blueprint, покрытие стадий, незаполненные
скелеты, согласованность tracking plan ↔ dashboard-spec, сверка с knowledge graph,
напоминание о ретроспективе. PROBLEM = exit 1 — ставьте в CI.

## 3a. История прогонов и метрики эффекта (v2.5)

Перед коммитом PR запускайте отчёт с записью среза:

```bash
python3 <kit>/tools/run_report.py features/my-feature --graph knowledge/graph.yaml --record
```

Срез (дата, вердикт, стадия, покрытие) допишется в `.ai/project/report-history/<фича>.jsonl`
и закоммитится вместе с PR. По накопленной истории считаются метрики эффекта:

```bash
python3 <kit>/tools/effect_metrics.py    # PROBLEM-rate, динамика покрытия, дни до retrospective
```

Инструмент честен: пока нет 3+ фич с 3+ срезами, он явно пишет «baseline не готов».

## 3b. Исполнение движком без клона кита (v2.82)

После `ai-ops init` движок лежит **внутри репозитория** в `.ai/managed/` — клонировать
parent-кит для `ai-ops run` не нужно:

```bash
python3 .ai/managed/tools/ai_ops_run.py run "почини падающий тест даты" . \
  --engine pipeline --provider openai-compatible --model deepseek-chat \
  --execute --baseline-diff --sandbox --json
```

`--sandbox` (v2.81) ограничивает shell модели allowlist'ом dev-инструментов и запрещает `git push`
из петли. ВАЖНО (v2.93, честно): `--sandbox` **НЕ отключает сеть** — `sandbox_policy()` по умолчанию
`allow_network=True` (движку нужен egress к API модели и реестрам npm/pip); произвольные сетевые
бинарники (curl/wget) не в allowlist, но пакет-менеджеры сеть используют. Настоящий сетевой контроль
даёт контейнер (`AI_OPS_NETWORK=none`) или egress-allowlist прокси — см. `docs/container-isolation.md`.
`--json` даёт машиночитаемый отчёт (прогресс идёт в stderr). Проверить,
что движок установлен целиком: `python3 .ai/managed/validation/validate_standalone_engine.py .`
или `ai-ops doctor` (строка «движок (standalone)»).

Для ENGINEERING/PRODUCT-задач добавьте `--review` (v2.83) и `--author` (v2.86): `--review` даёт
независимый read-only вердикт по ai-review гейтам (code_review/ux_review/...) — writer ≠ judge;
`--author` производит артефакты requirements/plan и **specification** (OpenSpec-изменение) и
подтверждает их детерминированно: requirements/plan — по форме; specification — рендерит OpenSpec-
markdown и валидирует настоящим `openspec validate --strict` (нужен `npm i -g @fission-ai/openspec`).
Закрывает гейты requirements/plan_readiness/specification. Честно: эти гейты детерминированные,
поэтому **качество** требований судит **человек**, а не in-loop `--review` (ревьюер закрывает только
ai-review гейты вроде code_review/ux_review). Нет `openspec` CLI или битый артефакт → гейт остаётся
блокирующим; human-approval-гейты тоже — движок не выдаёт ложный «готово».

Новые флаги пути исполнения (v2.109–2.117):
- `--resume [--force]` — продолжить прерванную работу того же `--feature` **поверх коммита** (не
  рестарт): переиспользует ветку/worktree, подаёт состояние из RunHandoff в prompt. Устаревшая база
  (main ушёл вперёд) → блок без `--force` (не продолжаем молча на старом evidence).
- `--sequential` — неатомарную задачу исполнить по WorkPackages последовательно; у каждого пакета свой
  коммит/SHA/гейты/точка resume; зависимый пакет не стартует без подтверждённого предыдущего; блок
  пакета останавливает последовательность. Отчёты — `features/<id>/work-packages/<pkg>/report.json`.
- **Preflight**: неполная `features/<id>/spec.yaml`, превышение context-budget, неподтверждённая
  декомпозиция или отсутствие нужного `ApprovalRecord` → прогон останавливается **до** tool-loop
  (`status=blocked`, коммита нет). Одобрение создаётся:
  `python3 .ai/managed/tools/approvals.py record . <feature> --approval secrets --by you@x --scope config --reason "…"`.

Граница: child-CI (раздел 4) по-прежнему клонирует kit по тегу — это пин версии для проверки
установки, отдельный от пути исполнения движка.

## 4. CI child-репозитория (проверенный набор)

```yaml
  ai-ops:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install pyyaml
      - name: Clone ai-ops-kit (пин на installed_version из .ai-ops.yaml)
        run: |
          VER=$(python3 -c "import yaml; print(yaml.safe_load(open('.ai-ops.yaml'))['parent']['installed_version'])")
          git clone --depth 1 --branch "v$VER" https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git /tmp/ai-ops-kit
      - run: python3 /tmp/ai-ops-kit/installer/ai_ops.py validate
      - run: python3 /tmp/ai-ops-kit/installer/ai_ops.py doctor
      - run: python3 /tmp/ai-ops-kit/validation/validate_knowledge_graph.py knowledge/graph.yaml
      - name: Blueprint + оценка прогона (все фичи)
        run: |
          for f in features/*/blueprint.yaml; do
            d="$(dirname "$f")"
            python3 /tmp/ai-ops-kit/validation/validate_feature_blueprint.py "$d"
            python3 /tmp/ai-ops-kit/tools/run_report.py "$d" --graph knowledge/graph.yaml
          done
```

## 5. Обновления

`ai-ops-update.yml` раз в день сам откроет PR с новой версией кита (managed-слой
обновится, `.ai/project/` и `.ai/custom/` не тронет). Вручную:
`python3 <kit>/installer/ai_ops.py update`.

## Типовые ошибки (все — из реальных прогонов)

| Сообщение | Причина и что делать |
|---|---|
| `feature.status 'in_progress' вне ['in-progress', ...]` | Статусы пишутся через дефис: `in-progress` |
| `реальность обогнала blueprint: ... delivered-by, а current_stage=...` | Код выпущен, а blueprint не закрыт. Дозаполните/declined стадии и поднимите current_stage — в том же PR, что и релиз |
| `НЕЗАПОЛНЕННЫЕ СКЕЛЕТЫ достигнутых стадий` | Артефакт создан scaffold'ом, но не заполнен. Заполните по существу или пометьте `status: declined` c `declined_reason` |
| `declined без declined_reason` | Отказ от артефакта должен быть обоснован — одна честная строка почему |
| `стадия '...' достигнута (profile=full), но артефактов для неё нет` | Либо добавьте артефакты стадии, либо фиче место в lean-профиле (`feature.profile: lean`) |
| `dashboard-spec использует событие '...', не объявленное в tracking plan` | Кросс-артефактное расхождение: объявите событие в tracking plan или уберите из дашборда |
| `Обнаружена прямая правка managed-слоя; обновление остановлено` | Не редактируйте `.ai/managed/` — перенесите правку в `.ai/custom/` (overlay) и повторите update |
| `openspec CLI: — (не найден...)` в doctor | Установите `npm i -g @fission-ai/openspec` или выключите `openspec.enabled: false` |

Дальше: воспроизводимый сквозной сценарий — [WALKTHROUGH.md](WALKTHROUGH.md);
кто чем пользуется в команде — [adoption-guide.md](adoption-guide.md).
