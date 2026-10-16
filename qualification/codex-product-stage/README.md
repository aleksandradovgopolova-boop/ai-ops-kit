# Bounded PRODUCT.specification: native capture

2026-10-06, macOS / CPython 3.14.7, codex-cli 0.147.0, gpt-5.6-terra low.
`input.json` — вход последнего smoke; `stage-specification.md`, `NativeStageReport.json` и
`GateReport.json` скопированы без изменения из фактического каталога результата CLI.
`sources.json` фиксирует версии, source hashes и число запусков. Hash skill_context записан
после удаления одной пустой строки EOF; это единственное изменение этого источника после capture.

Реальный вход:

```bash
python3 -m ai_ops_kit.devtools.codex_stage_cli \
  --input qualification/codex-product-stage/input.json \
  --output-dir /tmp/NEW_NATIVE_STAGE_RESULT \
  --model gpt-5.6-terra --codex-bin /path/to/codex
```

Получены artifact_created / workflow blocked и exit 1: стадия исполнена, весь PRODUCT не готов.
Native audit содержит один SessionStart, tool calls — 0. Отдельно сохранённый stage artifact
совпадает с provenance hash. В evidence нет auth и raw tool payloads; temporary copies удалены.
Качество всей продуктовой задачи, raw model input, универсальная изоляция и полнота native audit
не квалифицируются. Новая CLI и native adapter находятся в непоставляемом devtools; defaults
продуктовых репозиториев не меняются.

Всего в разработке — четыре native запуска. Первый результат отклонён: Codex записал стандартное
уведомление vetted hook trust как item типа error, а первая версия parser запрещала все error
items. Исправлено точным allowlist только этого сообщения; actual errors и tools по-прежнему
отказывают (отдельные тесты). Следующий диагностический вызов и два CLI smoke успешны; финальный
capture выполнен после переноса адаптера в devtools и исправления публикации. Это расход лимитов
native аккаунта, не утверждение бесплатности Codex; Jev и Claude — 0 calls.

Независимый review выявил P2 частичной публикации, исправленный подготовкой всего комплекта в
соседнем temporary directory и атомарным rename в зарезервированное новое имя. Проверены отказ
записи отчёта и запрет перезаписи существующего результата. Correction review — без новых находок,
52 targeted passed. После изменения расположения — 63 targeted passed, включая footprint,
docs index и dormant inventory. Первый fast profile: 8329 passed, 2 failed (footprint/docs index);
обе причины исправлены, соответствующие проверки затем прошли.

Final relocation review — без новых находок, ещё 52 targeted passed.
full-current-python (CPython 3.14.7 / darwin): 9024 passed, 35 skipped, 2 warnings; exit 0. В CI native model calls не запускаются.
