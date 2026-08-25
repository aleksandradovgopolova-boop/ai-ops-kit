Прополка: монолитный селфтест `tests/unit/test_tool_broker_selftest.py` (одна мега-функция с
десятками проверок через `expect()`) заменён гранулярными тестами в `tests/unit/test_tool_broker.py`.
Каждое поведение движка политик безопасности — op:git-gauntlet, destructive+approval, child-override
protected_paths, чтение с начала файла и по диапазону, вырезание секретов из окружения shell и из
вывода, block_push/allow_network и их дефолты, посегментная allowlist-проверка (chained/pipe/
подстановка/фон/сырой bash), quote-обфускация и её честная граница, traversal на decide, allowlist
окружения — теперь отдельный именованный тест с проверкой ЗНАЧЕНИЯ, а не только формы ответа. Два
уже гранулярных теста fail-closed-скраба перенесены без изменений. Покрытие не потеряно, монолит снят.
