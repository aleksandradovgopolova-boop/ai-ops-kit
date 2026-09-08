Настройки задаются intent-level выбором намерения по оси, а не набором внутренних флагов: человек
выбирает «что хочу» по семи осям (communication / autonomy / watch / quality / team / design / cost),
а резолвер раскладывает выбор на внутренние флаги. Оси объявлены данными
(`registry/capability-policy.yaml`), резолвер — в `ai_ops_kit/checks/capability_policy.py`
(`resolve` / `resolve_all`). Честность прежде всего: у каждого выбора `status ∈ implemented | planned`;
три оси построены целиком (communication/autonomy/team), у остальных часть выборов помечена `planned`
и резолвер НЕ выдаёт их за готовые (value=None), а `default` обязан быть implemented. Проверяет
`validate_capability_policy.py` + `tests/contracts/test_capability_policy.py`. Достройка недостающих
switch'ей (watch continuous, quality strict, design auto/external, cost economy/quality-first) —
по мере поля, не впрок. Вторая половина #632. (#644)
