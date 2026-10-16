# #1278: отзыв разрешения действует до доставки

## Результат
Последнее записанное решение для той же цели определяет одобрение. Старое approve
не переживает последующее revoke/deny/неоднозначное решение. Повторное явное approve
может разрешить действие. Режим observe остаётся наблюдением, block — принуждением.

## Затрагиваемые пути
ai_ops_kit/governance/enforcement.py; tests/unit/test_governance_delivery_enforcement.py;
этот brief, замер и newsfragment. Формат журнала/публичный API/уровни policy не меняются.

## Инварианты
Используем существующий append-only decision_log и human_override. Порядок записи
эпизодов задаёт последнее решение, дата без времени не используется как новый ключ
версии. Оба существующих alias цели (work-id/action:work-id) учитываются вместе.
Никакого автоматического изменения политики или расширения полномочий.

## Failure modes
Старое approve после revoke; отзыв через другой alias; отзыв другой работы;
неоднозначное последнее решение; повторная доставка после отзыва.

## Доказательство
До исправления — записи approve→revoke через настоящий registry API, gate block
разрешает доставку. Positive: повторное approve; fail-closed: revoke/unknown;
side-effect: настоящий transactional _deliver и локальный внешний marker, отзыв
не достигает внешнего вызова. Все имитации человеческих решений — только fixture,
не owner acceptance и не полевой результат #1243. Свежий независимый AI review,
целевые тесты, full-current-python и GitHub CI.

## Не входит
Отзыв уже выполненного внешнего действия, отмена in-flight запроса после проверки,
expiry полномочий, полноценный security jail, приёмка реальной продуктовой работы.

Смежная контролируемая квалификация существующей доставки сохранена в
qualification/delegation-faults-2026-10-16/: фактический loopback HTTP POST с потерей
валидного ответа, reconciliation и отсутствие второго POST. Отдельно неуспешный
durable-барьер дал 0 HTTP-запросов. Это не crash живого агента/не GitHub reliability.
Regression до фикса: 7 failed, 11 passed. После: 31 passed за 6.97s.
Свежий независимый AI review: NO FINDINGS; его pytest не запускался из-за отсутствия
pytest в выбранном им interpreter, авторский целевой прогон выполнен отдельно.

Поле process-* дополняет инъекцию барьера настоящим SIGTERM: durable Intent,0POST;
common resume opened, повтор updated;1заявка, тот же delivery_id/SHA. Все fixtures
явно отделены от принятых работ. Финальный full-current-python CPython3.14.7/darwin:
9151 passed,35 skipped,2warnings,1630.49s. Новые production файлы/зависимости отсутствуют.
