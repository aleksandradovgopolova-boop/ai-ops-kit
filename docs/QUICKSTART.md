# Quickstart — первый день с AI Ops Kit

Требования: python3 (3.10+) и pyyaml. Node.js нужен только для OpenSpec-опции
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

## 2. Первая фича

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
        run: git clone --depth 1 --branch v2.3.0 https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git /tmp/ai-ops-kit
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
