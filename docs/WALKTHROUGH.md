# Walkthrough — от обычной фразы до вердикта

Сквозной сценарий реального пути пользователя: вы описываете задачу **обычными
словами**, кит сам выбирает маршрут, проводит стадии и **не считает работу
сделанной, пока блокирующие проверки не доказаны**. В Claude Code это выглядит как
«напишите задачу и вызовите `/ai-start-task`»; ниже — та же механика через CLI, чтобы
всё было воспроизводимо. `$KIT` — клон кита, `$PROJ` — тестовый проект.

```bash
KIT=$(pwd)            # клон ai-ops-kit
PROJ=$(mktemp -d)     # «репозиторий продукта»
```

## Шаг 1. Установить кит в проект

```bash
python3 $KIT/installer/ai_ops.py init $PROJ
cd $PROJ
```

Появились: `.ai/managed/` с **полными контрактами** (тела агентов, правила, шаблоны,
реестры), `.claude/commands/` с командой-точкой входа **`ai-start-task`** и командами
каждого workflow, `.ai-ops.yaml` с реальным `parent.source` (из git remote, без
кредов). Claude Code видит `/ai-start-task` сразу — маршрут выбирать руками не нужно.

## Шаг 2. Обычная фраза → маршрут выбирается сам

В Claude Code вы просто пишете «добавить фильтр по статусу в списке заказов» и
вызываете `/ai-start-task`. Под капотом работает движок маршрутизации по реестрам в
`.ai/managed/` — вот его решение:

```bash
python3 $KIT/validation/ai_route.py '{"task_type":"feature","risk":"low","reasoning_complexity":"high","confidentiality":"internal","available_providers":["anthropic"],"available_runtimes":["claude-code"]}'
# -> workflow: ENGINEERING, human_approval_required: false, с обоснованием в reasons
```

**Критический риск переопределяет тип задачи** и требует ручного одобрения:

```bash
python3 $KIT/validation/ai_route.py '{"task_type":"feature","risk":"critical","confidentiality":"internal","available_providers":["anthropic"],"available_runtimes":["claude-code"]}'
# -> workflow: CRITICAL, human_approval_required: true
#    reason: "critical risk overrides declared task_type"
```

## Шаг 3. Прогон workflow — гейты реально блокируют

```bash
python3 $KIT/tools/orchestrator.py run QUICK "поправить опечатку в README" $PROJ
# -> BLOCKED: 4 стадии пройдены, но блокирующие гейты не выполнены:
#    intake_completeness, implementation_verification
cat $PROJ/.ai/runtime/orchestrator/quick/GateReport.json   # машиночитаемый отчёт
```

Оркестратор проводит стадии с изоляцией ролей (writer ≠ judge), но **не ставит
`done`, пока блокирующие гейты не доказаны**. Это и есть замкнутый контур — раньше
задача помечалась готовой при любом ответе.

## Шаг 4. Evidence снимает блок — но бездоказательный pass запрещён

Доказательства подаются файлом (по `schemas/gate-evidence.schema.json`) или
собираются из вердиктов reviewer-стадий (`--collect-evidence`):

```bash
cat > /tmp/ev.json <<'JSON'
{"intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
 "implementation_verification": {"status": "pass",
   "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]}}
JSON
python3 $KIT/tools/orchestrator.py run QUICK "поправить опечатку" $PROJ --fresh --evidence /tmp/ev.json
# -> OK: workflow QUICK завершён; все блокирующие гейты выполнены
```

Голый `{"status": "pass"}` без `provided` executor **отклонит** — доказательство
обязательно (`required_evidence` из `quality/gates.yaml` должен быть подтверждён).

## Шаг 5. CRITICAL — строгий путь с независимым ревью и одобрением

```bash
python3 $KIT/tools/gate_executor.py CRITICAL
# гейты: intake_completeness, plan_readiness, implementation_verification, security, code_review
# security   -> human-approval (обязательное ручное одобрение)
# code_review -> ai-review (независимый judge)
# без evidence/одобрения -> blocked
```

CRITICAL — отдельный зарегистрированный workflow с independent `security-review`,
`code-review` и стадией one-way-door (решение за человеком).

## Что вы только что увидели

1. **Обычная фраза → маршрут сам**: классификация и routing по реестрам, а не ручной
   выбор команды; `critical` переопределяет тип + требует human approval.
2. **Контур замкнут**: оркестратор проводит стадии, но `done` только при доказанных
   блокирующих гейтах; иначе `blocked` со списком незакрытых гейтов.
3. **Доказательства, а не слова**: evidence валидируется по схеме, бездоказательный
   `pass` отклоняется, вердикты reviewer-стадий можно собрать автоматически.

---

## Часть B. Продуктовый blueprint (отдельный слой) — фича от идеи до вердикта

Для продуктовых фич кит ведёт машиночитаемый blueprint (проблема → определение →
аналитика → релиз → ретроспектива) с одним CI-вердиктом. Кратко:

```bash
python3 $KIT/tools/generate_artifacts.py new features demo "Каталог на API-слое" --profile lean
python3 $KIT/tools/generate_artifacts.py scaffold features/demo --stage discovery
python3 $KIT/tools/run_report.py features/demo
# -> PROBLEM: незаполненные скелеты (созданный-но-пустой артефакт не считается работой)
```

Заполните discovery по существу (какую проблему решаем, чем докажем), двигайтесь по
стадиям (артефакт достигнутой стадии — заполнен **или** `status: declined` + причина),
и добейтесь единого вердикта:

```bash
python3 $KIT/validation/validate_cross_artifacts.py features/demo   # событие дашборда без tracking plan -> PROBLEM
python3 $KIT/validation/validate_feature_blueprint.py features/demo
python3 $KIT/tools/run_report.py features/demo                      # -> ВЕРДИКТ: OK
```

Ключевые инварианты слоя: скелеты детерминированные — содержание ваше (drift-детект
отличает заполненное от пустышки); отказ легален, молчание — нет; blueprint
закрывается в том же PR, что и релиз кода (race «код уехал, бумаги остались» ловит
run_report через knowledge graph).

Продолжение: [QUICKSTART.md](QUICKSTART.md) §4 — CI-джоб; [adoption-guide.md](adoption-guide.md) — роли.
