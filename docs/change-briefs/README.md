# Change Brief'ы — по одному на изменение

Инженерный цикл требует Change Brief ДО кода (`AGENTS.md` → «Инженерный цикл», шаблон —
`templates/quality/ChangeBrief.md`). Заполненным брифам до 2026-08-12 не было отведено места, и
это ломало сам смысл артефакта: два лежали в корне как `.ai-change-brief.md` и
`.ai-change-brief-pom.md`, причём второй получил суффикс только чтобы не затереть первый. Бриф,
который перезаписывается следующим изменением, перестаёт быть записью решения.

## Правило

Один файл на изменение, имя — `<версия>-<slug>.md`, например `3.35-product-operating-model.md`.
Файлы **не перезаписываются**: следующее изменение приносит следующий файл. Скрытых имён в корне
больше нет — бриф это документ, а не служебное состояние.

## Что здесь есть

- [`3.34-distribution-boundary-cleanup.md`](3.34-distribution-boundary-cleanup.md) — срез 3.34:
  `validation` переехал в `ai_ops_kit/`, замер циклов ядра стал ратчетом.
- [`3.35-product-operating-model.md`](3.35-product-operating-model.md) — срез 3.35: контур
  Planning & Execution, модель контуров продукта, Human Communication Layer.

Ревизия репозитория 2026-08-11 своего брифа не имеет намеренно: бриф пишется ДО кода и объявляет
замысел, а ревизия идёт от найденного — замысел ей предшествовать не мог. Её эквивалент, с теми
же разделами (мотив, объём, доказательства, риск), — [`../audit-report.md`](../audit-report.md).

- [Цена принятой работы — #1276](1276-accepted-work-economics.md).

- [Границы автоматизации — #1241](1241-runtime-qualification-boundaries.md).
- [Здоровье паспорта требует результата прогонов — #1257](1257-passport-health-evidence.md).

- [Запуск установки и сохраняемый журнал](setup-run-journal.md).
- [Покрытие обычного набора без повторного ночного корпуса](4.11.1-ordinary-coverage.md).
- [Независимая техническая очередь — #1321/#1322](1321-independent-technical-queue.md).
- [Импорты валидаторов без повторного исполнения сценариев](validator-bootstrap-import-only.md).

- [Сверка доставленных срезов и baseline — #1321/#1322](1321-1322-progress-reconciliation-20261020.md).
- [Компактный обзор продуктового пульта](dashboard-overview-20261020.md).
- [Согласованная трёхрядная компоновка пульта](dashboard-approved-layout-20261020.md).
- [Найденные данные качества, релизов и принятых работ](dashboard-evidence-20261020.md).

- [Ускорение малых изменений без повторной работы](priority-delivery-reuse.md) — content receipts, review и подтверждение поставки.

- [Граница собственных outputs и общий слот проверок](receipt-output-boundary.md).
- [Выборочные проверки при динамических зависимостях](4.11.2-bounded-impact-checks.md).
- [Проверка check-fast без повторного сбора всего набора](4.11.2-fast-check-no-recursive-collection.md).
- [Оставшиеся повторы перед выпуском](4.11.2-pre-release-speed-audit.md).
- [Безопасное продолжение выбора тестов по файловым импортам](file-spec-fail-closed.md).
- [Сверка старого checkout и граница файловых импортов](root-reconciliation-and-file-targets.md).
- [Запас поставки без повышения потолка](compact-managed-python.md).
- [Точечные проверки сканера](targeted-security-checks.md)

- [Ускорение выбора проверок без изменения охвата](graph-selection-speed.md).

- [Сокращение повторной подготовки графа в тестах](reuse-real-graph-fixture.md).

- [Повторное использование подготовки тестовых установок и обновлений](reuse-installer-test-environments.md).

- [Один чистый checkout для корпуса выпущенных версий](reuse-release-test-checkout.md).

- [Замер: локальная правка получает более быстрый feedback без ослабления гейтов — #1321](local-feedback-targeted-selection.md).
- [Baseline CI всего пути — #1321](ci-end-to-end-baseline.md).
- [Доставляемая команда объёма проверки `verify-scope` — #1321](verify-scope-delivered-command.md).
- [Закрытие направления цикла проверок (3/3) — #1321](1321-verification-cycle-performance-closeout.md).

- [Допуск host-slot учитывает реальную нагрузку, а не имя процесса — #1377](host-slot-load-aware-admission.md).
- [Предупреждение о дрейфе версии Python local↔CI перед пушем — #1378](1378-python-version-drift-warning.md).

- [Дубль обязательного набора PR↔merge убран; финальный полный гейт перенесён на релиз (Вариант 1) — #1376](ci-pr-merge-duplication-design.md).

- [Описание выпуска деградирует чисто, когда devtools нет в дочке — #1380](1380-release-notes-degrade-without-devtools.md).

- [Стухшие наблюдения-кандидаты можно снять (`candidates decline --why`) — #1386](decline-stale-observation-candidates.md).

- [Установленный wheel работает вне клона — #1398](1398-wheel-runtime-data.md).

- [Проверка обязательных контекстов защиты main — #1401](1401-required-contexts.md).
- [Отказы и очистка контейнерного wrapper — #1410](1410-wrapper-failures.md).

- [`1405-garden-dormant-report.md`](1405-garden-dormant-report.md) — неподключённые модули и причины карантина в отчёте уборки.

- [Наблюдающие ShellCheck/shfmt и shell policy — #1410](1410-shell-quality-pilot.md).
