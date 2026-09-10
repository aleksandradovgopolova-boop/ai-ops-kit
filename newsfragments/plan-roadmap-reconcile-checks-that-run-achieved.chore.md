Сведены план и roadmap под закрытые работы. Цель `checks-that-run` («каждая объявленная проверка
реально исполняется») ДОСТИГНУТА: последняя работа внешнего аудит-бэклога #721 —
`declared-tools-and-gates-prove-they-run` — закрыта (PR #841, инвентарь «объявлено→исполняется»
покрыл pre-commit-хуки), исход `external_audit_backlog_is_closed` флипнут в true, работа перенесена
в `history/plan-history.yaml`, цель убрана из ROADMAP «Сейчас». Работы `parallel-safety-allows-kit-own-update-prs`
(#836) и `the-plan-tells-the-truth-about-the-run` (#838) остаются открытыми ЧЕСТНО: их код влит и
протестирован, но done-when несёт остаток (живой полевой замер и полная перестройка specify-потока
соответственно) — заметки обновлены.
