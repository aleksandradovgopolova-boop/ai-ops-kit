# Состояние AI Ops Kit — 02.11.2026

## Источники и охват

Свежая полная сверка GitHub **2026-11-02T12:10:32.496468+00:00**: **32 open issues,
17 open PR (9 draft, 8 non-draft)**. Коллекции issues/PR прочитаны с per_page=100:
49 записей issues включают 17 PR, отдельный PR endpoint возвращает те же17;
лимит страницы не достигнут. Сверены все32 карточки и свежие check-runs каждого
открытого head. Утренний полный audit09:36 с timeline/comments сохранён как
источник исторической приёмки, но его изменяемые факты обновлены.

Main: `073d1bfb3ab0cabc884f58fca69e8563b357edeb`, после merge #1472 в11:56:23UTC.
RU/EN README, onboarding и примеры #1472 сохранены без изменений; #1471 с контактом
остаётся отдельным draft. Сверены план/история, ROADMAP, README, AGENTS и ARCHITECTURE.
Нет новых модельных вызовов, rollout, изменения trust, merge в main или релиза.
Отклонённые descriptions #1425/#1455/#1458 не редактируются.

Прежний audit-owner был остановлен пользователем: штатный read_thread подтвердил
turn01a19b9d со status=interrupted, error=null. Работа продолжена с сохранённого
commit058c6ee2; исходный temp-каталог и автономный bundle сохранены отдельно.
PR #1456 продолжается с сохранением его истории, без новой дублирующей карточки/PR.

## Опубликовано и следующий состав

[v4.12.0](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/releases/tag/v4.12.0)
опубликован30.10 в14:01:49 UTC, tag SHA `7acca17f9602c04fc2ec71b04c82544bc9846123`.
[Stock release run41065592704](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/41065592704)
на том же SHA завершён success: full-gate и последующие mutation, drain queue,
owner-layer и создание тега подтверждены. Всего13 jobs success, два штатных PR-only
jobs skipped; последние не названы повторным PASS на release push. Это qualification,
а не доказательство stable нового minor или завершение командной приёмки #1434.

На указанном main после тега11 first-parent merge. Текущий машинный
Pages-план содержит13 фрагментов и выводит
**4.13.0 (minor)**. Его legacy `ready=true` означает наличие материала для сборки;
это **не** `plan_ready`, `release_ready`, дата или разрешение публикации. Изменения
из открытых PR не становятся обязательными для4.13 лишь потому, что открыты.

## Release-critical и P1 диагностика

1. Подтвердить стабильный source snapshot и exact CI-связи по действующему
   контракту. Старые восемь bindings после1453/1452/1457/1449/1455/1459/1460/1462
   не восстановлены текущим validator.1465 сохраняет будущий архив до потери
   association, а не восстанавливает утраченную историю. Найденные24 исходных
   workflow logs и synthetic merge/Git parents — кандидаты evidence, не принятый
   новый recovery-контракт. Его реализация требует отдельного решения владельца.
2. [Свежий Pages snapshot12:01:11 UTC](https://aleksandradovgopolova-boop.github.io/ai-ops-kit/data.json)
   ([publisher run41440750899](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/41440750899))
   подтверждает `source.sha=073d1bfb`, target `4.13.0`, `plan_ready=true`,
   `composition_available=true`, но `release_ready=false` и
   `implementation_evidence_complete=false`. Blockers:
   `implementation_ci_incomplete`, `final_release_evidence_required`,
   `release_bump_pending`. Все11 post-tag implementation записей имеют
   `merged_change_observed=true`, `ci_observed=false`; архив содержит1361/1425,
   что не восстанавливает CI-связи этих11 реализаций.
3. Исторический Pages snapshot09:35:26 на146e0c3f действительно имел
   `source=null`, `source_unknown_or_invalid`, `final_source_consistency`.
   Это больше не текущий статус. Причина конкретного утреннего отказа не доказана;
   из последующего успеха нельзя вывести, какое сравнение ранее не прошло.
   Старый read-only capture оборвался с executor-key transport error и не сохранил
   финальный receipt; его исход остаётся uncertain. Отдельный diagnostics-owner
   исследует этот контур; audit не меняет collector, source, gates или recovery policy.
4. Для конкретного release-кандидата остаются установленный артефакт,
   согласованные owner notes/bump, независимое review, все17 PR checks точных
   head/base и штатные full-gate/actual mutation/release_gate на точном release SHA
   до автоматического тега. Старый nightly, draft skips и author-ready не заменяют их.

## Следующая итерация и внешние блокеры

- #1411/#1467: prepared read-only trace/history, отсутствуют producer links/timestamps.
- #1412/#1464: guarded load typing; это аннотационный срез, не весь adapter strict.
- #1451/#1463: локальная согласованность и корректность времени, не подлинность
  источника и не подтверждённая продуктовая активность.
- #1409/#1461: подготовка ручного CI-measurement, dispatch не выполнялся;
  локальная base/repeat пара была, но не принята как чистый baseline.
- #1434/#1468/#1469: диагностика и неактивный дизайн, не runtime compatibility fix.
  Для Codex0.147.0 readiness=false; независимый tool-deny при hook failure не доказан.
  Trust и required-установка дочки не заменяют natural-language приёмку двух аккаунтов.
- #1193: server merge-block приватной ИИ-среды не доказан; утренний GET02.11 — HTTP403.
- #1401: утренний PAT-срез classic protection показал actual10/declared12. Свежая
  проверка через GitHub connector получила403 Resource not accessible by integration;
  текущее admin-состояние этим доступом не подтверждено, изменение защиты не заявляется.
- First-hour/экономические/learning/delegation field proofs не закрыты. Последний
  полный экономический readout19.10 имел primary0; отсутствие новых доказательств
  не позволяет засчитать exploratory/CI-only работы проспективной выборкой.

## Реестр карточек свежего среза

Все32 имеют GitHub OPEN на момент свежей сверки. DONE ниже — фактический результат,
не синоним слитого отдельного PR. Исторические дубли #1115/#1116/#1183/#1322/#1439
сохраняют полную приёмку и не открываются заново.

| Карточка | Подтверждённый статус / остаток |
|---|---|
| [#1144 — эпик первого часа владельца в трёх проектах](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1144) | Полевой эпик: 0/2; три полных owner-led first-hour не доказаны. |
| [#1145 — эпик пользы для дочек; приёмка #1116](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1145) | Полевой эпик: нет итогового сравнения пользы двух дочек. |
| [#1193 — эпик стиля кода дочек; приёмка #1183](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1193) | 4/5; native hook подтверждён, обязательный server merge-block приватной дочки не доказан; GET02.11 HTTP403. |
| [#1243 — На двадцати–тридцати настоящих работах измерены результат и цена сопровождения](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1243) | Нет подтверждённой основной выборки20–30. Последний полный readout19.10: primary0; exploratory не заменяет prospective. |
| [#1244 — Польза кита оценена сравнением с исходной базой и её ограничениями](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1244) | Ждёт сопоставимых наблюдений, пяти показателей и продуктового решения. |
| [#1256 — первый час в трёх проектах; приёмка #1115](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1256) | in_progress; полезные работы есть, три полных первых часа не зачтены. |
| [#1276 — Владелец видит реальную цену принятой работы и затраты своего времени](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1276) | Методика есть; фактическая цена и active minutes неполны, неизвестное не равно нулю. |
| [#1277 — Прошлый результат помогает киту принять следующее продуктовое решение](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1277) | Нужна реальная полная цепочка урок→рекомендация→решение→следующее наблюдение. |
| [#1278 — Кит завершает разрешённую работу и надёжно передаёт исключения владельцу](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1278) | Нужны принятая реальная bounded работа, вмешательства, исключения/resume и вывод о полномочиях. |
| [#1346 — эпик распределения и восстановления; приёмка #1322](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1346) | Эпик0/3; технические срезы не доказывают весь автоматический путь. |
| [#1348 — доказать восстановление прерванной работы без дублей](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1348) | Следующий proof прерывания/resume; prerequisite fencing уже выполнен. |
| [#1387 — запутанные плохо-покрытые функции краснеют как и крупные](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1387) | Advisory CRAP слит; глобальный measured baseline, coverage/unknown и gate wiring остаются. |
| [#1401 — объявленные обязательные проверки сходятся с защитой main](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1401) | Последний доступный admin-срез09:36: actual10/declared12, docs/build и security-scan отсутствуют. Свежий connector403; изменение настроек не подтверждено. Штатные17 checks не отменены. |
| [#1402 — версия Ruff одна в CI, hooks и dev](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1402) | CI/hooks Ruff0.16.2 против dev>=0.16.8; PR1395 открыт, lint failure. Единого pin/сторожа нет. |
| [#1403 — кит измеряет и ограничивает стоимость контекста](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1403) | 1453 уже merged, HOLD4.12 устарел. Полевая relevance/native prompt+tool reads/Storybook aggregate остаются. |
| [#1404 — спецификация сходится с кодом и тестами, фантомных отметок нет](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1404) | Нет полного converge→работы по недостающим AC и phantom-completion proof. |
| [#1406 — кит видит флот дочек и откатывает обновление безопасно](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1406) | Reach/update есть; полного fleet drift/capabilities, rollback и обязательной репетиции нет. |
| [#1407 — риски автономного агента проверяются эвалами, а не только сторожами](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1407) | Deterministic evals слиты; реальные model/MCP/redaction/exfil и sandbox negatives не доказаны. |
| [#1408 — импорты и структура JS/TS читаются по синтаксическому дереву, а не регулярками](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1408) | AST pilot1426 открыт и имеет fast-2 failure; timing/полнота не завершены, fallback сохранён. |
| [#1409 — у кита есть замеренная база скорости и памяти](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1409) | Локальная base/repeat пара была выполнена, чистота baseline не принята.1425 открыт;1461 draft без dispatch. Actions RSS/repeat не исполнены. |
| [#1411 — один WorkItem виден как trace, без сетевой телеметрии](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1411) | 1467 draft read-only reader/history; producers не дают package/invocation links и timestamps. Полного OTel контракта нет. |
| [#1412 — строгая типизация доведена до публичных контрактов и моделей состояния](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1412) | 1452 router и1460 review state merged.1464 load_guarded draft; adapters и остальные критические модели не закрыты. |
| [#1413 — автономность агента — управляемый уровень, а не тумблер](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1413) | Пять уровней и автоматическое понижение не доказаны; существующие modes не эквивалент. |
| [#1414 — воспроизводимое окружение и быстрее CI через uv (пилот)](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1414) | uv spike: нет принятого численного сравнения и lockfile-решения. |
| [#1415 — названы критерии перехода с JSONL/Git на SQLite](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1415) | Storage spike: нет реалистичного load proof и измеренных SQLite-триггеров. |
| [#1416 — у движка есть стабильный машинный интерфейс под будущий UI](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1416) | Public surface существует; полный контракт будущего UI не доказан. |
| [#1417 — кит поднимается профилем под стек (CORE + capabilities + presets + bundles)](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1417) | Базовые presets есть; полный capability/bundle add сценарий не реализован. |
| [#1434 — Вся команда работает по киту в Claude и Codex без ручного контроля](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1434) | 1462 merged, child1243 merged/required. Codex0.147 SessionStart внутри run_turn; pre-turn ack/tool-deny не подтверждены, readiness=false.1468 diagnostics и1469 design — drafts. |
| [#1445 — Проверенные исправления и накопленные возможности доставлены выпуском 4.12.0](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1445) | ФАКТИЧЕСКИ DONE: v4.12.0 опубликован, stock run41065592704 success на7acca17f. План todo устарел; переносится в историю. |
| [#1446 — автоматически пересчитывать выпуск; приёмка #1439](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1446) | 1449/1465 merged, общий контракт не завершён. Pages12:01: source073d1bfb, plan_ready=true, release_ready=false; CI evidence11 post-tag реализаций неполно. Утренний source=null исторический; причина не доказана. Diagnostics отдельным owner. |
| [#1447 — эпик проверенного состава и доставки выпуска](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1447) | Первый исход4.12 подтверждён; второй полный verified-reconcile не завершён. Текущий машинный план4.13 доступен; release_ready=false. |
| [#1451 — Кит показывает число установленных и активных проектов с проверяемым охватом](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1451) | 1455/1459 merged;1463 draft local consistency не authenticity/activity proof. Provenance/dated update/product activity/coverage остаются. |

## Открытые PR свежего среза

Последние check-runs каждого имени на зафиксированном head, не merge admission:
base/политика/независимое review должны оцениваться заново. Таблица фиксирует
состояние до публикации продолжения #1456; новый head проверяется отдельно в PR. Девять draft имеют
11 success/2 штатных skip и не прошли полный17-check маршрут. Два non-draft
имеют17 success; у шести есть failure. Эти числа не делают их обязательными4.13.

| PR | Head | Режим / текущие checks | Назначение |
|---|---|---|---|
| [#1274](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1274) | `3e38ea8f` | open; failure:1, success:16 | chore(deps): update mypy requirement from >=1.8 to >=2.4.0 |
| [#1352](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1352) | `4428fa1f` | open; failure:1, success:16 | chore(deps): update pre-commit requirement from >=3.5 to >=4.7.0 |
| [#1361](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1361) | `0534de2f` | open; success:17 | ci: еженедельный авто-снос влитых codex-веток |
| [#1371](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1371) | `f28fc143` | open; failure:1, success:16 | perf(security): убрать повторные обходы AST внутри update |
| [#1394](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1394) | `ab6ea38b` | open; failure:1, success:16 | chore(deps): update hypothesis requirement from >=6.168.0 to >=6.170.9 |
| [#1395](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1395) | `79b29e6a` | open; failure:1, success:16 | chore(deps): update ruff requirement from >=0.16.8 to >=0.17.3 |
| [#1425](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1425) | `11754dec` | open; success:17 | feat(devtools): воспроизводимый harness измерения производительности (#1409) |
| [#1426](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1426) | `8e21f91c` | open; failure:1, success:16 | feat(context): opt-in JS/TS AST-пилот (tree-sitter) с fallback на regex (#1408) |
| [#1456](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1456) | `2b17d525` | draft; skipped:2, success:11 | docs(planning): связать работы с текущими карточками без дублей |
| [#1461](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1461) | `e9585580` | draft; skipped:2, success:11 | ci(perf): подготовить ручные RSS/repeat-серии (#1409) |
| [#1463](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1463) | `78fa603b` | draft; skipped:2, success:11 | feat(reach): локальная проверка свидетельств установки |
| [#1464](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1464) | `664197ea` | draft; skipped:2, success:11 | feat(types): различать состояния защищённой загрузки |
| [#1466](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1466) | `acf64d15` | draft; skipped:2, success:11 | docs(release): отразить #1446 и оставшуюся приёмку в ROADMAP |
| [#1467](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1467) | `223b63f2` | draft; skipped:2, success:11 | feat(observability): локальная трасса WorkItem и история пакетов |
| [#1468](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1468) | `dca2fe0e` | draft; skipped:2, success:11 | fix(providers): различать trust и отсутствие native SessionStart |
| [#1469](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1469) | `76409e80` | draft; skipped:2, success:11 | docs(providers): проект двухфазного preflight с запретом native tools |
| [#1471](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1471) | `4df99666` | draft; skipped:2, success:11 | docs(license): добавить почту для коммерческих запросов |

PR #1466 содержит одно уточнение ROADMAP; его смысл принят в продолжении #1456,
вместе с plan/history/architecture. Отдельный дубль не нужен. Исходная ветка и
приёмка1466 сохраняются; объединение не означает merge какой-либо реализации.

## Что было устаревшим

- План:4.12 todo после опубликованного Release; automation todo и ссылка на
  закрытый duplicate1439. Завершённая доставка переносится в history, текущая
  автоматизация ссылается на1446 и остаётся in_progress, следующий delivery —4.13.
- ROADMAP: будущий4.12 и оба исхода недостигнуты; первый fencing тоже описывался
  как предстоящий. Исторические диагнозы стиля29.09 недостаточно отделены от текущего.
- Утренний диагноз source=null устарел: свежий source073d1bfb и plan_ready=true
  подтверждены, но source recovery и release readiness не смешиваются.
- Карточки:1452/1453/1455 названы открытыми; child1243 назван draft;
  performance локальные серии ошибочно NOT_RUN. Исправляется факт без снятия остатка.
- ARCHITECTURE: outcome→learning ещё назван future; нет различия native adapter
  в main, неактивного дизайна и реальной совместимости0.147.0. Trace draft не
  объявляется shipped и OTel по-прежнему не подключён.
- Старый Change Brief4.12 — датированный замысел30.10; его не переписывают задним
  числом, в индексе он помечается историческим. AGENTS содержит историческое
  соглашение для4.11.1; оно не используется как новое разрешение/ослабление4.13.
- В `release-claims.evidence_scopes.compatibility-matrix.obtained_by` осталась
  подпись python39/3.9; фактический floor>=3.12, pipeline3.12/3.13. В этой ветке
  исправляется только описательная строка источника, не значение/обязательность scope.

## Проверка и границы публикации

Целевые plan/history/roadmap/docs регрессии, short core smoke, проверка ссылок и
независимое read-only review выполняются на итоговой delta. Их фактические результаты
и SHA публикуются в PR #1456. Полный локальный профиль и merge admission не заявляются.
README/EN/RU/CONTRIBUTING, коммерческая строка1471, LICENSE, VERSION, runtime/registry
capabilities, CI/security policy и отклонённые описания1425/1455/1458 не изменяются.
Описательная строка evidence scope исправляет имя уже существующего CI-источника.
