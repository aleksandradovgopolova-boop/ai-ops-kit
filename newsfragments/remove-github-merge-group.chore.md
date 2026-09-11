Снят мёртвый фордж-зависимый механизм `merge_group` (#311/#312): триггер `merge_group:` убран из
`on:` обоих обязательных workflow (`pr-smoke.yml`, `package-quality.yml`) вместе с его обвязкой
(«капкан статусов», рационале очереди слияния в комментариях, `required-contexts.yaml` и
`docs/guides/ci.md`). GitHub merge queue недоступна для личных репозиториев и привязывала кит к
фиче конкретного форджа — фордж-нейтральный пивот 04.09. Обычные триггеры (`pull_request`, `push`,
`workflow_dispatch`) работают как прежде; draft-фильтр `quality` сохранил форму
`github.event_name != 'pull_request' || …` — она по-прежнему нужна, чтобы push/workflow_dispatch не
скипались. Дрейф main против ИТОГА СЛИЯНИЯ держит сам кит на чистом git
(`ai_ops_kit/gates/merge_preview.py`, `gate-measures-merge-result`), а не очередь форджа.
Контракт-страж переориентирован (`test_gate_measures_merge_result.py` →
`test_ci_event_gating.py`): требует draft-фильтр, покрывающий не-PR события, гейтит шаг проверки
заголовка PR по `pull_request` и фиксирует, что `merge_group:` не крадётся обратно.
