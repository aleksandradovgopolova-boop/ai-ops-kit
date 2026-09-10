Монолит ночного обзора `intelligence/nightly_review.py` (1097 строк) расщеплён на оркестратор и
два сателлита-соседа. Сбор read-only сигналов дельты (git/репозиторий: коммиты, изменённые файлы,
статус плана, наличие CI, открытые PR — плюс прогон шипнутых валидаторов `run_checks`) вынесен в
`intelligence/nightly_collectors.py`; расписание и доставка брифа владельцу (schedule_status,
install_schedule, deliver_brief и генерация CI-workflow) — в `intelligence/nightly_schedule.py`.
`nightly_review` остался оркестратором (collect_delta / format_brief / run_nightly / confirm_review)
и единственным держателем git-пишущего пути автофикса класса A — его намеренно не трогали, чтобы
`validate_nightly_no_direct_main_write` продолжал сторожить запрет прямой записи в main ровно в этом
файле. Поведение байт-в-байт то же: сателлиты импортируются самим обзором, ре-экспорт сохраняет
доступ `nightly_review.<имя>`. Файл упал до 665 строк (ниже порога 700).
