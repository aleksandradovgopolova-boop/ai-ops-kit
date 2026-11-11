# Новый пользовательский ход после native handoff — #1434

Результат: после проверенного current-session handoff новое уточнение пользователя
достигает текущего агента без нового запроса, claim, controller или провайдера.
Пути: UserPromptSubmit → intake continuation → immutable event receipt → resume;
finalize/reconcile/verify должны учитывать последующий пользовательский ввод.
Инварианты: request/claim/исходная постановка и подготовленный план сохраняются;
event identity, не текст; unknown/autonomous claim остаётся fail-closed; текст не
становится approval или независимым verdict. Accepted не следует из нового ввода.
Failure modes: новый turn ошибочно останавливается; replay/late conflicting event;
tamper/смена контекста/unknown handoff; поздний ввод во время verification; новый
запрос после accepted теряется. Проверки — реальные hook commands обоих runtime,
FS/Git/claim side effects, полный путь до независимой проверки и следующей задачи.
Границы: исходные облачные claims не трогать; physical primary и app deploy HOLD;
не запускать модели, не извлекать approval из слов пользователя, не снижать gates.
Нужны независимое review, install compatibility и CI точного итогового head.

## Уточнение intake до claim

Независимый probe: после run с task_type=research и отсутствующими size/risk
новый ответ пользователя заменяет active request и исходную постановку. Это P1
исходного пользовательского пути. До реализации расширения: сохранить durable
маркер фактически запрошенных недостающих intake полей и уже заданные signals;
только для известного pending clarification/preparation принимать следующий ввод
как continuation того же запроса без claim. Fresh pending без такого маркера не
склеивать семантическим угадыванием. Не извлекать approval из текста. Проверить
оба runtime/отсутствие turn_id: original prompt → missing intake → новый ответ →
тот же request/signals → spec/controller → реальные checks/independent gates.


## Решение и границы

CLI передаёт в lifecycle валидатор подтверждённого prepared current-session handoff:
проверяются mode/status, пустой regular claim без symlink, текущие root/branch/managed/config,
канонические controller-артефакты и сохранённые хэши. Проверка и запись проходят под requests
lock. Квитанция создаётся create-only с fsync/readback и mode 0600; локальная постановка
хранит полный manifest её хэшей. Потеря, изменение, orphan/посторонний файл закрывают путь.
Ни исходная постановка, ни preparation, ни файлы controller, ни claim не заменяются.

При надёжном turn_id event_id детерминирован, текущий повтор идемпотентен. После нового
ввода исходное событие и предыдущие continuation считаются поздними. Без turn_id runtime
получает новую delivery-only квитанцию с `identity_scope: unreliable`: это отдельная доставка,
а не task UUID, без обещания идемпотентности/обнаружения позднего повтора и без text dedup.
Пустой/нестроковый переданный turn_id остаётся ошибкой. Неизвестный или автономный claim,
неподготовленный handoff и смена контекста остаются fail-closed.

Полный manifest ignored runtime receipts входит в artifact_inputs и отдельный inputs_sha256
review scope. Worker проверяет scope после реальных checks; публикация durable отчёта и
reconcile/accepted запись синхронизированы с intake тем же requests lock. Новый записанный
ввод делает старые review/verification proof неприменимыми. Короткий конфликт блокировки
даёт явный отказ, не ложную приёмку. Reviewer request перечисляет локальные input_receipts:
судья обязан учитывать уточнения, текст не заменяет ApprovalRecord. Payload создаётся только
в ignored/untracked runtime path; при попадании его в tracked Git дальнейшая проверка закрыта.

CLI сохраняет факт запроса недостающих intake-полей (вместе с уже заданными signals)
либо ожидания spec в mode=current-session. Только такой known pending marker без claim
даёт продолжение той же постановки; fresh pending без marker остаётся семантически
неоднозначным и сохраняет прежнюю границу отдельных запросов. JSON `--signals` дополняет
сохранённые signals; payload пользователя не разбирается программно. Запись подготовки и
claim синхронизируется с intake и сохраняет receipts, пришедшие между этими стадиями.
Autonomous markers, неверный список missing и чужая spec закрывают продолжение.

## Проверяемые исходы

Actual shell hook обоих runtime: новый reliable turn и обычный payload без turn_id →
тот же request/claim/preparation → CLI resume без процесса → real checks/finalize/reconcile →
accepted → следующий настоящий запрос. Fail-closed: unknown/autonomous/unprepared,
missing/nonempty/symlink claim, чужой plan/context, конфликтующий/поздний/malformed event,
receipt tamper/delete/add и runtime path без ignore. Side-effect proof проверяет байты
подготовленных файлов, claim и process log, отсутствие ApprovalRecord и tracked input.
Гонки покрывают ввод внутри реальной check-команды и после worker перед reconcile:
старый отчёт не принимается, повтор проверки работает без нового execution claim.

## Изменение объёма работы

Сохранение нового ввода не пересчитывает автоматически risk/size/workflow или критерии
приёмки уже prepared RunPlan. `run --signals` после handoff остаётся resume того же плана.
Если уточнение меняет классификацию или объём работы, требуется отдельное штатное
перепланирование; этот путь не предоставляет нового API перепланирования и не подтверждает
безопасность произвольного расширения scope по тексту. Фактический security diff и approvals
всё равно проверяются существующими gates. До подходящего плана и проверки изменённых
обязательств не объявляй задачу выполненной.

Независимый tool/read-only Agent result внутри текущего хода не является UserPromptSubmit.
Ручная передача digest новым пользовательским ходом добавляет input и требует обновлённого
scoped review; обходить эту инвалидацию по содержимому сообщения нельзя.
