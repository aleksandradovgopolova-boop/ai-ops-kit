Красный main (lint + selftests-a) починен: `_sl` в `_build_not_yet_list` потерял импорт при
выносе из run_pipeline (K6) — NameError жил на живом пути spec-first; blind except в шине событий
получил записанную причину (fail-safe подписчика); мутация module-scoped фикстуры context_bundle
делала тест «первым по случайности» — падал в xdist, проходил локально; unused `result` в
характеризационном тесте убран.
