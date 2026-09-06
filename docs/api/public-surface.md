# Публичная поверхность AI Ops Kit

**Зачем этот документ.** До него границы не существовало. Не существовало, значит, и определения
breaking change: любая правка могла оказаться ломающей, и ни одна не была ломающей наверняка. Канал
`stable` при этом уже обещал дочкам совместимость — обещал ничем не подкреплённое.

Документ отвечает на один вопрос: **на что дочка вправе опираться, а на что нет**. Четыре уровня,
и у каждого своя цена изменения:

| Уровень | Что это | Что можно менять |
|---|---|---|
| `stable` | Контракт с дочкой. Ломать — только major, и только с окном вывода | Аддитивно: новый интент, необязательное поле, новый код возврата ПОСЛЕ объявления здесь |
| `experimental` | Работает, но форма ещё меняется. Дочка вправе пользоваться, зная это | Свободно, с записью в CHANGELOG |
| `internal` | Внутренности движка. Импортировать снаружи нельзя — совместимость не обещана вовсе | Свободно |
| `deprecated` | Ещё работает, но уже уходит. Список вправе только сокращаться | Только удалять |

**Что считается breaking change и каково окно вывода — в [AGENTS.md](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/AGENTS.md), раздел
«Публичная граница и breaking change».** Здесь — только перепись поверхностей.

## Как этот документ не расходится с кодом

Блок ниже — не иллюстрация, а **сама декларация**: его читает
[`tests/contracts/test_public_surface.py`](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/tests/contracts/test_public_surface.py) и сверяет с
реальностью. Появился интент, которого здесь нет, — тест красный. Исчез объявленный — красный. В
`stable`-схему добавили обязательное поле — красный, потому что это и есть breaking change, и он
обязан быть решением, а не побочным эффектом.

Правило простое: **правят декларацию, а не тест.** Тест не знает, что «правильно», — он знает
только, совпадает ли объявленное с тем, что есть.

```yaml
schema_version: 1
kind: ai-ops-public-surface

stable:
  # Интенты движка (`./ai-ops <интент>`) — ai_ops_kit/cli/ai_ops_cli.py -> INTENTS.
  cli_intents:
    - new
    - onboard
    - discuss
    - specify
    - plan
    - run
    - do
    - advise
    - resume
    - review
    - status
    - health
    - session
    # Диагностика установки СИЛАМИ ДОЧКИ (добавлен при сведении лент 20.08.2026). Полный `doctor`
    # живёт в установщике, а он в поставку не едет — в дочке без клона кита команда отвечала
    # «исходник рядом не найден». Обёртка дочки ведёт `doctor` в движок, полную проверку — как
    # `kit-doctor`, по образцу `status`/`kit-status`.
    - doctor
    - next
    - model
    - bootstrap
  # Префикс сухого прогона: `./ai-ops preview <интент>`.
  cli_intent_prefixes:
    - preview
  # Команды самого кита (`./ai-ops <команда>`) — installer/ai_ops.py -> _dispatch.
  kit_commands:
    - init
    - update
    - diff
    - doctor
    - validate
    - migrate
    - verify-capabilities
    - selftest
    - delivery-proof
    - usage
    - audit
    - session
    - subsession
    - engops
    - method
    - status
    # Зрелость UI-evidence (Storybook). Раньше звалась `onboard` — то же имя носит интент движка
    # «определить стек» (`./ai-ops onboard`), и обёртка ведёт `onboard` именно в него; чтобы одно имя
    # не значило два разных действия, команда установщика переименована в `ui-status`.
    - ui-status
  # Коды возврата интентов движка. Смысл кода — часть контракта: по нему CI дочки решает,
  # останавливать ли конвейер. Изменить смысл существующего кода = breaking change.
  exit_codes:
    0: "сделано и готово: работа исполнена, проверки сошлись, доставка (если запрошена) состоялась"
    1: "исполнено, но не готово: правки есть, а готовности нет — или доставка не удалась"
    2: "не исполнено: путь блокирован гейтом, отказом, потолком траты или ошибкой разбора"
  # Схемы контрактов. Список обязательных полей — снимок: его расхождение с файлом схемы и есть
  # сигнал breaking change (новое обязательное поле ломает существующие документы дочки).
  schemas:
    workitem: [schema_version, kind, id, workflow, paths, status]
    gate-result: [schema_version, gate, status, blocking, owner, review_mode]
    run-plan: [schema_version, kind, workitem_id, base_workflow, required_tracks, gates]
    provenance: [schema_version, package, source, installed_version, managed_root]
    update-result: [schema_version, command, status, human_approval_required]
    child-config: [schema_version, kind, parent, presets, adapters, providers]
  # Раскладка `.ai/` в дочке. Смысл каталога — контракт: `.ai/project/` и `.ai/custom/` кит при
  # обновлении не трогает, `.ai/managed/` перезаписывает целиком.
  ai_layout:
    .ai/managed/: "поставка кита; перезаписывается обновлением целиком, править нельзя"
    .ai/project/: "артефакты продукта дочки; кит не трогает"
    .ai/custom/: "оверлей владельца поверх поставки; кит не трогает"
    .ai/runtime/: "рабочее состояние прогона; в .gitignore"
    .ai/worktrees/: "рабочие деревья параллельных прогонов; в .gitignore"
  # Артефакты, которые дочка читает машиной.
  artifacts:
    run-report.json: "итог прогона: overall_status, ready_for_pr, checks, gates, delivery"
    DeliveryReceipt: "подтверждение доставки: status, sha_verified, checks_verified, merged"

experimental:
  # Интент канала наблюдений дочка->кит: форма улик ещё меняется.
  # roadmap/delivery (лента 4, Фаза 3): подключены командами CLI и работают, но форма ещё
  # устаканивается — delivery читает backlog по контракту ленты 3, который сводится, а вывод
  # roadmap/delivery ещё может измениться. Дочка вправе пользоваться, зная это.
  cli_intents:
    - feedback
    - roadmap
    - delivery
    # Backlog Intelligence (Фаза 2): `backlog classify|dedup|prioritize|graph` над GitHub Issues
    # дочки. Форма вывода и набор атрибутов ещё уточняются — дочка не должна на них опираться.
    - backlog
    # Product Contract (срез 1): `contract` — единый объект продукта поверх подсистем
    # (идентичность/стандарт/артефакты/контуры/здоровье) + вердикт. Агрегирует существующее, ничего
    # не пишет. Форма объекта и вердикта ещё уточняется; health пока впрыскивается отдельно (not_computed
    # без него). Дочка вправе смотреть, но не строить на форме — она устаканивается следующими срезами.
    - contract
    # Product Contract (срез 2): `products` — сводный флит-вид по реестру продуктов (products.yaml /
    # $AI_OPS_PRODUCTS). Реестр флота — операторское состояние, НЕ часть стандарта, поэтому не в
    # registry/ кита. Только чтение; форма реестра и вывода ещё уточняется.
    - products
    # Фаза 4 (закрытие острова): `team` — статус команды (health×3+риски+блокеры+задачи+milestone);
    # `governance` — активная политика автономии + журнал решений AI + переопределения человека.
    # Оба ТОЛЬКО ЧТЕНИЕ (enforcement policy_engine не подключён — отдельное решение). Форма ещё уточняется.
    - team
    - governance
    # `inspect <id>` — карточка одного продукта флота по id (контракт+вердикт+здоровье+риски). Только
    # чтение; форма ещё уточняется.
    - inspect
    # Фаза 5 (капстоун): `replan` — автономное перепланирование. Без флага read-only отчёт; с
    # `--apply` пишет переприоритизацию (класс A, обратимо, состав работ не меняет) в машинный
    # артефакт дочки, авторский план/main не трогает. Структурные изменения — предложением. Форма
    # отчёта/артефакта ещё устаканивается — потому experimental, а не stable.
    - replan
    # #539: `explain` — владельческая карточка одной задачи «что с моей задачей прямо сейчас»
    # (стадия, что готово/идёт, что мешает и ПОЧЕМУ последствием, следующий шаг, оценка стоимости).
    # Только чтение; собирается из active-work/workitem/usage-ledger/living_status. Состав полей и
    # формулировки ещё уточняются — дочка вправе смотреть, но не строить на форме.
    - explain
  # Advisory-гейты: не блокируют, форма улик и applicability ещё уточняются.
  # Проверяется числом и списком — quality/gates.yaml -> blocking: false.
  advisory_gates:
    - regression_test_evidence
    - concurrency_preflight
    - contour_consistency
    - own_medicine
    - event_contract_consistency
    - surface_wiring_consistency
    - feature_decision_quality
    - stakeholder_readiness
    - documentation_drift
    - documentation_updated
    - release_safety
    - decision_quality
    - knowledge_integrity
    - knowledge_freshness
    - observability_readiness
  # Ключи `.ai-ops.yaml`, объявленные, но ещё не устоявшиеся.
  config_keys:
    - product_operating_model
  contracts:
    - Experience Contract
    - watch-контракты

internal:
  # Импортировать снаружи нельзя. Внутри пакета имена пакетные, снаружи — никаких обещаний.
  packages:
    - checks
    - cli
    - context
    - delivery
    - devtools
    - engine
    - engops
    - gates
    - integrations
    - intelligence
    - governance
    - kernel
    - lifecycle
    - planning
    - providers
    - security
    - shared
    - ui
    - validation
  paths:
    - installer/
  note: >-
    Валидаторы вне рантайм-списка — внутренние: их наличие, имя и код возврата не контракт.
    Рантайм-список — тот, что исполняется в чеклисте и pytest.
```

## Пояснения к решениям

### `tools/` — снят в 4.0

До 4.0 `tools/` был слоем совместимости: код переехал в пакеты `ai_ops_kit/*` (v3.30-3.34), а в
`tools/` остались тонкие алиасы (`import workitem` вместо `from ai_ops_kit.lifecycle import
workitem`) ради внешних вызовов. Слой был объявлен `deprecated`, а в 3.40 прямой запуск плоской
точки печатал предупреждение. **В 4.0 слой удалён физически.** Точки входа зовутся пакетно:
`PYTHONPATH=.ai/managed python3 -m ai_ops_kit.<pkg>.<mod>` (или через обёртку `./ai-ops`); импорт —
`from ai_ops_kit.<pkg> import <mod>`. Соответствие старых имён — в `MIGRATION_GUIDE_4.0.md`.

### `update_channel` — решается работой A2

Поле `parent.update_channel` объявлено обязательным в `child-config.schema.json`, но кодом не
читается: канала как механизма нет. Здесь оно перечислено в снимке обязательных полей схемы — как
факт схемы, а не как обещание поведения. Судьбу поля (наполнить смыслом или убрать из обязательных)
решает отдельная работа A2; до её исхода менять его здесь нельзя.

### Найдено при описи и НЕ исправлено здесь

Опись публичной поверхности вскрыла два расхождения. Оба — поведение, а не декларация, и оба лежат
за границей этой работы; записаны, чтобы не потерялись.

1. **`./ai-ops status` в самом ките отвечает не о том.** Обёртка кита отправляет `status` в
   установщик (отчёт о дрейфе managed-слоя), а обёртка дочки — в движок (что идёт прямо сейчас), и
   состояние кита там названо отдельно, `kit-status`. Комментарий в шаблоне дочки прямо описывает
   это расхождение как исправленный дефект — в собственной обёртке кита он остался.
2. ~~**Интент `session` в дочке недостижим.**~~ **ЗАКРЫТО 19–20.08.2026** второй лентой этой же
   работы. Дефект был двойным: обёртка дочки отправляла `session` в установщик, которого в поставке
   нет, И само имя не было внесено в список исполняемых интентов CLI — команда печатала «Выполню
   намерение» и возвращала **0**, то есть отказ выглядел успехом. Обе половины исправлены,
   расхождение списка с обработчиком теперь краснеет тестом
   (`tests/contracts/test_direct_intents_match_handler.py`).

Первое расхождение относится к `ai-ops` — точке входа самого кита, а не к границе с дочкой.
