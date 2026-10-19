# План исполнения принадлежит своей цели — #1322

Результат: automatic admission читает versioned WorkGraph из `features/<workitem_id>/work-graph.yaml`, чтобы разные цели не делили один mutable граф репозитория. Это следующий ограниченный storage/admission критерий пути цель→план после immutable goal budget anchor #1340.

Существующие `work-graph.yaml` и `.ai/runtime/work-graph.yaml` совместимы. Несколько кандидатов, включая одинаковые копии, дают отказ, без приоритета и догадок. Identity проверяется до построения feature path; symlink, dangling symlink и неподходящий тип пути не считаются отсутствующим планом с fallback на single execution. Feature внутри графа обязана совпадать с исходной целью. Граф включён в прежний полный frozen snapshot, drift закрывает следующий callback.

Доказательство: два goal-scoped графа в одном Git store разрешаются независимо и не попадают в чужой snapshot; legacy positive сохраняется; неоднозначность/unsafe identity/symlinks/wrong goal дают отказ до dispatcher; реальный automatic package runtime сохраняет feature graph provenance и отказывает следующему callback при drift. Только controlled Git/fake transport, без платных моделей. Resource admission → focused/core когда допущены → независимый entire-delta review → все17 exact-head CI → normal match-head merge.

Не входит: создание произвольного плана моделью, изменение схемы WorkGraph или бюджетов, новые права/runner/deploy, general leases, ускорение без ABBA, field acceptance и закрытие общего #1322.
