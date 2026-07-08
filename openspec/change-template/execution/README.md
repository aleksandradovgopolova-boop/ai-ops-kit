# execution/ — task-lifecycle изменения

Артефакты выполнения кладутся сюда по существующим шаблонам пакета
(они не дублируются, а переиспользуются — принцип 24):

- TaskBrief, TaskContext, TaskPlan, TaskState, TaskHandoff, TaskResult
  → [`../../../templates/task/`](../../../templates/task/TaskState.md)
- VerificationEvidence
  → [`../../../templates/quality/VerificationEvidence.md`](../../../templates/quality/VerificationEvidence.md)

`TaskState.yaml` здесь обеспечивает возобновление после прерывания сессии.
