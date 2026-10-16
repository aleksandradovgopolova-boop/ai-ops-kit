# #611: WorkItem и RunPlan получают одинаковые сигналы

## Результат
Работа с task_type=bug/refactor и size=large получает один ENGINEERING workflow
в RunPlan и WorkItem. Сейчас WorkItem теряет size и ошибочно становится QUICK;
внешний status законно отказывает на несовместимых артефактах, созданных самим Китoм.

## Затрагиваемые пути
ai_ops_kit/lifecycle/workitem.py; ai_ops_kit/engine/ai_ops_run.py;
ai_ops_kit/engine/ai_ops_run_lifecycle_stages.py; tests/unit/test_workitem.py;
этот brief/замер/newsfragment. Все два production callsite start проверены.

## Инварианты
Один существующий ai_route, никаких новых таблиц/политик маршрутизации. Старые
вызовы start(task_type,risk) совместимы. Явные прежние аргументы имеют приоритет
над добавочным signals. Сигналы не мутируются. Контроллер остаётся planned, не done.

## Failure modes
Потеря size/других routing-сигналов; старые аргументы сломаны; входной dict мутирован;
controller/pipeline расходятся; несовместимый RunPlan принимается вместо исправления producer.

## Доказательство
Воспроизведено на main: bug/large/low и refactor/large/low дают plan ENGINEERING,
WorkItem QUICK. Positive — согласованные workflow/reasons; fail-closed — реальные
гейты ENGINEERING остаются unmet, не обходятся; side-effect — оба входа записывают
реальные YAML и status читает их без ошибки несовместимости. Независимый review,
целевые проверки и full-current-python, затем GitHub CI.

## Не входит
Полный native task execution/смена harness без потерь на всех runtime; ядро
валидации RunPlan не ослабляется. Не дочерняя когорта и не owner acceptance.

Проверено:5новыхрегрессий красные до исправления;76passed,1skipped за44.62s
после; mypy23файла clean;size/layering/compat проходят; независимыйAIreview
NO FINDINGS. Full-current-python CPython3.14.7/darwin:9147passed,35skipped,
2warnings,1014.16s. Внешняя CI/доставка фиксируются отдельно.
