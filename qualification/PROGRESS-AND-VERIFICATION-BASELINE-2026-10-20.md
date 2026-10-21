# Доставленные срезы и исходные измерения — 20.10.2026

Срез на `main cde7f5fbff23387cfe3fbfcc915661cdd97760b8`, дерево
`16e09390c1a46236d2e643776679403739e961ed`. Локальная копия сверена по Git tree SHA.
Это сверка уже выполненного и публикация существующих наблюдений, не новый benchmark.
Все исходы направлений #1321/#1322 и полевые критерии сохраняются открытыми.

## Завершённая работа плана

`delegation-owner-fencing` выполнена [PR1324](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1324):
поздний ответ прежней автоматической попытки не перезаписывает отчёт и не снимает
заявку нового держателя. Приёмка ограничена границами допуска и записи состояния;
уже допущенный внешний эффект не отменяется задним числом. Это не автоматическое
переназначение, общее восстановление или гарантия жёсткого USD-лимита.

Итоговый head `2b519453767893011591edf0852e36f1cb53b2ba`, merge
`c585e447d40cdbbdcb2ef779f4f8ede26202cfab`, время merge 19.10, 13:55:45 UTC.
Свежая вычитка GitHub 20.10: package-quality — 13 SUCCESS, pr-smoke — 3 SUCCESS,
docs — 1 SUCCESS; всего 17, пропуски не засчитаны. Источники:
[package-quality](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39247575401),
[pr-smoke](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39247575418),
[docs](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39247575469).
Связь head перепроверена по PR и API runs; после merge GitHub возвращает пустой
pull_requests в run, поэтому эта пустота сама по себе не является историческим допуском.

Сохранённое независимое статическое review всей delta: `review1324-independent.json`,
head/base совпадают с PR, verdict NO_FINDINGS. Оно не подтверждает исторические тесты;
их квитанции проверены отдельно. Наблюдения: 3 RED на прежнем коде; затем 156 targeted,
88 core и 13 public-contract PASS. Эти числа относятся к историческим прогонам,
повторного запуска в текущей сверке нет. Источник требований и границ:
[Change Brief](CHANGE-BRIEF-delegation-owner-fencing-2026-10-19.md).

## Baseline проверок: что действительно измерено

Сведены 17 существующих запусков GitHub Actions и 111 jobs. Это разные задачи и SHA,
включая неуспешную попытку #1342; из них нельзя собрать одну сквозную работу или
сравнение до/после. Времена ниже — created_at → последний completed_at jobs этого
workflow. Длительности параллельных jobs не суммируются; это не CPU и не счёт провайдера.
Исходные start/end, очереди, шаги и labels доступны в API каждого run и его jobs.

| Run | Workflow | Head | Jobs | Начало UTC | Конец UTC | Wall, с | Состояния jobs |
|---|---|---|---:|---|---|---:|---|
| [39307085179](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39307085179) | pr-smoke | `59a8b679de8ea935c0c277723aee07370096f33b` | 3 | 2026-10-19T18:58:50Z | 2026-10-19T19:00:28Z | 98 | success |
| [39307085182](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39307085182) | docs | `59a8b679de8ea935c0c277723aee07370096f33b` | 1 | 2026-10-19T18:58:50Z | 2026-10-19T18:59:10Z | 20 | success |
| [39307085252](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39307085252) | package-quality | `59a8b679de8ea935c0c277723aee07370096f33b` | 13 | 2026-10-19T18:58:50Z | 2026-10-19T19:04:17Z | 327 | success |
| [39334920943](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39334920943) | pr-smoke | `7a441c90e35e2b79683dda07b043544891211674` | 3 | 2026-10-19T22:26:07Z | 2026-10-19T22:27:40Z | 93 | success |
| [39334920960](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39334920960) | package-quality | `7a441c90e35e2b79683dda07b043544891211674` | 13 | 2026-10-19T22:26:07Z | 2026-10-19T22:31:36Z | 329 | success |
| [39334921024](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39334921024) | docs | `7a441c90e35e2b79683dda07b043544891211674` | 1 | 2026-10-19T22:26:07Z | 2026-10-19T22:26:27Z | 20 | success |
| [39335870703](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39335870703) | pr-smoke | `cc84c8f09dc65125bfca59d740407ed03e586ac3` | 3 | 2026-10-19T22:34:11Z | 2026-10-19T22:35:42Z | 91 | success |
| [39335870716](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39335870716) | package-quality | `cc84c8f09dc65125bfca59d740407ed03e586ac3` | 13 | 2026-10-19T22:34:11Z | 2026-10-19T22:39:47Z | 336 | success |
| [39335870834](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39335870834) | docs | `cc84c8f09dc65125bfca59d740407ed03e586ac3` | 1 | 2026-10-19T22:34:11Z | 2026-10-19T22:34:29Z | 18 | success |
| [39336984666](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39336984666) | docs | `68538cd43790465792d6030a429ebe64fb155d74` | 1 | 2026-10-19T22:43:58Z | 2026-10-19T22:44:18Z | 20 | success |
| [39336984711](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39336984711) | pr-smoke | `68538cd43790465792d6030a429ebe64fb155d74` | 3 | 2026-10-19T22:43:58Z | 2026-10-19T22:45:01Z | 63 | success |
| [39336984712](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39336984712) | package-quality | `68538cd43790465792d6030a429ebe64fb155d74` | 13 | 2026-10-19T22:43:58Z | 2026-10-19T22:47:59Z | 241 | success |
| [39337913195](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39337913195) | package-quality | `2b7da40a199e1ea51b7a4bc09116dfd3969205b8` | 13 | 2026-10-19T22:52:20Z | 2026-10-19T22:57:16Z | 296 | success |
| [39337913200](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39337913200) | pr-smoke | `2b7da40a199e1ea51b7a4bc09116dfd3969205b8` | 3 | 2026-10-19T22:52:20Z | 2026-10-19T22:53:58Z | 98 | success |
| [39337913207](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39337913207) | docs | `2b7da40a199e1ea51b7a4bc09116dfd3969205b8` | 1 | 2026-10-19T22:52:20Z | 2026-10-19T22:52:36Z | 16 | success |
| [39339268201](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39339268201) | package-quality | `d96ab818aedb22600b2d68c09519b0932357c9c1` | 13 | 2026-10-19T23:04:42Z | 2026-10-19T23:10:16Z | 334 | success |
| [39342437575](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/actions/runs/39342437575) | package-quality | `f82a0c4276b369f50a65c994ba588aabb2018a77` | 13 | 2026-10-19T23:34:44Z | 2026-10-19T23:40:29Z | 345 | failure, success |

В отдельном примере PR1327, head `59a8b679de8ea935c0c277723aee07370096f33b`:
17 jobs трёх workflows, CI wall 327 с. Критическая job selftests-m: очередь 3 с,
исполнение 323 с, тестовый шаг 313 с, установка pip 4 с. Это один PR, не норматив.

| Этап | Наличие источника | Граница |
|---|---|---|
| Локальные targeted | 156 PASS, 140,025 с, fencing | Один технический срез |
| Core smoke | 88 PASS, 26,674 с, fencing | Короткий охват, не весь pytest |
| Очередь PR/CI | Job created/start; dispatch отдельно | Не активное время человека |
| Исполнение CI | Run/job/step timestamps, head и attempt | Не CPU/оплаченные минуты |
| Установка зависимостей | Шаги pip | Cold/warm и hit/miss неизвестны |
| Сборка | Docs build | Не сборка дочернего продукта |
| Интеграционные проверки | Public contracts и process contracts | PostgreSQL дочки не измерен |
| Ещё нет сквозного измерения | local full, hooks, browser/e2e, review, release gates, deploy, post-deploy | Семь категорий; наличие отдельных старых проверок не закрывает этот baseline |

Семь категорий имеют хотя бы один ограниченный источник, семь остаются без него
в данном наборе. Это охват инвентаризации, не процент готовности #1321.
Сквозная длительность, p50/p95, CPU/RAM, полная цена и активные минуты — unknown.

Причины известных повторов:

- PR1342: первый head `f82a0c4276b369f50a65c994ba588aabb2018a77`, run39342437575,
  345 с. Fixture потерял saved policy flags, а except:pass превысил замороженную базу.
  Это реальные исправления, не доказанный flake; новый head требует нового CI.
- PR1324: rebase `c508dba19e4de4077093c0c0991396c7fd84c156` → `2b519453...` из-за
  новой базы; семь файлов побайтно сохранены, финальный CI нового head выполнен.
- RED → GREEN — намеренная проверка регрессии, не лишний аварийный повтор.
- Для остальных запусков причина повторов unknown; attempt=1 не означает отсутствия
  запусков прежних source revisions. Сэкономленные секунды не вычисляются.

Ранее начатый ABBA остановлен ресурсным правилом: сохранились A=41,670 с и B=3,581 с,
по одному наблюдению, последовательность не завершена. Отношение/ускорение не объявляется.
Отдельная повторная регистрация осталась без новых samples: на 20.10, 04:46:38 UTC
допуск отказал при наличии чужого vitest PID28644, даже при CPU=0; прочие prerequisites
были выполнены. Это исторический снимок, не утверждение текущей нагрузки.
Процесс, ресурсное правило и регистрацию не меняли. Следующий benchmark начинается
только после свежего штатного допуска, с сохранением остановленных попыток.

## Пять дочек: доставка политики отдельно от наличия кода в main

Ниже датированный аудит 20.10, 00:05:31 UTC, не обещание текущего remote HEAD.
Повторный GitHub-доступ к ii-sreda в этой сессии вернул 404/422; доступ приложения
также не дал состояния. Это ограничение текущего канала, не отсутствие репозитория.
Локальный ii-sreda уже имеет другой HEAD; две копии не смешиваются.

| Дочка | Remote SHA на момент аудита | Kit | Профиль | Следующий проверяемый шаг |
|---|---|---|---|---|
| niti | `d14c2bf00a813a1c68399c71598cba964b6ed217` | 4.9.2 | отсутствует | Подтвердить workspace-команды и профиль на чистой актуальной базе; локальная копия устарела. |
| ii-sreda | `f6385ad927b7238f5ed71cda1245a65ef2f941f4` | 4.11.1 | draft | Сопоставить профиль с PostgreSQL, coverage и browser jobs; сохранить CI_RUNNER и существующие gates. |
| ai-ops-cockpit | `fd08be3187a632df979ec5498b08389d8d2426f5` | 4.9.2 | draft | Дополнить карту проверок Electron/IPC/security и packaged smoke; npm test не заменяет их. |
| dashboard-kit | `f5e63f7c243b38ba9f6e2ec5c1bca0603f77fe6b` | 4.3.2 | draft | Сохранить полный custom runner; безопасное сужение Python/Chrome-команд не доказано. |
| ii-quest | `97eba804ae489336776e209f90405d0e20cf0fa0` | 3.36.10 | confirmed | Проверить продуктовый CI и происхождение версии; диапазон >=3<4 запрещает автоматический major4. |

Последний опубликованный пакет 4.11.1 (`99b254425e3760aaf4a7ca6e58f727a73a134f4c`)
предшествует исправлениям обхода графа #1333/#1337. Они не считаются доставленными
в дочках по одному номеру 4.11.1. Нужен отдельно подготовленный выпуск и штатное
версионированное обновление; неопубликованный main этим срезом не устанавливается.
У всех пяти рассмотренных PR отсутствует сохранённое решение выбора тестов на точном
diff: успешные CI не доказывают принятие новой policy. Отличия локальных шаблонов
не объявляются несанкционированным drift; dirty-копии и адаптации раннеров сохраняются.

## Реальные работы и ближайшая работа

Основная когорта #1243 по последнему опубликованному срезу — 0; локально найденная
уже начатая работа сценариев не регистрируется задним числом. Её допущенные и
отказанные проверки учитываются отдельно, неизвестные минуты/расходы не равны нулю.
Подробности добавлены в [журнал](CHILD-VALUE-JOURNAL-2026-10-06.md).

1. Убрать `delegation-owner-fencing` из активного плана и закрыть только #1344 после
   доставки этой сверки; общий #1322 остаётся открытым. Под ним остаётся конкретная
   следующая работа `automatic-work-recovery-proof`: реальный старт/прерывание/продолжение
   с уже построенными механизмами. Запись не даёт разрешения на новые paid/native вызовы.
2. Продолжить #1343/#1321 по семи отсутствующим категориям на одной разрешённой
   реальной работе: timestamps, base/head, версии, ресурсный допуск, причины повторов.
   Не повторять уже влитые fixes или начинать новый искусственный planner-сценарий.
3. Следующий новый продуктовый запрос в выбранных дочках зарегистрировать до исполнения
   по существующему протоколу. Начатые сценарии и repair #1142 — не новые primary работы.
   Приёмка владельцем, техническая доставка и post-release outcome остаются разными событиями.

## Источники сверки

GitHub-ссылки выше закрепляют проверяемые CI и PR. Дополнительные исторические
квитанции прочитаны из сохранённых локальных outputs без их перезаписи:

- `baseline1321-source-consolidation/consolidated.json` — SHA256 `0e774d4e19c9933f86b901e44c614da2beb295f674a6e74ba020e94d53d483ed`.

- `child-adoption1321/report.json` — SHA256 `2c3d85c0ca696afb5c07164e47d924f45631fc35fbde22cf4c13fcaaa4ce6358`.

- `review1324-independent.json` — SHA256 `8f038981234254c4357fc3c0f7473f7c939f481bd755fa59b7dfe6da34cdd1ec`.

- `abba1321-readonly-admission-20261020-044638.json` — SHA256 `7f1e2e69a5c256664a81b43d979c1b9a6313b181c4f09483ad6f62a570b4066f`.

Локальные хэши фиксируют происхождение сводки, но не заменяют недоступные первичные данные.
