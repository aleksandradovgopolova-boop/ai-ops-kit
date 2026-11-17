# #1434 — начальная задача, переданная штатным Codex host

Результат: текущий Codex-агент может сохранить исходное поручение в lifecycle Кита,
если штатный host передал его как delegation, без UserPromptSubmit. Пользователь
не запускает CLI; capture выполняет сам агент, затем использует прежние run/finalize.

Источник: одна разрешённая живая попытка 17.11.2026 на ИИ-Среде 3e705f9d,
Kit 4.15.0, Codex 0.167.0-alpha.4.1. Реальный SessionStart доставлен; исходная
задача пришла как function_call_output/codex_delegation. User-role сообщения
содержат только AGENTS/environment scaffold. Сохранённой задачи, WorkItem,
RunPlan и приёмки нет. Прямой engine-вызов отклонён из-за выдуманных бюджетных
ключей; агент всё равно закончил справку. Это не успешная автономность.
Частные исходные свидетельства: /tmp/ii-sreda-kit-delivery-20261117/live-preparation/.

Затрагиваемые пути: SessionStart context с реальным session_id; новый внутренний
CLI intake (bounded JSON stdin); начальная pending-запись в прежнем lifecycle;
идемпотентное восстановление того же intake; сохранение неизвестного claim;
обычный UserPromptSubmit, run/spec/current-session handoff, finalize/review;
инструкция агенту и штатная установка в disposable child.

Инварианты: intake не имитирует hook и не создаёт turn_id. Происхождение явно
current-agent-intake, идентичность ввода declared; это не доказательство runtime
dispatch, личности, trust, ApprovalRecord или приёмки. Один initial intake на
сессию; другой текст/чужая active задача/accepted/неизвестное исполнение не
заменяются. Прежние binding/spec/gates/approvals остаются. Нет модели, provider,
controller, claim или продуктового результата на стадии capture. Подготовленный
resume проверяется прежним валидатором. Не принимаем неизвестные budget keys.

Failure modes: потерянный session_id; повтор/другой текст; чужая active запись;
неизвестный outcome/смена binding; зависший или чрезмерный stdin.

Доказательство: positive — реальная pending-запись и прежний run на synthetic
Git/FS fixture; negative — неверный payload/runtime, binding, чужой/unknown claim
с неизменными bytes; side-effect — capture существует до проверки и не создаёт
process/feature/claim, повтор не пишет второй запрос. Реальный блокирующий stdin
ограничен общим read deadline; smoke/линтеры/валидаторы и independent entire-delta
review точного кандидата. Эти проверки offline, не вторая живая попытка.

Не входит: включение hooks/trust, изменение native provider или preflight-контракта,
автоматическое принятие/ослабление Stop, paid API/новая модельная попытка,
поставка в рабочую ИИ-Среду и новая командная приёмка. Текущая установка неизменна.

Первичная локальная проверка: 24 новых теста PASS; после добавления bounded replay
26 новых и 63 core-smoke теста PASS. Расширенный промежуточный набор: 231 PASS,
1 FAIL в неизменённой проверке managed read deadline (worker не дошёл до marker
за 1.5 с). Отдельная та же проба на 4.15 и кандидате PASS с доказанным blocked read.
Это не общий зелёный профиль: причина не установлена. В assert добавлена только
диагностика последнего пути чтения, без изменения deadline/реакции/критериев.
Финальная delta требует повторной затронутой проверки и независимого review.
