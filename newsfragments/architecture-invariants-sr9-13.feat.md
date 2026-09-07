Инженерный стандарт SR-9..13 (срез 3): архитектурные инварианты дочки как ДАННЫЕ (advisory).
`ai_ops_kit/planning/architecture_invariants.py` + схема `schemas/architecture-invariants.schema.json`:
инвариант с id/правилом/причиной/силой (форма `packages/layering.yaml`), единый резолвер зоны
путь→зона, нарушение несёт адрес `файл:строка → ребро`, отсутствие объявления даёт `not_checked`
(не `pass`), новая зависимость без ADR — находка. Проведён в governance-отчёт дочки (#605) отдельным
блоком, без нового гейта. Граф JS/TS строится regex (stdlib) → блок целиком advisory до полевого замера.
