# Strict mypy для состояния Budget — #1412

Результат: ратчет strict расширяется на существующий `shared.budget`; лимиты,
счётчики и durable ledger имеют конкретные типы, которые видит настоящий потребитель.
Затрагиваемые пути: `pyproject.toml` → штатный mypy/CI lint; `shared/budget.py` →
создание/resolve общего Budget → in-memory charge и durable reservation/readback.
Инварианты: `declared_limits` остаётся единственной проверкой деклараций; прежние
отказы, блокировки и сериализация сохраняются; неизвестная цена не становится нулём.
Failure modes: поле остаётся Any; strict можно сократить; потерян допустимый строковый
max_duration; cast скрывает непроверенный ledger; аннотация меняет runtime-поведение.
Доказательство: реальные positive/negative mypy-пробы с доказанной записью мутации;
конфигурационный ратчет; существующие budget/reservations-тесты с потоками, процессами,
аварией и повреждением ledger; core smoke, Ruff, широкий PR-профиль через общий слот,
независимое review и обязательный CI точного head/base.
Не входит: новые runtime-лимиты, изменение JSON Schema, Pydantic, роутер или adapters
(#1434), полный strict пакета и закрытие всей #1412.
