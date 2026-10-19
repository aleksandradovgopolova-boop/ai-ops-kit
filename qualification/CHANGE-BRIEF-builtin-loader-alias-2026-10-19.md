# Builtin loader aliases и безопасный impact fallback — #1321

Результат: draft impact selection не сужает тесты при сохранении динамического builtin loader под другим именем (`load = __import__`, `run = eval/exec`).
Пути: RepositoryGraph AST uncertainty → существующий verification_tiers full fallback → targeted/full command; существующие точные final CI не меняются.
Инварианты: unknown dependency остаётся unknown, отдельный статический consumer не маскирует пропущенный dynamic consumer; обычные статические импорты остаются пригодны для targeted selection.
Failure modes: loader присвоен alias/передан аргументом; eval/exec конструирует импорт; alias reference ошибочно принимается за отсутствие динамики; изменение исходника действительно ломает скрытый consumer.
Доказательство: controlled consumer сначала PASS, затем реальное изменение source даёт FAIL; full fallback включает неизвестную зависимость даже при наличии direct consumer. Regression на aliases/передачу loader + ordinary static positive. Локально только ресурсный допуск, иначе штатный hostedCI; независимый review всей delta и17exact-headCI до normal merge.
Не входит: выполнение недоверенного кода продукта, новый граф/runner/tiers, новые зависимости/права/платные модели, обещания speedup/p95/USD, закрытие #1321/#1322 или полевая выборка.
