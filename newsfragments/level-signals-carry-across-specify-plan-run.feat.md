Сигналы задачи, заданные на `specify` (`--signals '{"task_type":"ENGINEERING",...}'`), теперь
сохраняются в `features/<id>/spec.yaml` и автоматически подхватываются шагами `plan` и `run`, когда
`--signals` на вызове не передан; явный `--signals` по-прежнему переопределяет сохранённое. Прежде
(полевой замер cockpit, фича free-tile-counter) уровень spec и workflow прогона считались независимо:
`plan` без повторных сигналов выдавал `base_workflow: QUICK`, а подсказка `run` роняла `task_type` —
ENGINEERING-задача молча ехала как QUICK без судьи. Подсказка intake теперь сохраняет известный
`task_type`.
