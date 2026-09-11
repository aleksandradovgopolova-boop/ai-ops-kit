# arch.rules.md — оперативный слой Архитектурной конституции

> Генерируется из `ARCHITECTURE_CONSTITUTION.md` (`scripts/build-rules.py`). Не редактировать вручную.
> Держится в контексте агента. Детали правила — в Конституции по ID.
> Формат строки: **ID** · УРОВЕНЬ · заголовок — gate: `гейт` (исполнение).

## Преамбула — Честность
- **HON-001** · MUST · Правило без гейта — пожелание — gate: `meta` (meta)
- **HON-002** · MUST · Недоказанное называется недоказанным — gate: `none` (none)
- **HON-003** · MUST NOT · Запрет ложной зрелости — gate: `none` (none)
- **HON-004** · MUST · Объявлено ≠ подключено (built ≠ wired) — gate: `test_dormant_inventory` (parent)
- **HON-005** · MUST · Писатель ≠ судья — gate: `reviewer_handoff` (child)

## Часть I — Архитектура (макро)
- **ARCH-001** · MUST NOT · Зависимости образуют DAG — без циклов — gate: `validate_layering` (parent)
- **ARCH-002** · MUST · Направление зависимостей — вниз по слоям — gate: `validate_layering` (parent)
- **ARCH-003** · SHOULD · Логика живёт в своём слое — gate: `none` (none)
- **ARCH-004** · MUST · Один источник истины — gate: `none` (none)
- **ARCH-005** · MUST NOT · Границы модулей — только через контракты — gate: `none` (none)
- **ARCH-006** · MUST NOT · Нет god-модуля и монолита — gate: `validate_module_size` (both)
- **ARCH-007** · SHOULD · Фреймворк изолирован адаптером — gate: `none` (none)
- **ARCH-008** · MUST · Контракты явные и версионируемые — gate: `none` (none)

## Часть II — Код (микро)
- **CODE-001** · SHOULD · Функции короткие и односмысловые — gate: `validate_func_size` (parent)
- **CODE-002** · SHOULD · Плоский поток — ранние возвраты — gate: `none` (none)
- **CODE-003** · MUST NOT · Без дублирования (DRY) — gate: `test_code_duplication` (parent)
- **CODE-004** · SHOULD · Имена раскрывают намерение — gate: `none` (none)
- **CODE-005** · SHOULD · Без магических значений — gate: `none` (none)
- **CODE-006** · MUST NOT · Ошибки не глотать — gate: `none` (none)
- **CODE-007** · MUST NOT · Без мёртвого и закомментированного кода — gate: `test_capability_reachability` (parent)
- **CODE-008** · MUST · Тестируемость — gate: `validate_test_taxonomy` (child)
- **CODE-009** · SHOULD · Строгая типизация — gate: `none` (none)
- **CODE-010** · MUST NOT · Без галлюцинаций API — gate: `none` (none)

## Часть III — Безопасность
- **SEC-001** · MUST · SECURITY.md в каждом репозитории — gate: `required_repo_artifacts` (child)
- **SEC-002** · MUST NOT · Секреты не в коде — gate: `none` (none)
- **SEC-003** · MUST · Входные данные недоверенны — gate: `none` (none)
- **SEC-004** · MUST · Наименьшие привилегии — gate: `none` (none)
- **SEC-005** · MUST · Гигиена цепочки поставок — gate: `none` (none)
- **SEC-006** · MUST · Защита main — ревью до мержа — gate: `reviewer_handoff` (child)
- **SEC-007** · MUST NOT · Не течь внутренности в ошибках и логах — gate: `none` (none)

## Часть IV — Данные и API-контракты
- **DATA-001** · MUST · Явная схема данных — gate: `none` (none)
- **DATA-002** · MUST · Схема — источник истины, реализация из неё — gate: `none` (none)
- **DATA-003** · MUST · Контракт версионируется; ломающее — только мажор — gate: `none` (none)
- **DATA-004** · SHOULD · Обратная совместимость по умолчанию — gate: `none` (none)
- **DATA-005** · SHOULD · Ошибки контракта — явные и машиночитаемые — gate: `none` (none)
- **DATA-006** · MUST · Миграции данных — через миграцию, обратимо и проверяемо — gate: `none` (none)
- **DATA-007** · SHOULD · Идемпотентность операций с эффектом — gate: `none` (none)
