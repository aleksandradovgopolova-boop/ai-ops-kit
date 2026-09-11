Последний мега-тест-файл `tests/unit/test_tool_broker.py` (~964 строки) разрезан по поведенческим
темам на два: решения политики/path-containment/read-write/self-host остаются в исходном файле, а
shell-канал (режимы/allowlist/сеть/block_push/scrub/sandbox_policy) вынесен в
`test_tool_broker_shell.py` (общий git-хелпер фикстур — в `_tool_broker_helpers.py`). Перенос
behavior-preserving: тела тестов не менялись, число собранных тестов сохранено. Новый структурный
сторож `test_no_mega_test_file` краснеет, если любой `tests/**/test_*.py` перерастает порог строк —
монолит теперь ловится в тот же день, а не спустя месяцы.
