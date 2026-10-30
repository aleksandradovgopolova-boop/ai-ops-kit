# #1434 — checkout точной ревизии без именованной ветки

- Результат: проектный binding работает для обычного pinned checkout в detached HEAD.
- Источник: реальный checkout Марка на po-vm, commit4c670bac; binding падает на git symbolic-ref; проверка без моделей 30.10.2026.
- Пути: существующий lifecycle/project_session.py и его FS/Git регрессия.
- Инварианты: фактический root, HEAD, rules/config/managed/source hashes сохраняются; смена коммита/ветки по-прежнему обнуляет прежнее evidence.
- Решение: git rev-parse --abbrev-ref HEAD возвращает имя ветки либо HEAD для detached состояния; commit хранится отдельно.
- Доказательство: реальный Git checkout --detach; сохранение запроса, исполнение controlled producer, проверка receipt и отказ после изменения HEAD.
- Границы: без новых runtime, credentials, прав и модельных запусков; remote-Claude через SSH этим не квалифицируется.
