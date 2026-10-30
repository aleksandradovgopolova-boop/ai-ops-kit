#!/usr/bin/env python3
"""Offline comparison of recorded UI context names; does not call GitHub or read browser storage."""
import importlib.util
import json
from pathlib import Path

folder = Path(__file__).resolve().parent
root = folder.parents[2]
spec = importlib.util.spec_from_file_location(
    "required_contexts", root / "ai_ops_kit/validation/validate_required_contexts.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
observation = json.loads((folder / "browser-observation.json").read_text())
jobs_by_workflow, aliases, errors = validator._workflow_inventory(root / ".github/workflows")
declared = validator.load_declared_contexts(root)
if declared is None or errors or not validator.validate(root)["workflow_ok"]:
    raise SystemExit("Cannot compare invalid local workflow/declaration inputs")
observed = observation["branch_protection"]["required_status_checks"]
resolved = set()
unresolved = []
emitted_names = validator._emitted_context_index(jobs_by_workflow)
for context in observed:
    matches = emitted_names.get(context, set())
    if len(matches) == 1:
        resolved.update(matches)
    else:
        unresolved.append(context)
expected = set().union(*(aliases.get(context, set()) for context in declared))
missing = [context for context in declared if not (aliases.get(context, set()) & resolved)]
print(json.dumps({
    "source_kind": "authenticated-browser-ui-observation",
    "observed_at_utc": observation["observed_at_utc"],
    "local_source_revision": observation["local_comparison_basis"]["revision"],
    "declared_count": len(declared), "ui_required_count": len(observed),
    "required_status_checks_enabled": observation["branch_protection"]["required_status_checks_enabled"],
    "missing_required": sorted(missing), "unexpected_required": sorted(resolved - expected),
    "unresolved_required": sorted(unresolved),
    "comparison_status": "fail" if missing or unresolved or resolved - expected else "pass",
    "not_an_api_snapshot": True,
    "api_validator_status": validator.validate(
        root, github_snapshot=json.loads((folder / "github-snapshot.json").read_text()))["status"],
    "scope": "Configured classic protection contexts confirmed by UI; no rulesets visible. Named bypass grants and runtime enforcement remain unknown."
}, indent=2, ensure_ascii=False))
