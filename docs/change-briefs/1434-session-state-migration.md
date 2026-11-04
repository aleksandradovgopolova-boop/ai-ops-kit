# #1434: проверяемый перенос pending-state между managed-версиями

## Результат

Владелец заранее сохраняет приватный snapshot всей истории проектных сессий и связанных
артефактов. После отдельно выполненного штатного update он видит preview переноса, применяет
его по точному SHA256 плана и при необходимости откатывает только собственные изменения.
Миграция не запускает workflow/provider/controller, не завершает запросы и не переписывает claims.
Реальный повод: в ИИ-Среде 21 active pointer остался на старом managed binding; среди них есть
обычные pending/preparation и одинаковые suggestion-payload. Содержимое prompt не определяет допуск.

## Пути и контракт

- Новый экспериментальный CLI и lifecycle helper: capture → preview → apply → rollback.
- Capture хранит ВСЮ историю `.ai/runtime/sessions`, `features`, `.ai/runplan`,
  `openspec/changes`, старый managed и установочный
  контекст; не объявляется полной резервной копией пользовательского проекта/Git.
- Только same-root/branch/HEAD/config/product context и валидные manifest/checksums; единственная
  разрешённая разница config — `parent.installed_version`, равная целевому VERSION. Смена root
  или независимая правка продукта требует отдельного решения. Исключение для product comparison:
  штатное удаление двух пустых строк между соседними communication-policy END/project-session BEGIN
  в CLAUDE.md; остальной текст/mode и точный контекст после preview проверяются. Поддержка schema_version=1,
  перехода внутри major и доказанного pending без execution/claim/report. Неизвестное сохраняется.
- Active pending, чья исходная binding совпадает с захваченным контекстом, получает новую binding
  и ссылку на отдельный migration receipt. Все остальные поля, IDs, сигналы, статусы и результаты
  сохраняются. Неактивная история и состояния с claim/execution не переобъявляются готовыми.
- CLI/hooks, прямые mutator-входы и отдельный completion worker координируют записи общим
  неблокирующим shared lock; migration берёт exclusive lock ПЕРЕД preparation и requests locks.
  Migration удерживает и существующие
  preparation/requests locks. Для старых некооперативных runtime обязательно согласованное окно.
- CAS перед применением/каждой записью, durable transaction journal до первой записи; незавершённая
  транзакция блокирует обычные записи до явного rollback. WAL содержит все before/after bytes и
  modes до первой замены; rollback имеет собственную durable phase, повтор после его прерывания
  распознаёт before/after/divergent, включая ошибку fsync после успешной замены. Откат не удаляет новые concurrent inputs:
  при расхождении сохранённых bytes/manifest он отказывает, сохраняя неизвестный исход.
- Новый пользовательский turn после корректной миграции может продолжить тот же pending, сохраняя
  immutable input receipts; это не approval и не acceptance. Старые review/verification не получают
  действительность для нового managed-кода; claimed/executed состояния остаются закрытыми.
- Публичная experimental-декларация CLI, runtime-инструкция, FILE_INDEX и newsfragment синхронны.

## Инварианты

Ноль provider calls и повторов задач. UUID/active pointers/claim bytes не меняются. Никаких
accepted/cancel/skip по тексту или по факту snapshot. Перенос не снимает review/gates. Прежние
snapshot/receipts не перезаписываются; private files не коммитятся и не выводят пользовательские
prompt/results в stdout. Первичная установка и app deploy остаются вне этой работы.

## Failure modes (5)

1. Подменённый snapshot/plan, symlink/path escape, неизвестная схема или несовпавшая identity.
2. Независимый product/config/branch/root drift или новая запись между preview и apply.
3. Конкурирующий writer/new turn/claim; bounded отказ без потери нового ввода.
4. Прерывание после части замен; journal сохраняет исход, rollback возвращает только известные bytes.
5. Ложная приёмка старых receipts либо скрытый повтор controller/provider в ходе миграции.

## Доказательство до поставки

Positive: настоящий disposable install старого source → snapshot → update → actual migration;
проверить изменившуюся binding при равенстве всех IDs/status/signals/claims/results. Negative:
изменить реальный файл/claim/input и доказать CAS-отказ после факта изменения. Side-effect proof:
проверить реальные записи и rollback байтов, а не mock return. Отдельно plain/prepared/claimed/
accepted/history, оба runtime, новый turn, отсутствие turn ID, гонки, fault injection/interrupt,
повтор apply, откат после concurrent input, неправильный root, недоверенный suggestion marker.
Нативный macOS и Git без global identity; применимые core/lint/contracts, независимое review и CI
точного head. Полевая активация primary и оплачиваемая модель этим не квалифицируются.

## Границы владения

Existing tracker #1434; смежные #1348/#1406 не дублируются новой issue. Coordinator подтвердил
единственного владельца этого isolated slice. Historical blocked claim team-kit-autostart-1434
не снимается. Exact file claim: новые `ai_ops_kit/lifecycle/session_migration*.py`,
`ai_ops_kit/cli/project_session_migrate.py`, tests `test_session_migration*.py`; небольшое wiring
в `lifecycle/project_session.py`, `cli/project_session.py`, `cli/project_session_completion.py`
(дополнительный fileclaim согласован coordinator) и соответствующих docs/index/fragment.
Installer rollback #1406, provider/sessionstart/native-preflight, observability #1467, первичные
dirty деревья и чужие PR не изменяются. При новом live-overlap спорный path приостанавливается.
