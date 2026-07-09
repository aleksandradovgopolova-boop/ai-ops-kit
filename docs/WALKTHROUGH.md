# Walkthrough — сквозной сценарий за 15 минут

Воспроизводимая демонстрация цикла «фича от идеи до вердикта» на пустом каталоге.
Сценарий повторяет первый боевой прогон кита (child-репозиторий, фича миграции
каталога на API-слой) в обезличенном виде. Все команды выполняются из клона кита;
`$KIT` — путь к нему, `$PROJ` — ваш тестовый каталог.

```bash
KIT=$(pwd)            # клон ai-ops-kit
PROJ=$(mktemp -d)     # «репозиторий продукта»
cd $PROJ
```

## Шаг 1. Завести фичу (lean-профиль — у нас прототип)

```bash
python3 $KIT/tools/generate_artifacts.py new features demo-migration "Каталог на API-слое" --profile lean
python3 $KIT/tools/generate_artifacts.py scaffold features/demo-migration --stage discovery
```

Появились `blueprint.yaml` (5 стадий вместо 11) и два скелета discovery.

## Шаг 2. Честность проверяется сразу

```bash
python3 $KIT/tools/run_report.py features/demo-migration
# -> ВЕРДИКТ: PROBLEM: «НЕЗАПОЛНЕННЫЕ СКЕЛЕТЫ достигнутых стадий»
```

Система не принимает созданный-но-пустой артефакт за работу. Заполните оба файла
по существу (какую проблему решаем, чем докажем) — хотя бы по абзацу:

```bash
cat >> features/demo-migration/discovery/problem-statement.md <<'TXT'
Каталог — последняя страница на legacy-фикстурах, мимо API-слоя: объекты не связаны
с реальными сущностями, действия не попадают в аудит, состояние не переживает
перезагрузку. Решено: e2e полного цикла зелёный, события каталога видны в аудите.
TXT
cat >> features/demo-migration/discovery/hypotheses.md <<'TXT'
| 1 | Мы верим, что каталог на API-слое сделает путь «добавил -> вижу после перезагрузки» сквозным; узнаем по e2e полного цикла | e2e | сценарий зелёный без оговорок | planned |
TXT
python3 $KIT/tools/run_report.py features/demo-migration
# -> PROBLEM ушёл; остался WARN про незаполненную ретроспективу — это нормально в начале
```

## Шаг 3. Двигаться по стадиям

```bash
python3 $KIT/tools/generate_artifacts.py scaffold features/demo-migration --stage definition
# заполните prd/feature.md и prd/user-stories.md, затем поднимите current_stage:
python3 - <<'EOF'
import yaml, pathlib
p = pathlib.Path("features/demo-migration/blueprint.yaml")
bp = yaml.safe_load(p.read_text())
bp["feature"]["current_stage"] = "definition"
p.write_text(yaml.safe_dump(bp, allow_unicode=True, sort_keys=False))
EOF
```

Правило на каждый шаг: артефакт достигнутой стадии — заполнен или
`status: declined` + `declined_reason`. И главное правило прогона: **blueprint
закрывается в том же PR, что и релиз кода** — race «код уехал, бумаги остались»
run_report ловит через knowledge graph (ребро delivered-by при ранней стадии).

## Шаг 4. Аналитика с кросс-проверкой

Заполните `analytics/tracking-plan.md` (таблица Events) и `analytics/dashboard-spec.md`
(Source events, Funnels). Согласованность проверяется механически:

```bash
python3 $KIT/validation/validate_cross_artifacts.py features/demo-migration
# событие в дашборде, не объявленное в tracking plan -> PROBLEM
```

## Шаг 5. Финал — вердикт и ретроспектива

Дойдя до релиза: заполните `retrospective/retrospective.md` (результат vs метрики
из discovery, уроки -> memory) и добейтесь:

```bash
python3 $KIT/validation/validate_feature_blueprint.py features/demo-migration
python3 $KIT/tools/run_report.py features/demo-migration
# -> ВЕРДИКТ: OK
```

## Что вы только что увидели

1. **Скелеты — детерминированные, содержание — ваше**: генератор никогда не
   перезаписывает, drift-детект отличает заполненное от пустышки.
2. **Отказ — легален, молчание — нет**: declined с причиной проходит, пропуск краснит.
3. **Один вердикт**: run_report собирает blueprint, покрытие, кросс-артефактную
   консистентность и knowledge graph в один exit-код для CI.

Реальный прогон этого сценария (с гейтами, ревью и knowledge graph) занял один день
и нашёл два дефекта процесса — оба теперь автоматически краснят CI. Продолжение:
[QUICKSTART.md](QUICKSTART.md) §4 — CI-джоб; [adoption-guide.md](adoption-guide.md) — роли.
