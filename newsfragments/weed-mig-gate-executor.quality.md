Прополка тестов gate_executor (движок quality-гейтов, критичный: потеря проверки = гейт можно
обойти). Монолитный `test_gate_executor_selftest.py` — одна `@pytest.mark.slow` мега-функция с
десятками проверок через самописный `expect()` — заменяется гранулярными `@pytest.mark.unit`
тестами: одно поведение = один тест с ясным именем и настоящей проверкой значения.

Перенесены ВСЕ поведения монолита, которых не было в гранулярном файле с проверкой значения:
классификация security по сигналам (security_surface_changed / secret_boundary / destructive →
human-approval, None → нет); точные наборы `unmet_gates` (а не «непусто»); невыполненный
блокирующий гейт → `fail`, не `warn`; gate_ids-override трекового гейта; «умное ослабление» через
`not_applicable` с записью освобождения в warnings; отклонение бездоказательного pass; реальное
исполнение детерминированного валидатора против символического (None); `required_when` гейта
architecture_review; freshness-гейт (протух / свеж / нет контекста); forbidden-override на уровне
workflow остаётся blocked; соответствие gate-result схеме; резолв всех workflow-контрактов;
`validate_evidence` и `validate_evidence_schemas` по форме; сбор evidence из markdown и приоритет
структурного `.reviewer.json` над ним.

Монолит НЕ снят: его функция `test_gate_executor_selftest` названа в `-k`-селекторе
`.github/workflows/pr-smoke.yml` (не-тестовый файл), а правка CI вне охвата этой работы
(только `tests/` и `newsfragments/`). Снятие силами отдельной работы, синхронно с обновлением
smoke-селектора, чтобы гейт-движок не выпал из PR-smoke слоя молча.
