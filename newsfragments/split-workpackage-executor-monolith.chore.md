Монолит движка `ai_ops_kit/engine/workpackage_executor.py` (1066 строк) разрезан на соседние модули
пакета `engine` чистым рефакторингом — поведение байт-в-байт, тела и докстринги не тронуты. Вынесены
два когезивных кластера: модель SequencePlan (детерминированные хэши определения пакета/плана и полная
integrity-валидация) — в `ai_ops_kit/engine/sequence_plan.py`; aggregate-верификация финального SHA,
закрытие security/code_review на интеграционном диффе base..final, доставка draft PR и durable-запись
sequence-report — в `ai_ops_kit/engine/sequence_aggregate.py`. Имена ре-экспортированы из шапки
`workpackage_executor`, поэтому внешние импортёры, тесты и мутационные пробы работают без изменений.
Файл ужался до 681 строки (ниже порога ратчета 700).
