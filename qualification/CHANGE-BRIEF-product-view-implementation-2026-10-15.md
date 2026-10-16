# #1240 — пять вопросов существующего пульта

До кода: audit текущего пульта 15.10 сохранил current/backlog/fallback screenshots
и конкретный brief в qualification/product-view-audit-2026-10-15/README.md
(готовится в отдельной документационной ветке #1239/#1240).
Результат: существующий пульт показывает одну следующую работу с основанием,
≤2 альтернатив, настоящие причины ожидания и последние Git-изменения; fallback явен.
Пути: next_work CLI → dashboard build_data → data.json/snapshot → существующий index;
plan waiting_on/human_decision/evidence → blockers; git log → recent changes.
Инварианты: ранжирует существующий next_work, не вторая копия плана; read-only;
ошибка/битый план — unknown/degraded без рекомендации; всё untrusted экранируется;
никаких новых прав, нового dashboard/дизайна или записи в дочку.
Failure modes: отбрасывается отказ CLI; ручное ранжирование; owner wait показан
как ready; snapshot назван live; коммит объявлен измеренным продуктовым эффектом.
Доказательство: positive совместимость с реальным next_work, fail-closed отсутствующий/
битый план, side-effect proof настоящей сборки data и видимого браузерного результата;
три UI-сценария, независимый review, full-current-python. Никаких live model calls.
