# Промежуточный impact fallback использует существующий PR-профиль

Результат: локальный impact CLI при draft/ready_for_review/merge_candidate и полном fallback исполняет существующий check-full.sh --pr; release_candidate сохраняет default full-current-python с nightly. Выбор файлов, risk floors и обязательный exact-head CI не меняются.

Основание: AGENTS.md допускает pr-current-python для обычного широкого цикла и сохраняет nightly/default/release отдельно. Сейчас devtools/impact_check_cli.py всегда вызывает default check-full.sh, поэтому обычная итерация повторяет nightly. Это доказанное расширение профиля по коду, не измеренное end-to-end ускорение. Baseline1327 выделил313с тестового шага selftests-m и4с установки; менять sharding на основании одного job interval нельзя.

Пути: scripts/check-fast.sh --impact → impact_check_cli.main → существующий verification_tiers.select_tests → check-full.sh. При full fallback обычных стадий добавляется только --pr. Не меняются source selection, граф, неизвестный impact и risk floors; release сохраняет default. Ненулевой exit дочерней команды передаётся вызывающему; plan-only не запускает проверки.

Пруф: реальные процессы CLI во временном git repo с risk path и fake check-full.sh, который реально пишет полученные argv до проверки. Positive: --pr для всех трёх обычных стадий; fail-closed: rc7 остаётся rc7; release: default argv; plan-only: нет side effect. Существующие impact safety/transitive cases и профиль check-full сохраняются.

Не входит: ослабление mandatoryCI/nightly/release gates, skip/xfail, обещание ускорения всего пути или новый selector. Полный локальный30мин профиль не повторяется автоматически; полный exact-head CI обязателен до merge. Новых агентов, релиза/deploy или внешних платных вызовов нет.
