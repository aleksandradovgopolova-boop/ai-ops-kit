# AI Ops Kit v0.8.0 — delta (закрытие post-MVP бэклога)

Содержимое: только новые/изменённые файлы поверх v0.7.0.

## Как применить (в сессии на ai-ops-kit)
1. Распаковать zip В КОРЕНЬ репозитория (пути уже правильные, файлы заменятся/добавятся).
2. Проверить (все должны быть PASS):
   python3 validation/validate_ai_first_registry.py
   python3 validation/validate_stale_gates.py --selftest
   python3 tools/generate_runtime.py --selftest
   python3 tools/orchestrator.py --selftest
   python3 validation/validate_presets.py
3. Закоммитить одним коммитом: "release: AI Ops Kit v0.8.0 (stale-gates, runtime generation, sequential orchestrator, presets)"
4. Запушить в main.
5. (Опционально) создать Release/tag v0.8.0 на GitHub.
