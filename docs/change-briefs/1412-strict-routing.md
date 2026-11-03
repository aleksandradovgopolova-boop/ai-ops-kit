# Strict для результата маршрутизации — #1412

Результат: настоящий потребитель `route()` видит типы результата выбора; `shared.ai_route`
становится шестым strict-модулем с прежним ратчетом. Старый engine-реэкспорт сохраняется.
Затрагиваемые пути: signals + registry → `shared.ai_route.route` → WorkItem/run_plan/CLI;
`shared.contracts.RouteResult` → compiler-пробы; `pyproject.toml` → штатный mypy и CI lint.
Инварианты: registry и JSON Schema сохраняют авторство политики/внешнего формата; TypedDict —
только статическая проекция существующего Python-вывода, без runtime-модели и преобразований.
Failure modes: экспорт остаётся Any; strict сужается; None выбора маскируется строкой;
аннотация меняет approval/выбор; Python-проекция ложно объявляется эквивалентной JSON Schema.
Доказательство: positive/negative compiler-пробы с проверкой записанного source; исходные
routing-сценарии и пробы пустого выбора/approval; byte comparison результатов до/после;
целевые контракты, core smoke, Ruff, независимое review и полный обязательный CI точного head/base.
Не входит: изменение решений роутера, схем/registry, adapters (#1434), Pydantic, весь #1412.
Существующие nullable choices и classification_confidence не соответствуют всей текущей схеме;
расхождение документируется, формат в этом срезе не меняется. Срез не является условием 4.12.
Индекс Change Brief не меняется, чтобы не пересечь #1434; ссылка будет в docs/api/contracts.md.
