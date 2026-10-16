# Change Brief — #1241: границы автоматизации

Результат: владелец видит install/execute/review/hooks/parallel по всем runtime реестра.
Пути: README → qualification matrix → существующие capture/registry; plan → history.
Инварианты: documented не равно live verified; дата/версия/источник у каждой клетки;
ручное событие не равно native hook, bounded stage не равно полный workflow.
Failure modes: устаревшее evidence без даты; успех fixture выдаётся за enforcement;
декларация превращается в pass; Codex review вне Kit выдаётся за Kit gate; unknown скрыт.
Доказательство: сверить клетки с capture и фактическим exit; независимое read-only review;
проверить ссылки и full-current-python. Это сводка, новая capability не добавляется.
Не входит: новые adapters, повышение runtime статусов, live inference, новый глобальный gate.
