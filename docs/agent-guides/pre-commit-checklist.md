# Перед коммитом — полный список проверок

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS.

```bash
python3 tools/pr_open.py --selftest
python3 tools/gate_result_v2.py --selftest
python3 tools/branch_policy.py --selftest
python3 validation/validate_agents_checklist.py --selftest
python3 installer/ai_ops.py --selftest
python3 validation/validate_research_artifacts.py --selftest
python3 .research/tools/verify_quotes.py --selftest
python3 .research/tools/freshness_sweep.py --selftest
python3 .research/tools/ev_scaffold.py --selftest
python3 -m pytest tests/contracts/ -v --tb=short --no-cov
python3 -m pytest tests/contracts/ -v --tb=short
```

## Что переехало в pytest и почему здесь этого нет

Все 70 валидаторов, все перенесённые селфтесты и прогоны на примерах-фикстурах запускаются из
pytest: `test_validator_runtime_contract.py` (каждый валидатор из копии репозитория),
`test_<module>_selftest.py` (перенесённые тела) и `test_example_fixtures.py` (валидатор + его
пример). Дублировать те же команды здесь значило бы гонять одно и то же дважды — из-за этого
полный контур занимал девять минут вместо четырёх с половиной.

Ниже осталось только то, что pytest не покрывает: семь модулей с неперенесёнными селфтестами,
инструменты .research и контрактные слои.

## Валидаторы: почему их прогонов здесь больше нет

Все 70 валидаторов запускаются из pytest — `tests/unit/test_validator_runtime_contract.py`
прогоняет каждый ИЗ КОПИИ репозитория (standalone обязан быть зелёным, требующий артефакт —
отказать на пустом вызове), а перенесённые селфтесты живут в `tests/unit/test_<validator>_selftest.py`.
Дублировать те же команды здесь значит гонять одно и то же дважды — ровно то, из-за чего полный
контур занимал девять минут.

## Не входит в чеклист — объявленные исключения

Валидатор, которого нет в списке выше, обязан быть здесь с причиной. Полноту проверяет
`tests/unit/test_checklist_completeness.py`: молчаливо выпасть из чеклиста нельзя, иначе список
и реальный набор валидаторов расходятся — этот класс дрейфа уже дважды ловили на `checks_count`.

- `validation/validate_ai_ops_child.py` — проверяет установку кита в **child-репозиторий**
  (`.ai-ops.yaml`, зоны `.ai/*`, целостность managed-слоя). В репозитории самого кита проверять
  нечего; запускается в child-репо и покрыт `tests/unit/test_installer.py`.
