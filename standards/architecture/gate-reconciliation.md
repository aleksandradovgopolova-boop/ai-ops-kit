# Реконсиляция гейтов Архитектурной конституции

> Генерируется `ai_ops_kit/devtools/arch_gate_reconciliation.py`. Не редактировать вручную.
> Сверяет обещание статьи (`gate`, `enforced_in` из `rules.yaml`) с реальностью: существует ли
> backing-проверка и доходит ли она до дочки — по тому же источнику, что и доставка
> (`installer.RUNTIME_VALIDATORS`/`is_runtime_asset`).

Колонка **«в дочке?»** — ключевая честность: `validate_layering`/`validate_func_size` и
контракты dormant/reachability гоняются **только в CI кита**; в дочку из структурного едут
`validate_module_size` и `validate_test_taxonomy` + рантайм `reviewer_handoff`. Статьи с
`gate: none` — честный долг (#827), а не защита.

| ID | Статья | Гейт | Исполнение | Backing | В дочке? |
|---|---|---|---|---|---|
| HON-001 | Правило без гейта — пожелание | `meta` | meta (само-правило) | — | — |
| HON-002 | Недоказанное называется недоказанным | — | none (гейта нет (долг)) | — | — |
| HON-003 | Запрет ложной зрелости | — | none (гейта нет (долг)) | — | — |
| HON-004 | Объявлено ≠ подключено (built ≠ wired) | `test_dormant_inventory` | parent (только CI кита) | tests/contracts/test_dormant_inventory.py | нет |
| HON-005 | Писатель ≠ судья | `reviewer_handoff` | child (едет в дочку) | ai_ops_kit/engine/reviewer_handoff.py | да |
| ARCH-001 | Зависимости образуют DAG — без циклов | `validate_layering` | parent (только CI кита) | ai_ops_kit/validation/validate_layering.py | нет |
| ARCH-002 | Направление зависимостей — вниз по слоям | `validate_layering` | parent (только CI кита) | ai_ops_kit/validation/validate_layering.py | нет |
| ARCH-003 | Логика живёт в своём слое | — | none (гейта нет (долг)) | — | — |
| ARCH-004 | Один источник истины | — | none (гейта нет (долг)) | — | — |
| ARCH-005 | Границы модулей — только через контракты | — | none (гейта нет (долг)) | — | — |
| ARCH-006 | Нет god-модуля и монолита | `validate_module_size` | both (и кит, и дочка) | ai_ops_kit/validation/validate_module_size.py | да |
| ARCH-007 | Фреймворк изолирован адаптером | — | none (гейта нет (долг)) | — | — |
| ARCH-008 | Контракты явные и версионируемые | — | none (гейта нет (долг)) | — | — |
| CODE-001 | Функции короткие и односмысловые | `validate_func_size` | parent (только CI кита) | ai_ops_kit/validation/validate_func_size.py | нет |
| CODE-002 | Плоский поток — ранние возвраты | — | none (гейта нет (долг)) | — | — |
| CODE-003 | Без дублирования (DRY) | `test_code_duplication` | parent (только CI кита) | tests/contracts/test_code_duplication.py | нет |
| CODE-004 | Имена раскрывают намерение | — | none (гейта нет (долг)) | — | — |
| CODE-005 | Без магических значений | — | none (гейта нет (долг)) | — | — |
| CODE-006 | Ошибки не глотать | — | none (гейта нет (долг)) | — | — |
| CODE-007 | Без мёртвого и закомментированного кода | `test_capability_reachability` | parent (только CI кита) | tests/contracts/test_capability_reachability.py | нет |
| CODE-008 | Тестируемость | `validate_test_taxonomy` | child (едет в дочку) | ai_ops_kit/validation/validate_test_taxonomy.py | да |
| CODE-009 | Строгая типизация | — | none (гейта нет (долг)) | — | — |
| CODE-010 | Без галлюцинаций API | — | none (гейта нет (долг)) | — | — |
| SEC-001 | SECURITY.md в каждом репозитории | `required_repo_artifacts` | child (едет в дочку) | ai_ops_kit/planning/standard.py | да |
| SEC-002 | Секреты не в коде | — | none (гейта нет (долг)) | — | — |
| SEC-003 | Входные данные недоверенны | — | none (гейта нет (долг)) | — | — |
| SEC-004 | Наименьшие привилегии | — | none (гейта нет (долг)) | — | — |
| SEC-005 | Гигиена цепочки поставок | — | none (гейта нет (долг)) | — | — |
| SEC-006 | Защита main — ревью до мержа | `reviewer_handoff` | child (едет в дочку) | ai_ops_kit/engine/reviewer_handoff.py | да |
| SEC-007 | Не течь внутренности в ошибках и логах | — | none (гейта нет (долг)) | — | — |
| DATA-001 | Явная схема данных | — | none (гейта нет (долг)) | — | — |
| DATA-002 | Схема — источник истины, реализация из неё | — | none (гейта нет (долг)) | — | — |
| DATA-003 | Контракт версионируется; ломающее — только мажор | — | none (гейта нет (долг)) | — | — |
| DATA-004 | Обратная совместимость по умолчанию | — | none (гейта нет (долг)) | — | — |
| DATA-005 | Ошибки контракта — явные и машиночитаемые | — | none (гейта нет (долг)) | — | — |
| DATA-006 | Миграции данных — через миграцию, обратимо и проверяемо | — | none (гейта нет (долг)) | — | — |
| DATA-007 | Идемпотентность операций с эффектом | — | none (гейта нет (долг)) | — | — |

_Итог: 37 статей — 11 с гейтом (5 доходят до дочки), 25 честный долг (#827)._
