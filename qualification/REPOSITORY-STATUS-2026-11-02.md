# Состояние AI Ops Kit — 02.11.2026

## Источники и охват

Первичный полный срез GitHub **09:36:23 UTC / 12:36:23 МСК**: **32 open issues,
17 open PR (9 draft, 8 non-draft)**. Это новый запрос с пагинацией, не перенос
числа32 из предыдущего аудита. Реестр ниже описывает именно эти32 карточки;
#1445 отдельно признана фактически завершённой. Последующие административные
изменения отражает PR #1456; числа среза не переименовываются в текущие.

Main: `146e0c3f9586281833a50b25a07b9837c181d630`, после #1465/#1470.
Сверены все open issues, их timeline/comments, все open PR, последние merged PR,
реестры, план/история, ROADMAP, README, AGENTS и ARCHITECTURE. В readout нет новых
тестов моделей, rollout, изменения trust, merge или релиза. Не редактируются
отклонённые PR descriptions #1425/#1455/#1458. README/EN/RU/CONTRIBUTING и
коммерческий контакт #1471 принадлежат отдельным владельцам.

## Опубликовано и следующий состав

[v4.12.0](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/releases/tag/v4.12.0)
опубликован30.10 в14:01:49 UTC, tag SHA `7acca17f9602c04fc2ec71b04c82544bc9846123`.
[Stock release run41065592704](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/41065592704)
на том же SHA завершён success: full-gate и последующие mutation, drain queue,
owner-layer и создание тега подтверждены. Всего13 jobs success, два штатных PR-only
jobs skipped; последние не названы повторным PASS на release push. Это qualification,
а не доказательство stable нового minor или завершение командной приёмки #1434.

На указанном main после тега10 first-parent merge. Штатный read-only
`release_assembly.assemble(..., milestone=...)` видит12 фрагментов и выводит
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
2. [Pages snapshot09:35:26 UTC](https://aleksandradovgopolova-boop.github.io/ai-ops-kit/data.json)
   на publisher run41421563179 / main146e0c3f: `source=null`,
   `plan_ready=false`, `source_unknown_or_invalid`,
   `unavailable_stage=final_source_consistency`. Успех deploy job не означает
   успех release projection. Старое известное значение target4.13 нельзя выдавать
   за текущий подтверждённый машинный план при таком snapshot.
3. Код collector объединяет несколько финальных проверок в один stage и не
   сохраняет текст пойманного исключения. Поэтому из опубликованного payload
   нельзя доказать, какое именно сравнение/чтение вызвало отказ. Отдельное
   read-only воспроизведение не дало подтверждённого финального receipt после
   потери exec-транспорта; его исход остаётся uncertain, повтор не выполнялся.
   Источник не подставлялся, проверки не отключались. Нужна завершённая диагностика,
   затем решение о разрешённом исправлении; это не повод переписывать policy.
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
- #1193: server merge-block приватной ИИ-среды не доказан; свежий GET02.11 — HTTP403.
- First-hour/экономические/learning/delegation field proofs не закрыты. Последний
  полный экономический readout19.10 имел primary0; отсутствие новых доказательств
  не позволяет засчитать exploratory/CI-only работы проспективной выборкой.

## Реестр карточек исходного среза

Все32 имели GitHub OPEN на момент среза. DONE ниже — фактический результат,
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
| [#1401 — объявленные обязательные проверки сходятся с защитой main](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1401) | Расхождение защиты сохраняется: actual10/declared12, docs/build и security-scan отсутствуют. Штатные17 checks не отменены. |
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
| [#1446 — автоматически пересчитывать выпуск; приёмка #1439](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1446) | 1449/1465 merged, общий контракт не завершён. Старые8 CI bindings не приняты; Pages source=null/final_source_consistency. Recovery implementation не разрешена. |
| [#1447 — эпик проверенного состава и доставки выпуска](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1447) | Первый исход4.12 подтверждён; второй автоматический verified-reconcile не завершён. Целевой4.13 не готов. |
| [#1451 — Кит показывает число установленных и активных проектов с проверяемым охватом](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1451) | 1455/1459 merged;1463 draft local consistency не authenticity/activity proof. Provenance/dated update/product activity/coverage остаются. |

## Открытые PR исходного среза

Последние check-runs каждого имени на зафиксированном head, не merge admission:
base/политика/независимое review должны оцениваться заново. Девять draft имеют
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
