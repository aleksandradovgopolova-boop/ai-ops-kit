Развязка «рантайм зовёт валидатор как библиотеку» ЗАВЕРШЕНА (лента №5, последний шаг). Снято
последнее восходящее ребро `intelligence -> validation`: `evolution_triggers` звал `profile()` в
рантайме и `check_registry()`/`DEFAULT_DIR` в CLI. Логика вынесена ВНИЗ в пакет `checks`:
`quality_attributes` (profile/fitness, чистые), `architecture_decision` (структура одного ADR,
чистая), `adr_registry` (проверка реестра — read-only чтение каталога).

`adr_registry` брал вокабуляр `ui_impact` из `gate_policy.UI_IMPACT` (пакет `gates`, capabilities) —
из слоя primitives тянуть его нельзя, поэтому вокабуляр теперь берётся из
`architecture_decision.UI_IMPACT` (та же величина, тот же слой). CLI-обёртки в `validation`
ре-экспортируют перенесённые имена; `evolution_triggers` импортирует всё из `checks` вниз.

Итог всей ленты: `known_violations` в `packages/layering.yaml` **пуст**. `validation` (entrypoints)
больше не импортирует как библиотеку вверх НИ ОДИН пакет ядра — все пять рёбер (`security`, `engine`,
`providers`, `lifecycle`, `intelligence`) сняты переносом логики вниз в `checks`, а не подпроцессом.
Единственный, кто зависит от `validation`, — `devtools` (тот же слой, это разрешено). Ратчет за №4+№5:
взаимных пар 7 → 5, циклов длиннее двух 52 → 11. Числа этого шага не менялись (ребро не было в цикле);
footprint поднят записью (+3 файла).
