# #1322 — фактическое время исполнения пакетов

- Результат: существующий trace отличает передачу в очередь от фактического входа в package_runner и измеряет queue/execution отдельно.
- Пути: parallel_executor._run_packages → worker wrapper → существующий результат execute_parallel → durable parallel-report живого dispatcher.
- Инварианты: timestamps фактического runner появляются только внутри worker; отмена до старта и blocked dependency оставляют null. Успех/ошибка не меняют timing truth; длительности считаются monotonic, UTC labels не используются для арифметики.
- Failure modes: отменённая future выглядит запущенной; исключение теряет время реально начатого пакета; зависимость получает ложный старт; отчёт теряет trace; изменение лимита/порядка пакетов.
- Доказательство: реальная запись marker перед проверкой trace; контролируемые monotonic queue2/execution3; реально отменённая future без runner marker; runner пишет marker и выбрасывает ошибку; trace сохраняется в существующем report.
- Границы: время локального callback/очереди executor, НЕ физический model/native spawn, не полный job wall/idle, не durable recovery/lease/budget/USD. Расходы и полевая приёмка не выводятся.
- Не меняются: допуски, approvals, ownership fencing, bounded ≤2, fan-in/CI/review, публичные CLI/required schemas/зависимости. Нового merge helper не создаём: существующие merge-preview/receipt механизмы не являются полной admission; самостоятельный helper остаётся отдельным остатком.
- До merge нужны новый независимый review и все применимые exact-head CI. Нынешнее разрешение reviewer относилось только к завершённым PR1206/1324.
