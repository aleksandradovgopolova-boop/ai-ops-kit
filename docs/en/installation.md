# Install in your project

**[Русский](../guides/installation.md) · English** · [Quickstart](QUICKSTART.md)

## Prerequisites

Git, Python 3.12+ with `venv`/`pip`, and an existing Git project with an initial commit
and a configured Git author. Save your project changes before installing.
GitHub and Python package index access are needed to obtain the source and dependency.
Read [LICENSE](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/LICENSE) first; commercial use of the current code requires a
separate license. The engine dependency is PyYAML 6.0.3+.

## Complete manual path: 5 commands

Run from a directory next to which you can keep the kit checkout. Replace
`/absolute/path/to/your/project` with your product's real path. This installs from
current `main`, not a release tag; inspect the retrieved commit and code before
running it. After cloning, you can read the files and verify the source without
executing the installer.

```bash
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
python3 -m venv ai-ops-kit/.venv
source ai-ops-kit/.venv/bin/activate
python3 -m pip install -r ai-ops-kit/requirements.txt
python3 ai-ops-kit/installer/ai_ops.py setup /absolute/path/to/your/project
```

For an already verified checkout and prepared environment, only the final `setup`
call is needed. This is not one command from a clean machine: obtaining the source,
installing dependencies and connecting a model are separate steps. To try it after
the first four commands, replace `setup` with
`python3 ai-ops-kit/examples/first-session/demo.py`. It creates a temporary project
and leaves your product untouched.

The example is for macOS/Linux and bash/zsh. PowerShell uses a different activation:
`ai-ops-kit\.venv\Scripts\Activate.ps1`; full Windows verification was not performed in this slice.

## What setup does automatically

- Installs `.ai/managed/`, `.ai-ops.yaml` and the `./ai-ops` entry point.
- Delivers project context, Claude Code commands/skills, generated Codex prompts
  and CI templates; prepares communication instructions in `CLAUDE.md`.
- Checks integrity, detects the stack, prepares drafts and builds the initial plan
  if enough facts are available. Otherwise, it preserves questions for the owner.
- Commits its own kit files. Product changes are excluded from that commit.

If `CODEX_HOME` is set, the installer also writes prompts to its `prompts/` directory;
otherwise they remain in `.ai/generated/codex/prompts/`. Check this before installing:
it does not activate the native adapter. `demo.py` uses a temporary `CODEX_HOME`.

`setup` does not obtain credentials or call a model. Exit `0` means the automatable
part finished, not that the whole team is ready: read the remaining owner actions
and `.ai/runtime/setup/` logs. On error, resolve the named step; `setup` supports
reruns, but do not try to repair it by deleting managed files.

## Configure once after installation

Review product facts and answer outstanding questions; check a supported executor,
authorization/limits and permissions. Review project/providers in `.ai-ops.yaml`
without placing secrets in tracked files. Agree on publication rules and enable
applicable [CI checks](../guides/ci.md) (Russian reference). Installation itself
does not authorize publication.

Node.js is needed only for OpenSpec, enabled by default in the template. If you need
OpenSpec, install a compatible CLI using its instructions; otherwise explicitly set
`openspec.enabled: false` in `.ai-ops.yaml`. The installer does not install it for
you. The demo does not use OpenSpec and does not require Node.js.

A new terminal session must use Python with PyYAML installed: activate the same
environment before calling `./ai-ops`. When opening Codex/Claude, check project
instructions using the [quickstart](QUICKSTART.md). The team hooks experiment is
off by default; the native Codex adapter remains `readiness=false`. Instruction
files do not prove complete autonomy.

## Verify and update

From the product root, with the environment activated:

```bash
./ai-ops doctor
./ai-ops model --json
./ai-ops status
```

`doctor` checks local installation, not model account access or release readiness.
`model` reports known and unknown facts, rather than executing a product task.
Updating is a separate decision: review [channels](../release-channels.md) (Russian
reference) and `./ai-ops diff`, then use the supported `./ai-ops update` path.
Direct edits to `.ai/managed/` block updating; keep your own rules in `.ai/custom/`.

To develop the kit itself, see [CONTRIBUTING](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/blob/main/CONTRIBUTING.en.md).
