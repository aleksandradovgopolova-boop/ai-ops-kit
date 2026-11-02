# Terms used in detailed documentation

**[Русский](../glossary.md) · English** · [Quickstart](QUICKSTART.md)

| Term | Plain meaning |
|---|---|
| Parent / child | The kit source / a project where the kit is installed |
| Runtime / executor | The program in which an agent works, such as Codex or Claude Code |
| Provider adapter | The engine's technical connection to an executor; separate from reading repository instructions |
| Workflow | An applicable sequence: define the task, execute, check and deliver a result |
| Gate | A check that blocks the next step or reports an advisory finding |
| Evidence | A saved check result bound to a particular task and file revision |
| Writer ≠ judge | The change author and independent reviewer are different participants |
| Fail-closed | Failure of a required check does not authorize continuing |
| Managed | Updateable kit files in `.ai/managed/`; your own rules belong in `.ai/custom/` |
| WorkItem / RunPlan | A task record / execution plan; neither proves execution by itself |
| Built≠wired | Code exists but is not connected to the ordinary working path |
| Qualification | A version is being qualified; it does not promise every capability is stable |

The [capability map](../capability-map.md) records implementation details and checks
(Russian reference). Release history belongs in [CHANGELOG](../../CHANGELOG.md), not the first screen.
