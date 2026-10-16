# #611: native инструкция выбирает описанный режим и своего исполнителя

Сгенерированный ai-run описывает controller/planned, но команда не задаёт --engine
и предлагает только claude-code|generic-orchestrator даже Codex/Qwen. Канонический
текст повторяет тот же устаревший пример. CLI по умолчанию выбирает pipeline.

Меняем только shared/generate_runtime.py, commands/task/ai-run.md, существующие
тесты генератора и usage-docstring engine/ai_ops_run.py, brief/замер/news. Native путь явно --engine controller
--runtime конкретного адаптера. Автоматический provider pipeline остаётся отдельным
явным режимом; флаг runtime не выдаётся за native dispatch.

Positive: настоящая сгенерированная команда создаёт согласованные WorkItem/RunPlan,
правильный runtime, planned без TaskState. Fail-closed: обязательные гейты сохраняются,
отсутствие исполнения не становится done. Side-effect: реальные файлы CLI в Git-fixture.
Три runtime из существующего реестра; новых зависимостей/форматов/провайдеров нет.
До кода — отрицательный прогон; затем focused, независимый AI review и full-current-python.

Это подготовка протокола #611, не свидетельство live выполнения всеми runtime,
owner acceptance или продуктовая когорта #1243. Исполнитель AI, USD неизвестны.

До исправления3failed/12passed10.01s; после22passed7.81s. Review NO FINDINGS.
Контролируемый Qwen получил403 до инструментов; отдельный native Codex прочитал
WorkItem/RunPlan, создал разрешённый файл, оба YAML неизменны. Общий status затем
needs_more_evidence. Пределы протокола и точные receipts: native-workmodel-consumer-2026-10-16/.

Full-current-python CPython3.14.7/darwin:9171passed,35skipped,2warnings,1004.41s.
