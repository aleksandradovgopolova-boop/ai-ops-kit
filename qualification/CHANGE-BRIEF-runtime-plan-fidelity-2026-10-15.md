# #611: внешний runtime сохраняет требования исходного RunPlan

## Результат

WorkItem status оценивает все гейты сохранённого RunPlan, а не только базовый
workflow. Отсутствующее evidence дополнительного трека не становится done.
Битый/чужой/несогласованный RunPlan даёт явный отказ без перезаписи статуса.
Старые WorkItem без RunPlan сохраняют прежний базовый путь.

## Затрагиваемые пути

ai_ops_kit/lifecycle/workitem.py; tests/unit/test_workitem.py; артефакты настоящей
работы runtime-plan-fidelity-611; этот brief/замер/newsfragment. Нового provider,
брокера, tool loop, формата WorkItem или слоя ядра не вводим.

## Инварианты

Повторно используем gate_executor.evaluate(gate_ids=...), уже используемый
orchestrator. Базовые обязательные гейты не удаляются. Native Codex остаётся
внешним исполнителем; controller status=planned не объявляется исполнением.
User scope — все открытые ai-ops-kit issues, исполнитель AI. Реальная инженерная
работа родителя не включается в полевую когорту дочерних продуктов #1243.

## Failure modes

Потеря дополнительных гейтов; пустой/битый список принят как отсутствие плана;
чужой workitem_id/workflow; невалидный YAML; перезапись готового статуса до проверки.

## Доказательство

До кода: один WorkItem QUICK, два подтверждённых базовых гейта, RunPlan с ux_review.
Текущий status_cmd → done, тот же gate_executor с gate_ids RunPlan → ux_review unmet.
Positive: дополнительный подтверждённый гейт учитывается; fail-closed: отсутствующий
и невалидный evidence/RunPlan; side-effect: настоящий CLI/файлы/сохранённый статус.
Независимый AI review + full-current-python; GitHub CI и доставка отдельно.

## Не входит

Универсальная квалификация всех harness; автоматический native Codex dispatch;
owner acceptance/бизнес-эффект. Это найденный разрыв общего протокола, не доказательство
готовности всей #611. Время ниже начинается после чтения и воспроизведения дефекта;
предварительное исследование не измерено. USD и активные минуты человека unknown.

Свежий review обнаружил тот же обход в прямом orchestrator.run_workflow и
несверенные активные conditional_tracks. Коррекция расширяет затрагиваемые пути
на providers/orchestrator.py и общий read-only checks/plan_artifact.py. Это
существующий нижний слой checks, без новых пакетов/зависимостей. Оба пути читают
один источник до provider-вызовов/создания TaskState; supplied gate_ids не могут
стереть сохранённые. required и активные conditional сверяются одинаково,
неизвестный gate отказывается до модели. Пропущенные inactive tracks не добавляются.

Коррекционный review потребовал отказа при удалённом базовом gate из сохранённого
плана. Нижний gate_executor уже восстанавливал mandatory floor (он не ослаблялся),
но теперь такой несогласованный RunPlan отказывается до provider/записи состояния.
Проверяется subset canonical workflow.quality_gates, новые гейты не вводятся.

Проверка реальной поставки достигла потолка файлов при отдельном новом модуле.
Читатель перенесён в существующий доменный checks/plan_artifact; новых production-
файлов/пакетов и повышения budget нет. PyYAML импортируется лениво, прежняя чистая
проверка plan-artifact остаётся stdlib. Оркестратор разделён без роста func-size.
Промежуточный full с 5 failures не считается финальным; причины исправляются.

Финальная проверка: full-current-python CPython 3.14.7 / darwin — 9107 passed, 35 skipped, 2 warnings, 746.18s. Целевые проверки — 53 passed, 1 skipped; mypy — 23 файла без ошибок. Финальный запуск заменяет промежуточные неуспешные, не скрывая их.
