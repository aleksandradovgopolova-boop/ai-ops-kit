# Contributing to AI Ops Kit

**[Русский](CONTRIBUTING.md) · English**

**The kit is not accepting external changes at this time: the product is preparing for a commercial launch.**
Pull requests from external contributors are not being accepted.

Questions and bug reports can be submitted through
[Issues](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues) in Russian or English.
For a bug, include kit version, OS/Python, the command, expected result and
redacted actual output. Do not include secrets.

The current license is [PolyForm Noncommercial 1.0.0](LICENSE), not MIT.
Commercial use of the current code requires a separate license;
see [terms and author contact](README.en.md#license). Previously published
versions up to and including 4.12.0 remain under MIT. This page does not alter LICENSE.

## For maintainers: internal change process

The instructions below are retained for maintainers and work already agreed upon.
They are not an invitation for external PRs and do not change the license terms.

Before changing files, read [AGENTS.md](AGENTS.md) and the
[engineering cycle](docs/agent-guides/engineering-cycle.md) (Russian references).
Use an isolated branch/checkout, claim your write scope and start with a short
Change Brief. Keep code, registries and references consistent; do not declare a
runtime supported without verification. Russian and English entry pages must
retain equivalent content. Internal documentation is still mainly in Russian.

Development environment from the checkout root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
./scripts/check-fast.sh
```

The check chooses coverage from the diff against `origin/main`; it is a local check,
not a replacement for required CI. For example changes, run
`python3 examples/first-session/demo.py`. For documentation, check links and both
languages. Add a [newsfragment](newsfragments/README.md) (Russian reference);
VERSION and CHANGELOG change at release time, not for every edit.

Format issues using the [template](.github/ISSUE_TEMPLATE/task.md): what, why,
how to verify, scope/source. Describe the problem, final behavior, checks and
limitations in a PR; exclude other contributors' changes. Merging requires
independent review and applicable CI for the exact final revision.
