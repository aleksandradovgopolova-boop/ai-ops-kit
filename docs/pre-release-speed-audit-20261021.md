# Ускорение Kit перед следующим выпуском

База: `7601abe8a7397f38d3b76ff9965e8f6b62d7d267` (main после #1358), 21.10.2026.
Цель владельца — меньше времени на разработку в Kit и дочках. Релиз не запускался.

**Вывод:** четыре источника лишней работы устранены в этой ветке; дополнительно исправлен
неполный diff в дочерней draft-проверке. Главная незакрытая
граница — автоматическое переиспользование проверок в дочернем execution pipeline:
общий подбор тестов подключён, content adapter для reuse — нет. Поэтому нельзя выпускать
обещание «все проверки во всех дочках кешируются». Сравнительные прогоны не выполнялись.

## Исправлено в этой ветке

| Место | Что происходило | Что изменено | Подтверждение |
|---|---|---|---|
| CI Kit | Новый push не отменял старые package-quality/docs/pr-smoke; устаревший SHA продолжал занимать раннеры | Отменяется предыдущий прогон того же PR и workflow; main/manual и разные PR независимы | Декларации Actions и тест групп отмены; реальная отмена проявится при следующем перекрывающемся push |
| Граф зависимостей | Каждый исходник читался дважды; Python AST разбирался отдельно для импортов и динамических зависимостей | Один снимок текста/AST на узел, без кеша между вызовами | Счётчики реальных чтений и разбора; изменённый файл следующая сборка видит заново |
| Context Engine v2 | Полный граф строился даже без Python-кандидатов текстового поиска, хотя добавить соседей было невозможно | В этом случае граф не строится; причина явно указана в отчёте | Реальный поиск документа; запрещённый файл не читается; существующие тесты Python-соседей сохранены |
| Команды агентов | verify/regression требовали «выполнить доступные проверки», не объясняя использование уже полученного результата | Явно названы подбор по diff, проверка применимости receipts и повтор только по причине; finish использует итоговое evidence | Редакционная сверка с существующим контрактом reuse; новый механизм не добавлен |
| Диапазон задачи в дочке | Pipeline передавал только последний коммит: ранняя правка могла выпасть из draft-выборки | Передаётся base_sha..committed_sha; неизвестная база/ошибка git означает полный профиль | Два реальных коммита: ранняя ошибка в коде и поздняя проза; выбранный тест действительно падает. При неизвестной базе действительно запускается весь набор |

Источники: [repo_graph.py](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/context/repo_graph.py),
[context_engine.py](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/context/context_engine.py),
[package-quality](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/.github/workflows/package-quality.yml),
[docs workflow](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/.github/workflows/docs.yml), [pr-smoke](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/.github/workflows/pr-smoke.yml),
[ai-verify](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/commands/task/ai-verify.md), [ai-regression-check](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/commands/quality/ai-regression-check.md),
[ai-finish-task](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/commands/task/ai-finish-task.md).

Context Engine v2 включается отдельно; штатный runtime использует v1, shadow по умолчанию
выключен ([проводка](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/ai_ops_run_reporting.py)). Оптимизация графа действует
и в общем подборе тестов, поэтому не ограничена shadow-контуром.

## Оставшиеся белые пятна по приоритету

| Приоритет | Подтверждённая граница | Следующее конкретное действие |
|---|---|---|
| 1 | `evidence_collector.collect` сам создаёт content context только в корне самого Kit. Рабочие вызовы pipeline/sequence/parallel не передают `verification_context`; при его отсутствии reuse запрещён | Подключить поддерживаемый адаптер среды к одному разрешённому стеку и проверить реальный повтор без исполнения. Учесть внешние сервисы, БД, зависимости и outputs; не включать произвольное доверие по флагу |
| 2 | Последовательность получает полный baseline на sequence_base_sha, затем первый пакет при baseline_diff получает свой baseline на той же исходной базе. При продолжении последовательности baseline тоже собирается до исполнения пакетов | Переиспользовать подтверждённый baseline при совпадении дерева и среды. Остальные пакеты меняют базу: их проверки не считать дублями автоматически |
| 3 | Проверка пригодности локального receipt сама хеширует дерево, установленные Python-пакеты, stdlib и инструменты. Для свежего lint и test это делается до и после каждого исполнения | Исследовать общий снимок только внутри доказанно неизменного окружения. Не заменять content hashes на mtime и не убирать проверку изменения входов во время команды |
| 4 | Выбранная команда impact CLI не добавляет xdist, хотя прежний широкий check-fast использует его; большой выбранный набор может исполняться последовательно | Согласовать ограниченное число workers с существующим ресурсным контролем. Нельзя обещать, что меньшая выборка всегда быстрее широкого параллельного прогона |
| 5 | Все динамические Python-потребители добавляются к каждой выборке; JS aliases/setup, pytest plugins/fixtures, конфиги и критические пути сохраняют full-fallback | Сужать конкретные зависимости только при доказанной границе потребителей; это запас ускорения, а не повод отключить fallback |
| 6 | Адаптер произвольного дочернего build/test не объявляет безопасные outputs. Генерируемые файлы могут инвалидировать результат | Добавлять контракт outputs вместе с адаптером конкретного стека; tracked и неизвестные файлы оставлять входами |

Источники: [evidence_collector](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/gates/evidence_collector.py),
[execution_pipeline](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/execution_pipeline.py),
[baseline последовательности](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/sequence_aggregate.py),
[execute_sequence](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/workpackage_executor.py),
[baseline пакета](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/pipeline_setup.py),
[content adapter и receipts](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/shared/claim_provenance.py),
[impact CLI](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/devtools/impact_check_cli.py),
[политика выбора](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/gates/verification_tiers.py).

Пункты 1 и 6 требуют подключения адаптера, пункты 2–4 — отдельных ограниченных изменений.
Их нельзя объявить исправленными наличием общего API или документа. В этой работе не менялись
receipts, host-lock, права исполнения, схемы доступа и содержимое продуктовых репозиториев.

## Проверенные участки без новой правки

| Участок | Что уже ограничивает лишнюю работу |
|---|---|
| Подбор тестов Kit | Обычный check-fast передаёт origin/main и учитывает полный diff ветки/рабочей папки. Явный --impact без --base учитывает только рабочие изменения и untracked: для ветки базу нужно передать. Обычная проза освобождается от product tests; финальная стадия сохраняет свой охват |
| CI дочек | Шаблоны уже отменяют устаревшие PR-прогоны; required-контексты не переименовывались |
| Review | `review_branch` уже использует применимый PASS при той же базе, diff, политике и дереве; текстовый отчёт сам по себе недостаточен |
| Возобновление и параллельные пакеты | Есть проверка сохранённых результатов, точных SHA и бюджетов; повторный tool-loop без проверки исхода не добавлялся |
| Контекст сессии | `ai-session-start` уже разделяет обязательный компактный контекст и чтение по теме; v2 shadow выключен по умолчанию |
| Релиз и обновление | Выпуск имеет проверку ожидаемой версии/SHA/артефакта и наблюдаемого результата; шаблон обновления пропускает одинаковую версию |
| Совместимость | Контракты на разных Python, чистая установка и upgrade-path проверяют разные среды; их нельзя объявлять дублями одного локального pytest |

Источники: [review_branch](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/review_branch.py),
[parallel dispatch](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/engine/parallel_live_dispatch.py),
[старт сессии](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/commands/task/ai-session-start.md),
[поставка](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/ai_ops_kit/devtools/release_delivery_cli.py),
[обновление дочки](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/7601abe8a7397f38d3b76ff9965e8f6b62d7d267/templates/ci/ai-ops-update.yml).

## Охват и пределы ревизии

Прочитаны рабочие пути проверок, context/retrieval, baseline/sequence, review/resume,
проверочные workflows Kit и шаблоны CI дочек, выпуск и обновление. Это проверка кода и
контрактов с целевыми регрессиями, не обещание найти каждую возможную задержку.
Внешняя очередь моделей, сеть, БД и сервисы конкретных дочек здесь не исполнялись.
ИИ-Среда/ЖКХ остаются на STOP; пульт не изменялся.

Целевые прогоны: граф/context/selection — **65 passed**; диапазон задачи и pipeline setup —
**73 passed**; достижимость документов — **2 passed**. CPython 3.14; ruff PASS.
Новый код не заявляет измеренного выигрыша в секундах. Независимый review и CI фиксируются
в PR этой ветки. До нового выпуска эти ограничения должны остаться в release notes.
