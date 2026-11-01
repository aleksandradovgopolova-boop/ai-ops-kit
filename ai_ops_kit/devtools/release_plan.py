"""Read model собственного выпуска. Не выполняет merge, release или доставку дочке."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import yaml

from ai_ops_kit.devtools import release_assembly
from ai_ops_kit.planning import plan_model, plan_validate
from ai_ops_kit.validation import validate_release_claims

_SHA = re.compile(r"^[0-9a-f]{40}$")
_INPUTS = ("VERSION", "planning/plan.yaml", "quality/premerge-checks.json",
           "registry/release-claims.yaml", ".github/workflows/release.yml",
           ".github/workflows/package-quality.yml", "history/plan-history.yaml",
           "registry/communication-policy.yaml", ".github/workflows/status-dashboard.yml",
           "ai_ops_kit/devtools/release_plan.py", "ai_ops_kit/devtools/release_plan_sources.py",
           "ai_ops_kit/devtools/release_plan_state.py", "ai_ops_kit/devtools/release_assembly.py",
           "ai_ops_kit/integrations/github.py", "ai_ops_kit/planning/plan_model.py",
           "ai_ops_kit/planning/plan_validate.py", "ai_ops_kit/validation/validate_release_claims.py")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def input_digests(root):
    root = Path(root).resolve()
    result = {}
    names = [*_INPUTS, *[p.relative_to(root).as_posix() for p in sorted((root / "newsfragments").glob("*.md"))]]
    for name in names:
        path = root / name
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("release input missing or outside repository")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _intent(plan):
    if plan_model.RELEASE_INTENT_KEY in plan:
        errors = plan_validate._release_intent_errors(plan_model.release_intent(plan))
        if errors:
            raise ValueError("invalid release_intent")
        return plan_model.release_intent(plan)
    milestone = plan_model.current_milestone(plan) or {}
    return {"id": "kit-release", "milestone": milestone.get("name") or "Проверенный выпуск",
            "candidate_limit": 0}


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("invalid exact version")
    return tuple(map(int, value.split(".")))


def _history(snapshot):
    source, published = snapshot["source"], snapshot["published"]
    head, base = source["sha"], published["sha"]
    if not _SHA.fullmatch(head) or not _SHA.fullmatch(base):
        raise ValueError("invalid source SHA")
    rows = snapshot["commits"]
    by_sha = {r["sha"]: r for r in rows}
    if len(by_sha) != len(rows) or any(not _SHA.fullmatch(sha) for sha in by_sha):
        raise ValueError("ambiguous commit inventory")
    seen, cursor = set(), head
    while cursor != base:
        if cursor in seen or cursor not in by_sha:
            raise ValueError("release first-parent ancestry incomplete or cyclic")
        seen.add(cursor)
        parents = by_sha[cursor]["parents"]
        if not isinstance(parents, list) or not parents or any(not _SHA.fullmatch(p) for p in parents):
            raise ValueError("invalid commit parents")
        cursor = parents[0]
    if set(by_sha) != seen:
        raise ValueError("release inventory contains foreign commits")
    return by_sha


def validate_policy(policy):
    if not isinstance(policy, dict) or not policy:
        raise ValueError("empty CI policy")
    for workflow, names in policy.items():
        if (not isinstance(workflow, str) or not re.fullmatch(r"[\w-]+\.yml", workflow)
                or not isinstance(names, list) or not names
                or any(not isinstance(n, str) or not n for n in names)
                or len(set(names)) != len(names)):
            raise ValueError("invalid CI policy")


def _ci_observed(pr, records, policy):
    """Наблюдение exact PR CI, не independent review и не stock premerge admission."""
    evidence = {}
    for workflow, names in policy.items():
        candidates = [r for r in records if r.get("path") == ".github/workflows/" + workflow]
        if not candidates:
            return False, evidence
        if any(type(r.get("id")) is not int or type(r.get("run_attempt")) is not int
               or r["id"] < 1 or r["run_attempt"] < 1 for r in candidates):
            raise ValueError("invalid workflow identity")
        run = max(candidates, key=lambda r: (r["id"], r["run_attempt"]))
        bound = any(p.get("number") == pr["number"] and
                    p.get("head", {}).get("sha") == pr["head_sha"] and
                    p.get("base", {}).get("sha") == pr["base_sha"]
                    for p in run.get("pull_requests", []))
        if (run.get("head_sha") != pr["head_sha"] or run.get("event") != "pull_request"
                or not bound or run.get("status") != "completed"
                or run.get("conclusion") != "success"
                or run.get("queried_attempt") != run["run_attempt"]):
            return False, evidence
        jobs = run.get("jobs", [])
        if type(run.get("total_jobs")) is not int or len(jobs) != run["total_jobs"]:
            return False, evidence
        for name in names:
            matches = [j for j in jobs if j.get("name") == name]
            if (len(matches) != 1 or matches[0].get("status") != "completed"
                    or matches[0].get("conclusion") != "success"):
                return False, evidence
        evidence[workflow] = {"run": run["id"], "attempt": run["run_attempt"], "checks": names}
    return True, evidence


def _implementation_rows(snapshot, commits, policy):
    pulls = snapshot["pulls"]
    numbers = [p["number"] for p in pulls]
    if len(set(numbers)) != len(numbers):
        raise ValueError("ambiguous pull requests")
    rows = []
    for pr in pulls:
        if (any(not isinstance(pr.get(k), str) or not _SHA.fullmatch(pr[k])
                for k in ("head_sha", "base_sha", "merge_sha"))
                or any(type(n) is not int or n < 1 for n in pr.get("closing_issues", []))):
            raise ValueError("invalid implementation identity")
    for pr in sorted(pulls, key=lambda p: p["number"]):
        if type(pr["number"]) is not int or pr["number"] <= 0:
            raise ValueError("invalid PR number")
        merged = (pr.get("merged") is True and pr.get("state") == "closed"
                  and pr.get("base_ref") == snapshot["source"]["branch"]
                  and pr.get("merge_sha") in commits
                  and type(pr.get("changed_files")) is int and pr["changed_files"] > 0)
        ci_ok, ci = _ci_observed(pr, snapshot.get("ci", {}).get(str(pr["number"]), []), policy)
        rows.append({"pr": pr["number"], "merge_sha": pr.get("merge_sha"),
                     "head": pr.get("head_sha"), "base": pr.get("base_sha"),
                     "merged_change_observed": merged, "ci_observed": ci_ok,
                     "ci_evidence": ci, "closing_issues": sorted(pr.get("closing_issues", [])),
                     "url": f"https://github.com/{snapshot['repository']}/pull/{pr['number']}",
                     "independent_review": "unknown"})
    return rows


def _issue_rows(snapshot, implementations):
    issues = snapshot["issues"]
    if len({i["number"] for i in issues}) != len(issues):
        raise ValueError("ambiguous issues")
    result = []
    for issue in issues:
        if type(issue.get("number")) is not int or issue["number"] < 1 or issue.get("state") not in ("open", "closed"):
            raise ValueError("invalid issue")
    for issue in sorted(issues, key=lambda i: i["number"]):
        links = [p for p in implementations if issue["number"] in p["closing_issues"]]
        change = any(p["merged_change_observed"] for p in links)
        verified = any(p["merged_change_observed"] and p["ci_observed"] for p in links)
        result.append({"issue": issue["number"], "state": issue["state"],
                       "linked_prs": [p["pr"] for p in links],
                       "implementation_observed": change, "ci_chain_observed": verified,
                       "acceptance": "unknown",
                       "url": f"https://github.com/{snapshot['repository']}/issues/{issue['number']}"})
    return result


def dependency_records(root, plan, version):
    """Один транзитивный граф для collector и read model, включая прошлые циклы."""
    history_path = Path(root) / plan_model.HISTORY_REL
    history = yaml.safe_load(history_path.read_text()) if history_path.is_file() else {}
    closed = history.get("work", []) if isinstance(history, dict) else []
    all_rows = [*plan_model.items(plan), *closed]
    work = {w["id"]: w for w in all_rows}
    if len(work) != len(all_rows):
        raise ValueError("ambiguous dependency inventory")
    entry = work.get("next-kit-release-" + version.replace(".", "-"), {})
    states, records = {}, {}
    pending = [(d, False) for d in entry.get("depends_on", [])]
    while pending:
        dep, exiting = pending.pop()
        if exiting:
            states[dep] = "done"
            continue
        if states.get(dep) == "visiting":
            raise ValueError("cyclic release dependencies")
        if states.get(dep) == "done":
            continue
        states[dep] = "visiting"
        row = work.get(dep, {"id": dep, "status": "unknown"})
        records[dep] = row
        pending.append((dep, True))
        pending.extend((d, False) for d in row.get("depends_on", []))
    return records


def _dependencies(root, plan, version, issue_rows, implementations):
    gaps = []
    for dep, row in dependency_records(root, plan, version).items():
        observed = any(i["issue"] == row.get("issue") and i["ci_chain_observed"] for i in issue_rows)
        observed |= any(p["pr"] == row.get("pr") and p["merged_change_observed"]
                        and p["ci_observed"] for p in implementations)
        if row.get("status") != "done" or not observed:
            gaps.append(dep)
    return sorted(gaps)


def semantic_fingerprint(report):
    """Meaningful transition: timestamps/publisher/run IDs и отдельные job completions не шумят."""
    return digest({"target": report.get("target_version"),
                   "commits": [r["sha"] for r in report.get("included_commits", [])],
                   "composition": report.get("composition_available"),
                   "plan": report.get("plan_ready"),
                   "evidence": report.get("implementation_evidence_complete"),
                   "blockers": report.get("blockers"),
                   "deferred": report.get("deferred_issues"), "channel": report.get("channel"),
                   "ready": report.get("release_ready"), "cycle_state": report.get("cycle_state")})


def finalize(report):
    report["blockers"] = sorted(set(report["blockers"]))
    report["input_fingerprint"] = digest({k: v for k, v in report.items()
                                          if k not in ("input_fingerprint", "semantic_fingerprint")})
    report["semantic_fingerprint"] = semantic_fingerprint(report)
    return report


def build(root, snapshot):
    """Детерминированный read model; весь snapshot собирается read-only adapter отдельно."""
    root = Path(root)
    report = {"schema_version": 1, "kind": "kit-release-plan", "repository": snapshot.get("repository"),
              "source": None, "published": None,
              "cycle_state": "unknown", "composition_available": False, "implementation_evidence_complete": False,
              "release_ready": False, "publication_authorized": None, "blockers": [], "plan_ready": False,
              "delivery": {"observed": "unknown", "automatic_update_or_rollback": False}}
    try:
        inputs = input_digests(root)
        if (snapshot.get("complete") is not True or snapshot.get("unchanged") is not True
                or snapshot.get("input_digests") != inputs):
            raise ValueError("incomplete or changed source")
        plan = yaml.safe_load((root / "planning/plan.yaml").read_text())
        intent = _intent(plan)
        policy = json.loads((root / "quality/premerge-checks.json").read_text())
        validate_policy(policy)
        if not isinstance(snapshot.get("repository"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", snapshot["repository"]):
            raise ValueError("invalid repository")
        commits = _history(snapshot)
        current = (root / "VERSION").read_text().strip()
        previous = snapshot["published"]["version"]
        if current != snapshot["source"]["version"] or _version(current) < _version(previous):
            raise ValueError("checkout version is stale")
        assembly = release_assembly.assemble(root, milestone=intent["milestone"])
        target = current if _version(current) > _version(previous) else assembly.get("target_version")
        report.update(input_digests=inputs, source={k: snapshot["source"][k] for k in ("sha", "branch", "version")},
                      published={k: snapshot["published"][k] for k in ("sha", "version", "tag", "id")})
        if not commits and not release_assembly.pending_fragments(root):
            report.update(cycle_state="idle", target_version=None, cycle_id=intent["id"] + ":idle:" + current,
                          composition_available=True, implementation_evidence_complete=True, plan_ready=True,
                          included_commits=[], implementations=[], dependency_implementations=[],
                          issues=_issue_rows(snapshot, []), fragments={}, deferred_issues=[],
                          dependency_gaps=[], unlinked_commits=[], validation=snapshot.get("validation"))
            return finalize(report)
        if not target:
            report["blockers"].append("unreleased_changes_without_fragments")
        if target and _version(target)[0] != _version(previous)[0]:
            report["blockers"].append("major_requires_owner_decision")
        implementations = _implementation_rows(snapshot, commits, policy)
        historical = snapshot.get("dependency_pulls", [])
        if any(p.get("published_ancestor") != snapshot["published"]["sha"] for p in historical):
            raise ValueError("historical dependency ancestry unknown")
        historical_rows = _implementation_rows({**snapshot, "pulls": historical},
                                               {p["merge_sha"]: p for p in historical}, policy)
        issues = _issue_rows(snapshot, [*implementations, *historical_rows])
        linked = {p["merge_sha"] for p in implementations if p["merged_change_observed"]}
        unlinked = sorted(set(commits) - linked)
        if unlinked:
            report["blockers"].append("unverified_merge_provenance")
        missing_deps = _dependencies(root, plan, target, issues, [*implementations, *historical_rows]) if target else []
        if missing_deps:
            report["blockers"].append("dependency_evidence_missing")
        complete = all(p["ci_observed"] for p in implementations if p["merged_change_observed"])
        if commits and not complete:
            report["blockers"].append("implementation_ci_incomplete")
        report.update(cycle_state="planned", target_version=target, cycle_id=intent["id"] + ":" + str(target),
                      input_digests=inputs, source={k: snapshot["source"][k] for k in ("sha", "branch", "version")},
                      published={k: snapshot["published"][k] for k in ("sha", "version", "tag", "id")},
                      fragments=assembly.get("by_category", {}), validation=snapshot.get("validation"),
                      included_commits=[commits[sha] for sha in sorted(commits)],
                      implementations=implementations, dependency_implementations=historical_rows,
                      issues=issues, unlinked_commits=unlinked,
                      dependency_gaps=missing_deps, composition_available=bool(target and commits),
                      implementation_evidence_complete=bool(commits and complete and not unlinked))
        deferred = intent.get("deferred", {})
        report["deferred_issues"] = (sorted(deferred.get("issues", []))
                                     if deferred.get("cycle_version") == target else [])
        if target and current != target:
            report["blockers"].append("release_bump_pending")
        final_ok = final_release_observed(root, snapshot, policy, target)
        claims = yaml.safe_load((root / "registry/release-claims.yaml").read_text())
        channel_errors = validate_release_claims.channel_errors({**claims, "version": target})
        report["channel"] = {"declared": claims.get("channel"), "policy_valid_for_target": not channel_errors,
                             "earned": bool(final_ok and not channel_errors)}
        if channel_errors:
            report["blockers"].append("channel_evidence_missing")
        report["final_release_checks_observed"] = final_ok
        report["plan_ready"] = bool(report["composition_available"] and not unlinked and not missing_deps)
        report["release_ready"] = bool(report["plan_ready"] and final_ok and target == current
                                       and not report["blockers"])
        if not final_ok:
            report["blockers"].append("final_release_evidence_required")
    except (ValueError, KeyError, TypeError, AttributeError, OSError, yaml.YAMLError):
        report["blockers"].append("source_unknown_or_invalid")
        if snapshot.get("reason") in ("github_read_permission_denied", "release_snapshot_unavailable_incomplete_or_changed"):
            report["unavailable_reason"] = snapshot["reason"]
        if snapshot.get("failure_stage") in ("repository", "release_baseline", "issue_inventory", "pull_links_and_ci", "dependencies", "final_source_consistency"):
            report["unavailable_stage"] = snapshot["failure_stage"]
    return finalize(report)


def _release_job_results(root, policy):
    """Только известные условия stock workflow на push/dispatch; неизвестность блокирует."""
    workflow = yaml.safe_load((Path(root) / ".github/workflows/package-quality.yml").read_text())
    expected = {"check": "success", "release": "success"}
    for name in policy["package-quality.yml"]:
        job = workflow["jobs"].get(name.split(" (", 1)[0])
        if not isinstance(job, dict):
            raise ValueError("release job declaration missing")
        condition = job.get("if")
        if "if" not in job or condition == "github.event_name != 'pull_request' || github.event.pull_request.draft == false":
            result = "success"
        elif condition == "github.event_name == 'pull_request'":
            result = "skipped"
        else:
            raise ValueError("release job condition unsupported")
        expected["full-gate / " + name] = result
    return expected


def final_release_observed(root, snapshot, policy, target):
    """Наблюдает actual stock release SHA/attempt/jobs/шаги; не даёт прав публикации."""
    if snapshot["source"]["version"] != target or release_assembly.pending_fragments(Path(root)):
        return False
    runs = snapshot.get("release_ci", [])
    if not runs:
        return False
    if any(type(r.get("id")) is not int or type(r.get("run_attempt")) is not int for r in runs):
        raise ValueError("invalid release CI")
    run = max(runs, key=lambda r: (r["id"], r["run_attempt"]))
    if (run.get("head_sha") != snapshot["source"]["sha"]
            or run.get("path") != ".github/workflows/release.yml"
            or run.get("head_branch") != snapshot["source"]["branch"]
            or run.get("event") not in ("push", "workflow_dispatch")
            or run.get("run_attempt") != run.get("queried_attempt")
            or not ((run.get("status") == "completed" and run.get("conclusion") == "success")
                    or (run.get("status") == "in_progress" and run.get("conclusion") is None))):
        return False
    jobs = run.get("jobs", [])
    if type(run.get("total_jobs")) is not int or run["total_jobs"] != len(jobs):
        return False
    for name, conclusion in _release_job_results(root, policy).items():
        found = [j for j in jobs if j.get("name") == name]
        if len(found) != 1:
            return False
        job = found[0]
        success = job.get("status") == "completed" and job.get("conclusion") == conclusion
        publishing = name == "release" and job.get("status") == "in_progress" and job.get("conclusion") is None
        if not (success or publishing):
            return False
    workflow = yaml.safe_load((Path(root) / ".github/workflows/release.yml").read_text())
    expected = [s.get("name") for s in workflow["jobs"]["release"]["steps"]
                if "pytest" in s.get("run", "")]
    if len(expected) < 3 or any(not n for n in expected):
        return False
    steps = next(j["steps"] for j in jobs if j["name"] == "release")
    return all(len([s for s in steps if s.get("name") == name and s.get("status") == "completed"
                    and s.get("conclusion") == "success"]) == 1 for name in expected)
