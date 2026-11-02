# AI Ops Kit

**[Русский](README.md) · English**

**Open your project in Codex or Claude Code and describe a task in everyday language.**
AI Ops Kit adds shared instructions, project context and checks so the next session
can continue with an understanding of the project. You get changes with check
results, or a specific reason why work could not proceed.

For founders, developers and product teams who need to know what changed,
why a decision was made and what supports the result.

## What working with it looks like

After connecting the kit and configuring an executor once, open **your product's
repository**, start a session and write, for example:

> Use AI Ops Kit. Return “Hello, friend!” for an empty name and add a test.
> Show the changes, the check result and anything remaining. Reply in English.

The executor reads project context, selects an applicable kit process, performs
authorized work and collects evidence. You do not need to choose internal roles
or edit internal plans. Credentials, permissions, product decisions and acceptance
remain yours. Available automation depends on the executor and its configuration:
**a complete autonomous Codex/Claude workflow is not yet verified**.

**[Start in Codex/Claude →](docs/en/QUICKSTART.md)** — what to connect once,
what to write in your first session and how to check the result.

## Try it without a model

With Git and Python 3.12+ (including `venv`/`ensurepip`), use two commands. Inspect
the retrieved checkout before running; PyPI access is needed if the dependency is missing:

```bash
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
python3 ai-ops-kit/installer/bootstrap.py --demo --language en
```

The new entry prepares an isolated environment inside the checkout and calls the
existing example. With dependencies already installed, the original
`python3 examples/first-session/demo.py` from the kit root still works.

The example creates a separate temporary Git project, installs the kit, checks
installation integrity, detects Python and saves a project assessment with questions
for the owner. It runs a real test before and after installation; sample sources
are preserved. It makes no model calls and does not implement the greeting change.

**[Example, actual output and environment setup →](examples/first-session/README.en.md)**

## Connect your project

In Claude Code **with the AI Ops plugin already installed**, say
**“Install AI Ops”**: the skill guides installation and initial setup.
The plugin and access to an executor are separate prerequisites.

From a prepared checkout and Python environment, installation starts with one command:

```bash
python3 installer/ai_ops.py setup /absolute/path/to/your/project
```

`setup` creates kit files, checks installation, gathers context and plan drafts,
and commits its own files to Git. It asks for owner decisions when facts are missing.
**The new checkout path takes three commands**, including obtaining the source and
activating the environment; the dependency is installed automatically. The original
five-command manual path remains available. Git, Python with venv and dependency
access are required; executor configuration is separate. The new entry has local
macOS verification; Linux verification is pending.
[Complete path and limitations](docs/en/installation.md).

## What has been checked

| Scenario | Status |
|---|---|
| Local installation, file integrity, sample project assessment | [Reproducible example](examples/first-session/README.en.md), without a model |
| Everyday-language tasks with the kit connected | Depends on the available process and executor; [verified runtime matrix](qualification/RUNTIME-QUALIFICATION-MATRIX-2026-10-15.md) (Russian reference) |
| Project instructions and hooks for both executors | Experiment #1434, off by default; delivered files do not prove autostart |
| Codex native provider adapter | `readiness=false`: Codex 0.147.0 has not demonstrated independent tool denial when a hook fails; [details](docs/agent-guides/team-session-integration.md) (Russian reference) |

Choose your session language: ask for Russian or English responses. These entry pages
support both languages; the entire CLI and internal documentation are not yet localized.
See [VERSION](VERSION) for the current version and [release claims](registry/release-claims.yaml)
for its channel; `qualification` does not claim `stable` status.

## Learn more

- [Quickstart](docs/en/QUICKSTART.md) · [examples](examples/README.en.md) · [glossary](docs/en/glossary.md)
- [Capabilities and limitations](docs/capability-map.md) · [full documentation](docs/index.md) (Russian references)
- [Version history](CHANGELOG.md) · [product roadmap](ROADMAP.md) (Russian references)
- [Contributing](CONTRIBUTING.en.md) · [development instructions](AGENTS.md) (Russian reference)

<details>
<summary>Technical package inventory</summary>

Command, check and role counts are derived from registries and listed in the
[capability map](docs/capability-map.md) (Russian reference). Package size does not
mean that many autonomous scenarios are verified. [Terminology](docs/en/glossary.md).

</details>

## License

[PolyForm Noncommercial 1.0.0](LICENSE). The code is available to read. Personal use,
study, research and use by noncommercial organizations are free under its terms.
Commercial use (in a company, paid product or service) and resale require a commercial
license: contact the author through her [GitHub profile](https://github.com/aleksandradovgopolova-boop).

Versions published before this change, up to and including 4.12.0, remain under MIT.
