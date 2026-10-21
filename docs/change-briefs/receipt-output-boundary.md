# Проверяемые outputs и общий слот тяжёлых запусков

Результат: собственный pytest-кэш не превращает успешное свежее исполнение в BLOCKED; неизвестные изменения остаются блокирующими.
Пути: shared/lifecycle_store → impact_check_cli; devtools/host_resource_cli → scripts/check-full.sh.
Инварианты: старые receipts неизменны; нет ignore всего dirty; cache после исполнения входит в точный fingerprint; required CI не подменяется локальным результатом.
Failure modes: изменение source/dependencies/config/env; неизвестный файл в cache; tracked файл в output-path; конкуренция checkout/CI; потеря истории drift.
Доказательство positive: настоящий subprocess создаёт output и второй вызов переиспользует результат.
Доказательство fail-closed: каждый значимый вход и подмена cache после PASS требуют исполнения; неподдерживаемый output contract блокируется.
Доказательство side-effect: файловый счётчик и два независимых процесса конкурируют за общий host-slot; inode чужого lock не удаляется.
Граница совместимости: интеграция на exact main3cd01d35/VERSION4.11.1 в отдельном checkout; перенесены только task delta и patch, существующие профили/premerge/durable I/O сохранены.
P1-пути: host_resource_cli subprocess_kwargs → impact_check_cli и scope-fixtures; унаследованный slot не освобождается, потерянный fd даёт быстрый BLOCKED без ожидания своего родителя.
Размер: receipts выделены в existing shared/claim_provenance, lifecycle_store остаётся совместимым фасадом и владельцем durable I/O; потолки и число пакетов не растут.
Не входит: продуктовые работы/CI/security, push после denial, новый full suite в этом bounded шаге, автоматическое подключение внешнего self-hosted CI.

CI-регрессии main: receipts живут вне судимого Git дерева, stdout impact сохраняет один plan JSON; mutation anchor и индекс брифов сохранены. Новых файлов в child нет: host-функции внутри devtools, content proofs дополняют существующий claim_provenance. Потолок поставки не повышен.
