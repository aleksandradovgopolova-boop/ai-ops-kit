# Start with AI Ops Kit

**[Русский](../QUICKSTART.md) · English** · [Home](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/README.en.md)

## See a result first

The [local example](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/examples/first-session/README.en.md) installs the kit in a
separate sample repository and shows real checks and a project assessment. No model
or subscription is needed. It checks the connection; it does not demonstrate a completed AI task.

## Connect once

You need a Git repository with an initial commit, Python 3.12+ and PyYAML 6.0.3+.
[Installation](installation.md) shows the new three-command path: clone, bootstrap
and activate an isolated environment. Git, Python with venv and access to the existing
dependency are required. The original five-command path and a single `setup` call
from a prepared environment remain available. The new entry has local macOS/Python
3.14 verification; CI pipeline-e2e checks Linux/Python 3.12 and 3.13 on the exact revision. `setup` creates and commits its
own kit files; save your project changes first.

If the AI Ops plugin is already installed in Claude Code, say “Install AI Ops”.
The skill runs installation and diagnostics, then helps with the initial questions.
This works through agent instructions and requires repository access and permissions.

After installation, work with a technical teammate once to:

- Read the `doctor` result, review product facts and answer what the kit could not infer from files.
- Select an available supported executor and configure authorization and a budget.
  Model use can consume subscription/API allowance; the offline example does not.
- Check that a new session reads project instructions. Claude Code receives kit
  commands/skills; installing the kit in a project does not install the plugin.
  Give Codex the explicit instruction below if automatic connection is not configured.
- Agree on publication rules and configure CI using the [guide](../guides/ci.md)
  (Russian reference). Local success does not replace CI.

## Open a session and describe a task

Open **your product's root directory**, containing `.ai-ops.yaml` and `ai-ops`.
In your first Codex or Claude Code session without an existing connection, paste:

> Work through the installed AI Ops Kit. First read
> `.ai/managed/commands/task/ai-session-start.md` and
> `.ai/managed/commands/task/ai-run.md`, and check the available execution path.
> Return “Hello, friend!” for an empty name and add a test.
> Show the result, how it was checked and anything remaining. Reply in English.
> If the required executor is unavailable, preserve the task and name the specific blocker.

The greeting task belongs to the [sample project](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/examples/first-session/README.en.md);
replace that sentence with your task in your own product. You do not need to repeat
the technical introduction every time: after checking the connection, your team can
save references to these instructions in its `AGENTS.md`/`CLAUDE.md`, outside installer
blocks. An agent reading instructions is a communication mechanism, not independent tool enforcement.

In later connected sessions, an ordinary request is enough:

- “Look at the project and suggest the next useful task.”
- “Fix search and check it after reloading.”
- “Continue the work and show what remains.”

Add “reply in Russian” if that is your team's language. Response language is a session
requirement; technical commands, stored templates and some CLI messages retain their
original language. We do not yet claim complete CLI localization.

## Accept the result

Ask for changed files, applicable test results and remaining limitations. When work
runs through the engine, reports are saved under `features/<id>/`; compare them with
the current task and file revision. A plan, “done” message or old report does not prove
execution. Required checks, independent review and CI must cover the final changes.
If model/environment access is missing, expect a specific blocker, not a success report.

## If the session did not pick up the kit

Check the project root and `.ai-ops.yaml`, then ask the executor to read the two
instructions above and run `./ai-ops doctor` with the Python environment activated.
Missing `yaml` means returning to [dependency setup](installation.md). If installation
is damaged, preserve diagnostics and resolve them before executing the task; do not
delete managed files or reinstall over unfinished work.

Project hooks for both executors are experiment #1434, `off` by default. Installing
them does not prove the runtime loaded them. The native Codex adapter has
`readiness=false`: Codex 0.147.0 has not demonstrated independent tool denial when a
hook fails. This limitation is separate from reading `AGENTS.md`/`CLAUDE.md`.
[Integration status](../agent-guides/team-session-integration.md) ·
[runtime matrix](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/qualification/RUNTIME-QUALIFICATION-MATRIX-2026-10-15.md)
(Russian references).

Next: [examples](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/examples/README.en.md) · [glossary](glossary.md) ·
[detailed direct CLI workflow](../guides/cli-workflow.md) (Russian reference).
