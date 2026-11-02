# #1406 / R5 — полный откат неудачного обновления

Результат: отрицательный smoke или исключение после первой записи возвращает установку к исходным байтам, режимам и отсутствовавшим путям.
Затрагиваемые пути: delivery → CI и его backup/prints → ignore/attributes → локальные ключи merge-driver → entry/communication/team/lint → context/planning/product scaffolding → managed/config → skills/commands/generated (включая qwen и явно заданный CODEX_HOME).
Инварианты: один inventory связывает шаг поставки с областью снимка; owner-файлы и чужие настройки сохраняются; глобальный Git/config/trust не меняется.
Failure modes: неполный inventory; исключение посреди delivery; оставшиеся новые файлы/каталоги; потеря executable mode; ложное сообщение об успешном откате при ошибке восстановления.
Доказательство: positive update и наблюдение изменённого footprint до ошибки; negative smoke с полным сравнением дерева; exception в delivery; existing/absent owner paths; isolated local Git keys; targeted installer regressions + core smoke + lint + независимый review.
Окружение: только временные synthetic Git children, с отдельным CODEX_HOME либо без него; повтор Git/FS сценариев с GIT_CONFIG_GLOBAL=/dev/null и нативно на macOS.
Не входит: scripts/check-upgrade-path.sh; YAML/traversal/diagnostics соседних срезов; реальные дочки; models; push/PR/merge/release; закрытие всей fleet qualification #1406.

Независимое review выявило ссылки в footprint: delivery пишет сквозь них в owner-target вне снимка. Принято fail-closed: файл, каталог или ancestor-ссылка в области снимка блокируют update ДО backup/delivery с rc2/status=blocked; содержимое targets, ссылки и settings остаются прежними. Это ограничение поддерживаемого install footprint, а не доказательство fleet qualification.

Полный ready CI выявил связанный AST-разбор самоприменения: own_medicine должен читать ключи нового asset_inventory вместо прежнего словаря. Тесты доставки теперь различают same-version no-op и policy skip; mutation proofs добавляют/удаляют реальные tuple-записи inventory и отдельно подтверждают видимость мутации. Гейты и набор checks сохраняются.
Существующая mutation-проба gitattributes перенесена на новый callback inventory с тем же отключением вызова и теми же интеграционными тестами; baseline PASS и killed-пруф обязательны. Brief подключён к существующему индексу docs.
Fresh-base CI проявил file-taxonomy эвристику для R5 subprocess-harness. Добавлена прямая поведенческая регрессия snapshot preflight: при опасной ссылке сохраняются owner-target и уже существующий backup (непокрытая ранее гарантия). Порог taxonomy не меняется. Flaky host-resource test теперь моделирует неизмеримый CPU явно; случайный существующий idle PID 999 больше не подменяет предусловие fail-closed проверки. Продуктовый resource gate не меняется.
