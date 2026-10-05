# Исторический пул для пилота — 05.10.2026

Это рамка кандидатов до будущих наблюдений, не доказанная сопоставимость и не контроль без Kit. Источник — GitHub merged PR (ii-sreda: последние 100, cockpit: все 66), получено 05.10.2026. Список сохранён до набора новых работ. Живой main ii-sreda уже получил PR1096 после зафиксированного снимка; SHA ниже обозначают снимки анализа, а не обещание неизменного main.

Правило отбора: последние 12 по mergedAt PR, меняющие поведение продукта; исключены Kit/CI-only/план/описание приёмки/анализ. Исторический WorkItem устанавливается по исходному запросу перед подбором: связанные PR объединить, их нельзя объявлять отдельными работами. При объединении пул содержит меньше 12 независимых работ — это честное ограничение, не повод дробить. Группировка ещё не выполнена; до сопоставления заполнить historical_work_id / request / все связанные PR / max mergedAt / источник полноты. Негруппированный или неполный кандидат не может быть paired. Типы ниже предварительны по title; сложность, реальный человек-исполнитель и runtime unknown до проверки источников. GitHub author — только автор PR.

## Proektnyy-ofis/ii-sreda

Снимок main: `23c61f600f73b527131f75443b8c733373056b11`. README/package.json подтверждают web + backend для ii-sreda и Electron desktop для cockpit.

| PR / запрос | Created UTC | Merged UTC | GitHub author | Файлы (не сложность) | Предварительный тип |

|---|---|---|---|---|---|

| [#1092: I12: reject categorical claims with unverified edition](https://github.com/Proektnyy-ofis/ii-sreda/pull/1092) | 2026-10-04T19:24:29Z | 2026-10-04T19:31:12Z | timofeyrsk | 6 | fix |

| [#1091: I12: address permit grounds and exceptions in memory](https://github.com/Proektnyy-ofis/ii-sreda/pull/1091) | 2026-10-02T13:43:25Z | 2026-10-02T13:54:08Z | timofeyrsk | 8 | fix |

| [#1090: Fix one-pager DOCX source matching for suffix labels](https://github.com/Proektnyy-ofis/ii-sreda/pull/1090) | 2026-10-02T13:06:17Z | 2026-10-02T13:18:13Z | timofeyrsk | 4 | fix |

| [#1088: Cover legal claim wording and negative edition evidence](https://github.com/Proektnyy-ofis/ii-sreda/pull/1088) | 2026-10-02T12:30:17Z | 2026-10-02T12:36:08Z | timofeyrsk | 7 | fix |

| [#1087: Avoid false legal-evidence rejection in I12](https://github.com/Proektnyy-ofis/ii-sreda/pull/1087) | 2026-10-02T12:07:28Z | 2026-10-02T12:17:03Z | timofeyrsk | 7 | fix |

| [#1086: Guard I12 premise and legal source category](https://github.com/Proektnyy-ofis/ii-sreda/pull/1086) | 2026-10-02T11:48:35Z | 2026-10-02T11:57:14Z | timofeyrsk | 6 | fix |

| [#1085: Treat conditional current-law wording as hypothetical](https://github.com/Proektnyy-ofis/ii-sreda/pull/1085) | 2026-10-02T09:59:03Z | 2026-10-02T11:25:59Z | timofeyrsk | 4 | fix |

| [#1084: Normalize nested one-pager risk and action lists](https://github.com/Proektnyy-ofis/ii-sreda/pull/1084) | 2026-10-02T09:41:26Z | 2026-10-02T09:46:30Z | timofeyrsk | 5 | fix |

| [#1083: Guard legal one-pager construction-start claims](https://github.com/Proektnyy-ofis/ii-sreda/pull/1083) | 2026-10-02T09:14:34Z | 2026-10-02T09:21:19Z | timofeyrsk | 6 | fix |

| [#1081: fix: дашборд PDF на одном A4 для малого набора](https://github.com/Proektnyy-ofis/ii-sreda/pull/1081) | 2026-10-02T08:30:31Z | 2026-10-02T08:37:58Z | timofeyrsk | 4 | fix |

| [#1075: DOCX one-pager: remove verified duplicate legal sources](https://github.com/Proektnyy-ofis/ii-sreda/pull/1075) | 2026-10-01T15:09:35Z | 2026-10-01T15:21:36Z | timofeyrsk | 6 | fix |

| [#1074: Fit one-pager DOCX to a readable A4 page](https://github.com/Proektnyy-ofis/ii-sreda/pull/1074) | 2026-10-01T14:42:39Z | 2026-10-01T14:57:31Z | timofeyrsk | 9 | fix |


Начало/полезный результат/вмешательства/переделки/evidence/outcome: **unknown до чтения соответствующих источников**, не нули. createdAt → mergedAt вычислимо, но это PR lifetime, а не время выполнения запроса.

## aleksandradovgopolova-boop/ai-ops-cockpit

Снимок main: `3633db0b33b175683f9b1334fc51b39fd090be6f`. README/package.json подтверждают web + backend для ii-sreda и Electron desktop для cockpit.

| PR / запрос | Created UTC | Merged UTC | GitHub author | Файлы (не сложность) | Предварительный тип |

| [#69: feat(shortcuts): горячая клавиша скрытия/показа полки виджетов](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/69) | 2026-09-14T15:29:45Z | 2026-09-15T12:43:33Z | aleksandradovgopolova-boop | 7 | feature |
| [#68: feat(settings): переключатель светлой и тёмной темы](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/68) | 2026-09-14T15:27:58Z | 2026-09-15T12:38:14Z | aleksandradovgopolova-boop | 5 | feature |
| [#72: feat(workspace): предупреждение о пропущенных плитках при импорте](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/72) | 2026-09-15T08:04:33Z | 2026-09-15T08:09:57Z | aleksandradovgopolova-boop | 3 | feature |
| [#71: feat(workspace): экспорт и импорт рабочего места](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/71) | 2026-09-15T07:14:47Z | 2026-09-15T07:59:48Z | aleksandradovgopolova-boop | 7 | feature |
| [#66: Перетаскивание рабочих мест мышью в настройках](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/66) | 2026-09-14T13:58:55Z | 2026-09-14T14:13:38Z | aleksandradovgopolova-boop | 5 | feature |
| [#65: feat(catalog): поиск по каталогу помощников](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/65) | 2026-09-14T12:37:05Z | 2026-09-14T12:44:07Z | aleksandradovgopolova-boop | 4 | feature |
| [#56: Полка виджетов: состав списком + виджет «Свободно»](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/56) | 2026-09-11T10:59:02Z | 2026-09-11T11:08:14Z | aleksandradovgopolova-boop | 1 | feature |
| [#54: feat(terminal): подтверждать закрытие плитки с живым процессом (без tmux)](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/54) | 2026-08-31T08:35:11Z | 2026-08-31T08:39:04Z | aleksandradovgopolova-boop | 4 | feature |
| [#50: feat: вход в настройки из шапки приложения](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/50) | 2026-08-24T07:08:42Z | 2026-08-24T07:11:58Z | aleksandradovgopolova-boop | 2 | feature |
| [#46: Настройки, полка виджетов и уведомления, когда помощник ждёт](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/46) | 2026-08-15T16:50:00Z | 2026-08-15T16:50:57Z | aleksandradovgopolova-boop | 17 | feature |
| [#43: Значки от Claude Code на плитке и починенная проверка плашек](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/43) | 2026-08-15T15:54:35Z | 2026-08-15T16:03:38Z | aleksandradovgopolova-boop | 11 | feature |
| [#41: Первые шаги: пять подсказок, которые закрываются действием](https://github.com/aleksandradovgopolova-boop/ai-ops-cockpit/pull/41) | 2026-08-15T15:42:58Z | 2026-08-15T15:43:43Z | aleksandradovgopolova-boop | 12 | feature |

Начало/полезный результат/вмешательства/переделки/evidence/outcome: **unknown до чтения соответствующих источников**, не нули. createdAt → mergedAt вычислимо, но это PR lifetime, а не время выполнения запроса.

## Экспозиция и ограничения

В cockpit обновления Kit до этих продуктовых PR видны в PR40/48/51/52/55/57/58/67; в ii-sreda ранее был owner-led прогон 16.09 и последующая доставка 4.9.3 (PR1095). Точная установленная версия на каждый исторический запрос проверяется по его исходному SHA/манифесту, а не по текущему main. Runtime/model не выводятся из author.

В ii-sreda пул сосредоточен на исправлениях документации продукта/качества генерации одного исполнителя, в cockpit — на UI-функциях другого. Сравнение проводится ВНУТРИ дочки и страты, а не между продуктами. У будущего другого исполнителя/типа может не оказаться пары; правило unmatched определено в протоколе. Наличие старого Kit и календарные изменения продукта ограничивают причинные выводы. Исторические PR с общим запросом или зависимыми исправлениями не являются независимыми наблюдениями.

Файлы локальной выгрузки `/tmp/ii-sreda-baseline-prs-20261005.json` и `/tmp/cockpit-baseline-prs-20261005.json` — вспомогательные: устойчивый источник строк — ссылки на PR и опубликованные ISO даты выше. Наблюдения будущего пилота отсутствуют.
