# Change Brief — доставляемая команда объёма проверки `verify-scope` (#1321, срез 2a)

## Результат

У разработчика в дочке появляется ДОСТАВЛЯЕМЫЙ локальный ответ на вопрос «какой объём проверки
нужен ИМЕННО этому изменению»: `./ai-ops verify-scope [stage] [--base origin/main] [--json]`. По
текущему diff (база + локальные правки) команда печатает решение tier/стадии — только документация
(skip) / затронутые тесты (affected|module) / полный обязательный набор (full) — человеческую
причину и, когда это осмысленно, точечный набор тестов. Полные обязательные проверки на слиянии и
выпуске не трогаются: это диагностика объёма, а не гейт.

Раньше прямой impact-вход был только у разработки самого кита
(`ai_ops_kit/devtools/impact_check_cli.py`): он не едет в дочку (installer `DEV_ONLY_PREFIXES`) и
тянет страж слотов хоста (`devtools/host_resource_cli`). Политика-ядро давно доставлена —
`gates/verification_tiers` (решение tier) и `context/repo_graph` (граф зависимостей) уже лежат в
`.ai/managed/` у дочек. Не хватало доставляемой точки входа; срез 2a её добавляет, переиспользуя
доставленное и не копируя политику.

## Затрагиваемые пути

- `ai_ops_kit/cli/verify_scope_cli.py` — новая команда (слой `cli`/entrypoints). Импортирует только
  доставляемые слои: `gates/verification_tiers`, `context/repo_graph`, `shared/project_detector`,
  `ui/presenter`. Ни одного импорта из `ai_ops_kit.devtools.*`.
- `ai_ops_kit/cli/ai_ops_cli.py` — объявление интента (`INTENTS`), `DIRECT_INTENTS`, регистрация
  обработчика.
- `tests/unit/test_verify_scope_cli.py` — поведение + layering-страж на уровне теста.
- Сверка объявленной поверхности: `tests/unit/test_ai_ops_cli.py` (`EXPECTED_INTENTS`),
  `tests/unit/test_human_actions_facade.py` (замок числа команд 38→39), `README.md`
  (`claim:commands-total` 38→39) и сгенерированная витрина `docs/capability-map.md` (перегенерирована
  `python3 -m ai_ops_kit.devtools.capability_inventory --write`). Это ручные tripwire-манифесты
  поверхности, которые по построению обновляются вместе с добавлением команды — не ослабление
  гейтов, а их штатное ведение.

## Инварианты

- **Аддитивно.** Не тронуты гейты, обязательные проверки, маркеры, пороги риска, покрытие и floors
  безопасности; ничего не отключено и не помечено skip/xfail. Финальные гейты те же.
- **Layering.** `cli` — entrypoints (верхний слой), импорт из `gates`/`context`/`shared`/`ui` вниз
  разрешён; импорта из `devtools` нет. Границу держит `validate_layering`
  (`no-product-depends-on-devtools`) и `test_module_does_not_import_devtools`.
- **Delivery closure.** Модуль живёт в доставляемом наборе (`cli` не исключён из поставки; из
  `ai_ops_kit/cli/` dev-only только `entry.py`) и импортирует лишь доставляемые слои, поэтому
  самодостаточность движка (`validation/validate_standalone_engine`, `tests/unit/test_installer.py`)
  не нарушена.
- **Fail-closed.** Неизвестное влияние ⇒ консервативный ответ (full / «гони обязательный набор»),
  никогда не тихо-пустой или неверный выбор.

## Failure modes

1. **git не отвечает** (не репозиторий, нет HEAD) → `changed_paths` возвращает `None` → команда
   отвечает `tier=full`, `degrade_reason=git-unavailable`, а НЕ «изменений нет».
2. **Стек не Python / монорепо** → Python-граф целей не даёт → консервативный `tier=full`,
   `degrade_reason=non-python-stack`, причина названа явно (см. «Не входит»).
3. **Неполный граф** (динамические/нечитаемые входы) → `verification_tiers` сам отдаёт полный
   fallback; команда помечает `degrade_reason=incomplete-graph`.
4. **Определение стека упало** → перехвачено, `stacks=[]`, объём считается по diff/риску как обычно.

## Доказательство

- `tests/unit/test_verify_scope_cli.py` — 9 кейсов: docs-only⇒skip, пустой diff⇒skip, Python-правка⇒
  affected-или-консервативно, не-git⇒full/git-unavailable, JS/TS⇒full/non-python-stack, AST-страж
  «нет импорта devtools», wiring (объявлен/исполняем/доходит до обработчика), запуск пакетным входом
  как у дочки.
- `tests/contracts/test_direct_intents_match_handler.py` — интент доходит до обработчика.
- `validate_layering`, `validate_standalone_engine`, `tests/unit/test_installer.py` — границы и
  delivery-closure.

## Не входит (честная граница)

`context/repo_graph` строит граф из **Python-AST**. Для JS/TS и монорепо-дочек Python-граф НЕ
произведёт JS-тест-цели — поэтому доставляемая, язык-независимая ценность здесь это РЕШЕНИЕ
tier/стадии (docs-only vs backend vs cross-cutting ⇒ какой обязательный набор и на каком гейте).
Глубокий per-test Python-выбор остаётся спецификой кита. Команда это называет прямо (`tier` +
«точечный выбор тестов для этого стека недоступен ⇒ консервативный набор») и НЕ выдаёт за наличие
JS-тест-селекции. Дочки на не-Python стеке per-test ускорения кита не получают.
