"""Read-only receipt for the pre-tag Pages window; never authorizes a release."""
from __future__ import annotations

import argparse
from datetime import datetime
import json

from ai_ops_kit.devtools import release_plan_state
from ai_ops_kit.integrations.github import GitHubClient, GitHubError


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("missing timezone")
    return parsed


def receipt(client, head, version, started, *, read=release_plan_state.read_page,
            verify=release_plan_state.previous):
    page = read(client.repo)
    plan = page["release_plan"]
    publisher = plan["publisher"]
    if (plan["source"]["sha"] != head or publisher["checkout_sha"] != head
            or plan["target_version"] != version or plan["published"]["version"] == version
            or plan["release_ready"] is not True or plan["final_release_checks_observed"] is not True):
        return None
    # Authenticate these same bytes against the latest successful Pages deployment.
    if verify(client, read=lambda _: page) != plan:
        return None
    run_id = publisher["run_id"]
    run = client.read_page(f"repos/{client.repo}/actions/runs/{run_id}")
    if (run["id"] != run_id or run["run_attempt"] != publisher["attempt"]
            or run["head_sha"] != head or run["status"] != "completed" or run["conclusion"] != "success"
            or _utc(run["created_at"]) < _utc(started)):
        return None
    return {"version": version, "source_sha": head, "pages_run_id": run_id,
            "attempt": publisher["attempt"], "digest": publisher["digest"], "release_ready": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "head", "version", "started"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = receipt(GitHubClient(repo=args.repo), args.head, args.version, args.started)
    except (GitHubError, OSError, TypeError, KeyError, ValueError, AttributeError):
        return 1
    if result is None:
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
