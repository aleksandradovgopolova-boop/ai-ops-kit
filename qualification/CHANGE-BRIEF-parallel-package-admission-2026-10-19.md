# Допуск каждой пакетной попытки после ожидания слота

Результат: автоматический parallel запуск повторно сверяет canonical owner/generation и frozen saved inputs непосредственно перед каждым package run callback. Если между общим dispatch и очередным callback работа перенята, закрыта, потеряна/повреждена либо входы изменены — прежний callback не вызывается.

Пути: automatic saved-root admission → active_work.register → parallel_live_dispatch → run_live_concurrent/isolated package runner → guarded run_fn → существующий active_work.claimed_attempt +validate_admission; далее прежние package evidence/fan-in/report/conditional finish. Explicit parallel без automatic admission и single-path не меняются.

Инварианты: один источник generation и frozen inputs, без нового scheduler/lease; короткий canonical lock отпускается ДО run_fn/сети. Успешная короткая проверка означает admission callback: передача уже после этой проверки (в том числе до фактического входа в run_fn) не отменяет допуск. Уже допущенный callback может завершиться после takeover и не объявляется отменённым; атомарность с внешним вызовом здесь не обещается. Новые callbacks проверяются после clone и перед run_fn; disposable clones могут создаваться, но новая модель/пакетный run не стартует. Report и finish по-прежнему защищены generation.

Failure modes: takeover/новая generation той же session; missing/corrupt/closed claim; frozen input drift; уже допущенный внешний эффект после передачи; непреднамеренное удержание canonical lock во время callback.

Доказательство: RED на старом main с фактическим run_fn marker после real register takeover; positive real Git clones/package commits; 3 independent roots и2slots — первые2callbacks фактически допущены, после takeover третий callback не начинается; уже стартовавшие callbacks сохраняют результаты, новые canonical/projected/carrier/report bytes не перезаписываются. Отдельные corrupt/closed/input-drift проверки и обычный explicit путь. Targeted→core, structural/lint/layering/towncrier, независимый entire-delta review и17exact-headCI перед normal match-head merge. Без native/paid вызовов.

Не входит: автоматический takeover, leases, general capability assignment, durable shared reservations, crash resume всех стадий, отмена уже допущенного запроса, полевая квалификация/закрытие1322.

Первый пруф на базе60c4132f:7RED/1positivePASS. Все6вариантов stale input/ownership фактически достигли run_fn; real three-root/two-slot прогон начал лишнийcc после takeover. После исправления7/8PASS; оставшийся assert ожидал словоclaim, тогда как существующий parser честно сообщил «реестр повреждён» — уточнён expected message без изменения production. Итоговый affected/core и exact-headCI обязательны отдельно.
