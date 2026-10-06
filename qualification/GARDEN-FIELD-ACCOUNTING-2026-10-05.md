# Garden — ревью, P0 и установка Kit: полевой учёт

Дата: 05.10.2026, Europe/Moscow. Сессия выбранной тройки: **S01 / garden / owner-led**. Источник передачи: чат «Review Garden repository», thread `01a10b99-d8b8-7511-8adb-a161cfa9136f`, по явной просьбе владельца. Это запись наблюдений, не установка Kit и не закрытие первого часа.


**Текущее состояние после доставки:** P0, установка4.9.3 и совместимостьCI приняты в main `da4b8b1d1674feaabcdf0592b5f858ae2f500269`; девять проверочных workflows SUCCESS. Предыдущие разделы с OPEN описывают исторические снимки, актуальные merge приведены в конце.

## P0 до установки — исторический снимок

| Поле | Значение | Основание |
|---|---|---|
| Реальная задача | Независимое ревью Garden и устранение P0 | Исходные userMessage и метки turn, затем передача |
| Репозиторий | [aleksandradovgopolova-boop/garden](https://github.com/aleksandradovgopolova-boop/garden) | GitHub API |
| Исходный main | `9ffe943a06d2d7f50f400299ccee31a02d8e4d6c` | Передача и повторное чтение main |
| Ветка P0 | `codex/garden-p0-foundation` | API PR6 |
| Коммит P0 | `e3c7d7dccd9ca550c4802458f07445cd1e35c088` | API PR6/commit |
| Доставка | [PR6](https://github.com/aleksandradovgopolova-boop/garden/pull/6) открыт, **не слит** | API: state=OPEN, mergedAt=null |
| Черновик PR | **Нет** | В передаче назван draft; API isDraft=false, этот факт имеет приоритет |
| Проверки | Documentation quality + Public site build: SUCCESS на указанном SHA | [Run37299367989](https://github.com/aleksandradovgopolova-boop/garden/actions/runs/37299367989) |
| Kit в Garden | **Не установлен** | В дереве PR нет `.ai/`, `.ai-ops.yaml`, launcher `ai-ops`; doctor/validate/qualification не проводились |
| Кандидат для будущего подключения | Версия 4.9.3, parent snapshot `38429f984acb7bde79884327b2916954f796f10c` | Передача; это не установленный digest Garden |
| Опубликованный выпуск 4.9.3 | Тег v4.9.3 / `ad16611cec1ca65a659f597f7b3b0436df8e78b8` | RELEASE-DELIVERY-v4.9.3-2026-10-05.md; отличается от parent snapshot после документационных PR |

## Подготовленный результат PR

По передаче: восстановлены OWNER-DECISION-001, GDR-006A, GDR-013A из July ZIP с provenance; добавлен полный машинный реестр решений и scoped supersession. Исправлены шесть завышенных accepted-статусов и устаревшие engineering references. Добавлены CODEOWNERS, закреплённые WowRepo engine/actions/runtime и проверки полноты/ссылок/границы артефакта; обновлены derived metrics и README. Первый срез ограничен Place → Save → Leave → Return; AI Preview/Undo — следующий срез по решению владельца. Содержимое этих изменений здесь не повторно ревьюировалось; оно пока находится в PR, не в main.

Повторно прочитанные CI-логи подтверждают **155 активных Markdown, 0 ошибок/предупреждений; 18 тестов; сборку 54 страниц; 0 production artifact errors**. Передача дополнительно сообщает исправление прежнего пропуска 40 вложенных research reports. Зелёная проверка site coverage подтверждена run; исходный дефект в этом учётном шаге не воспроизводился.

## Наблюдаемые времена — с ограниченным основанием

| Событие 05.10, Europe/Moscow | Время | Источник | Интервал от создания ветки |
|---|---|---|---|
| Создание рабочей ветки | 13:32:44+03:00 | Переданный git reflog; сам reflog здесь повторно не прочитан | Начало наблюдаемого окна, не точный старт задачи |
| Implementation commit | 13:52:12+03:00 | Повторно проверен GitHub commit date | 19м28с / 1168 секунд |
| PR создан | 13:52:47+03:00 | Повторно проверен API createdAt | 20м03с / 1203 секунды |
| Последняя проверка CI завершена | 13:53:42+03:00 | completedAt Public site build, а не updatedAt run | 20м58с / 1258 секунд |

Интервалы рассчитаны от **переданного времени ветки**. Они включают ответы и паузы человека в этом окне; exclusive active work из них не выводится. Старт наблюдаемой Codex-сессии ревью и запрос P0 теперь установлены по read_thread (раздел ниже). T0 именно прогона Kit, точный момент первого полезного сообщения, T_ready, человеческая помощь/активные минуты, model/version, токены и стоимость этим не установлены. PR не принят и не слит, поэтому T_pr как событие принятой первой работы ещё не наступило. Branch→PR не подставляется вместо принятого PR.

## Уточнение по началу сессии — исходный запрос и часы

По замечанию владельца прочитано начало чата «Review Garden repository» через read_thread, включая первоначальную userMessage, startedAt/completedAt обоих этапов. Дополнительный запрос владельцу о том, какую реальную задачу выбрать для Garden, был избыточным: задача уже названа.

Исходный запрос: **независимое комплексное ревью garden/main** — структура, документация, продуктовая концепция, решения, архитектура/код, тесты/CI/CD, совместимость с Kit; результат — фактическое состояние, противоречия, readiness, приоритетный roadmap P0/P1/P2 и список issues. Следующий явный запрос владельца: **«давай делать P0»**.

| Наблюдаемое событие | Europe/Moscow, 05.10.2026 | Основание |
|---|---|---|
| Начало Codex-сессии ревью | 13:26:34+03:00 | startedAt=1791195994, исходная userMessage |
| Завершение этапа с полным отчётом | 13:31:45+03:00 | completedAt=1791196305; 311 секунд / 5м11с от начала |
| Запрос выполнения P0 | 13:32:16+03:00 | startedAt=1791196336, userMessage «давай делать P0» |
| P0 → implementation commit | 13:52:12+03:00 | 1196 секунд / 19м56с от запроса P0 |
| P0 → созданный PR | 13:52:47+03:00 | 1231 секунда / 20м31с от запроса P0 |
| P0 → green CI | 13:53:42+03:00 | 1286 секунд / 21м26с от запроса P0 |
| Начало ревью → green CI P0 | 13:53:42+03:00 | 1628 секунд / 27м08с суммарного наблюдаемого окна |

5м11с — верхняя граница времени до полного отчёта по окончанию turn; сообщения с полезными фактами появлялись раньше, но read_thread не даёт отдельного timestamp каждого сообщения. Поэтому точное время первого полезного сообщения не выдумывается. Метки запроса P0 точнее branch-start для наблюдаемого начала исполнения; прежние интервалы от ветки сохранены как отдельный ряд. Оба ряда включают паузы и ответы человека.

Это реальная работа выбранной owner-led сессии, а не задача, которую ещё нужно придумать. Её связь с установленным Kit остаётся отдельным фактом: ревью и указанный коммит P0 подготовлены до установки. Позднее в том же чате есть отдельный userMessage «так установи Ai-ops kit» и сообщения о начавшейся установке релиза 4.9.3. Это новый этап; завершение установки/проверок и её собственное время внесены ниже. Формулировка «не установлен» в таблице относится к зафиксированному P0-коммиту e3c7d7d, а не является неизменным статусом всех последующих этапов.

## Внешнее состояние и открытые вопросы

API на момент записи: Garden **PUBLIC**; main требует PR, strict checks Documentation quality/Public site build и resolved conversations, enforce admins=true, force push/deletion=false. Required approving review count=0: независимое обязательное approval не enforced.

По передаче: после краткого private-периода владелец выбрала «тогда оставь пока публичным)» из-за ограничения GitHub Pro; Pages удалён, старый deployment workflow disabled, сайт возвращает 404. Это переданные сведения, в этом шаге API Pages и HTTP сайта отдельно не перепроверялись. Публичная доступность internal/archive не превращает их в безопасное место для confidential/raw participant data.

- [Garden#7](https://github.com/aleksandradovgopolova-boop/garden/issues/7) открыт: квалификация зависимостей WowRepo перед будущей публикацией. Передано 22 advisories: 5 moderate, 16 high, 1 critical; состав advisory здесь не пересчитывался.
- [Garden#8](https://github.com/aleksandradovgopolova-boop/garden/issues/8) открыт: второй reviewer, авторизованный владельцем, и enforcement approval.
- Передан targeted credential-pattern scan: 221 historical blobs + 306 archive members, 0 совпадений. Это результат ограниченной проверки по передаче; **не полный secrets/PII audit**, не воспроизведён в этом шаге.

## Вердикт для P0 до установки

**В учёт приняты подготовленная реальная P0-работа и проверенные артефакты её качества.** Атрибуция — вне установленного Kit. Реестр установленных дочек, измеренный эффект Kit, первый час и исходы целей не повышаются. Ни Green CI, ни выбранная версия-кандидат не доказывают использование Kit в Garden.

Следующий этап S01 назван владельцем в этом же чате: подключение Kit. Его завершение и часы приняты по подлинному журналу установки в разделе ниже, отдельно от проведённых ревью/P0. Уже выполненный P0 нельзя повторно выдавать за новую первую работу. Установку этот учётный шаг не запускает. Карточка: `/Users/sasad/.codex/visualizations/2026/10/05/01a10ae5-74a9-7e63-b83b-842077f437e4/first-hour/SESSIONS-2026-10-05.md`.


## Установка Kit — отдельный этап S01

Kit **установлен в ветке PR9**, не доставлен в main. [PR9](https://github.com/aleksandradovgopolova-boop/garden/pull/9) открыт на `45d39c0de94bf489e523594cc37955dcf6187d76`, база `codex/garden-p0-foundation`; PR6 также открыт. Исходный main `9ffe943a` остаётся отдельным состоянием.

Установлен выпуск **4.9.3**, тег `v4.9.3`, parent `ad16611cec1ca65a659f597f7b3b0436df8e78b8`. Повторно проверены `.ai/managed/VERSION` и SHA256 всех **679** managed файлов: расхождений с checksum ledger и файлами чистого тега parent нет. Основание установки/настроек: [installation evidence](https://github.com/aleksandradovgopolova-boop/garden/blob/45d39c0de94bf489e523594cc37955dcf6187d76/internal/engineering/ai-ops/installation-2026-10-05.md).

По журналу установки: Codex/generic, восемь контуров и protected paths, диапазон `>=4.9.3,<4.9.4`, auto_update=false; план Place → Save → Leave → Return; pointers к владельческим источникам вместо второй документационной истины. Пять валидаторов, doctor, next и strict parallel прошли; 161 Markdown без ошибок, 18 тестов. Эти локальные команды в учётном шаге повторно не запускались. GitHub API независимо подтверждает **восемь SUCCESS** на SHA PR9.

| Событие 05.10, Europe/Moscow | Время | Основание | От ветки установки |
|---|---|---|---|
| Ветка установки создана | 13:58:23 | Переданный журнал установки | Начало наблюдаемого окна |
| PR9 создан | 14:07:53 | API createdAt | 9м30с |
| Финальные проверки Garden завершены | 14:10:36 | API completedAt docs/site | 12м13с |
| Последняя из всех восьми проверок завершена | 14:10:41 | API completedAt feature catalog | **12м18с** |

Это время от создания ветки, а не автоматически T0 первого часа: точная метка запроса установки, помощь человека и паузы не пересчитаны. Tokens/cost/model version — unknown; doctor 3120 startup tokens — **оценка**, не фактическое потребление. По передаче, внешние model API не вызывались и глобальные Codex prompts не менялись.

Установка потребовала исправления child-копии CI: пустое GitHub expression в комментарии upstream `templates/ci/ai-ops-update.yml:166` привело к [failure run37300910173](https://github.com/aleksandradovgopolova-boop/garden/actions/runs/37300910173), без jobs. Источник шаблона и отсутствие jobs перепроверены; точный текст серверной ошибки сообщён журналом установки. Child-комментарий исправлен, managed package сохранён. Upstream в этом учётном шаге **не исправлен**.

Два наблюдения собраны штатным `kit_feedback.collect` из отдельной owned временной копии Garden в этот worktree. Статус — **delivered**, а не resolved/accepted/became_work:
- [obs-2026-10-05-шаблон-ai-ops-update-yml-0f590832](../findings/from-children/obs-2026-10-05-шаблон-ai-ops-update-yml-0f590832.yaml).
- [obs-2026-10-05-garden-с-ещё-не-реализов-0297e686](../findings/from-children/obs-2026-10-05-garden-с-ещё-не-реализов-0297e686.yaml).

Первое — подтверждённый дефект шаблона CI, p1. Второе — трение класса EXISTING_PRODUCT, p2: inferred-класс при ещё не реализованном приложении, с честной оговоркой в паспорте; это не доказанный дефект классификатора.

**Итог S01:** реальная работа и установка документированы; Kit в PR проверен. Первый принятый продуктовый результат после установки, независимое ревью, acceptance/rollback и измеренный эффект пока не подтверждены. Первый час и полные полевые цели не закрываются. Документы и observations сохранены локально в отдельном worktree; коммит/merge не выполнялись.


## Доставка в main — обновление после поручения владельца

GitHub API независимо подтверждает:

| Этап | Merge05.10, Europe/Moscow | Merge SHA |
|---|---|---|
| P0, [PR6](https://github.com/aleksandradovgopolova-boop/garden/pull/6) | 14:27:45 | 966348f49f366d77782f42c0636ac5e89b7ffe94 |
| Kit4.9.3, [PR9](https://github.com/aleksandradovgopolova-boop/garden/pull/9) | 14:29:17 | d94b5d62380f3114fc6aa2281c87d99dc9a6aacf |
| CI compatibility, [PR15](https://github.com/aleksandradovgopolova-boop/garden/pull/15) | 14:34:51 | da4b8b1d1674feaabcdf0592b5f858ae2f500269 |

PR9 перед merge изменил head на315fcff1ddbeed6aa01aab81200ac2fbeadfe3f5; прежние часы/проверки45d39c0 описывают прежний снимок и не подменяют merge head. Итоговый main закреплён отдельной read-only копией; SHA256 всех679managed файлов совпадают с ledger, версия4.9.3.

На итоговом main девять проверочных workflows SUCCESS: Garden quality, validate, lint, feature-catalog, feature-coverage, secret-scan, record, scorecard, CodeQL. Это не включает дополнительные Dependabot-update runs, один из которых при чтении ещё выполнялся. Поэтому «все Actions завершены» не заявляется.

От ветки установки13:58:23 до mergePR9 — **30м54с**, до mergeCIсовместимости — **36м28с**. Ранее12м18с — только до первых восьми зелёных checks на прежнем PRhead. От запросаP0в13:32:16 до его merge — **55м29с**. Часы календарные с ожиданием решения владельца, не active time и не время получения первого результата.

Повторно прочитаны failed logs:
- [Run37303245290](https://github.com/aleksandradovgopolova-boop/garden/actions/runs/37303245290): feature-coverage пытался pushbaseline в main, получил GH006/Protected branch update failed. PR15 оставляет contents:read, исходный baseline принят через PR, proposed baseline сохраняется artifact. Ноль verified orphans — по переданному результату, не повторный запуск вычисления здесь.
- [Run37303456300](https://github.com/aleksandradovgopolova-boop/garden/actions/runs/37303456300): CodeQLjavascript-typescript не нашёл кода, exit32. Child настроен на Python; итоговый [CodeQLrun37303853483](https://github.com/aleksandradovgopolova-boop/garden/actions/runs/37303853483) SUCCESS.

Нативные наблюдения доставлены локально, не resolved upstream:
- [obs-2026-10-05-feature-coverage-workflo-cb759390](../findings/from-children/obs-2026-10-05-feature-coverage-workflo-cb759390.yaml).
- [obs-2026-10-05-доставленный-codeql-defa-aa177323](../findings/from-children/obs-2026-10-05-доставленный-codeql-defa-aa177323.yaml).

По передаче репозиторий PUBLIC, Pages отключён, branch protection сохранён; настройки в этом обновлении отдельно не перечитывались. Прежний empty-expression childfix сохранён. Исправления Garden не меняют parenttemplates автоматически.

**Вердикт:** установлен AND merged-main. Полная reference-productqualification остаётся pending: bounded applicationchange/research/независимыйreview/rollback ещё не подтверждены. Установка и исправление совместимостиCI не означают реализованный Gardenapplication. Запись локальная, без коммита/merge в Kit.


## Подтверждение полезности владельцем

Записано 2026-10-05T14:41:00+03:00. В текущем чате владелец ответила **«да»** на вопрос о полезности результатов во всех трёх репозиториях: Garden — ревью/P0 и понимание следующего шага; Personal Cosmic Book — обзор качества и план; dashboard-kit — исправление поиска и удобство результата. Ответ принят как owner acceptance перечисленных результатов.

Отдельных оговорок не сообщено. Объём подсказок/исправлений, активные минуты помощи, стоимость и токены остаются unknown: отсутствие оговорок не означает нулевую помощь. Это подтверждение полезности, не независимое техническое review, не измеренный причинный эффект Kit и не автоматический pass всех требований first-hour/reference-product qualification.


## Уточнение владельца об объёме помощи

Владелец сообщила: **«исправлений не было, подсказок тоже по факту»**. Для Garden, Personal Cosmic Book и dashboard-kit количество корректирующих подсказок и исправлений со стороны владельца — **0 по её самоотчёту**. Выбор репозитория/приоритета и разрешения на merge — решения владельца, не корректирующая помощь. Прежний unknown для этих двух видов помощи заменён этим сообщением; active human minutes, стоимость, токены и точные метки первого результата остаются unknown. Это не инструментальный замер и не подтверждение всех остальных условий квалификации.
