"""Полное read-only наблюдение выпуска через существующий GitHubClient и Git.

Не читает PR checkout/artifacts и не исполняет содержимое GitHub. Ошибка, усечение,
изменившийся источник или превышенный бюджет страниц — неизвестность, а не успех.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import re

import yaml
from urllib.parse import quote

from ai_ops_kit.devtools import release_plan
from ai_ops_kit.integrations.github import GitHubClient, GitHubError, parse_slug
from ai_ops_kit.shared.gitio import git


class SnapshotError(ValueError):
    """Полный стабильный snapshot не подтверждён."""

    def __init__(self, code, **identifiers):
        super().__init__(code)
        self.diagnostic = release_plan.snapshot_diagnostic({"code": code, **identifiers}) or {"code": "snapshot_invalid"}


def collection(client, path, *, key=None, params=None):
    rows, total = [], None
    for page in range(1, 101):
        data = client.read_page(path, {**(params or {}), "per_page": 100, "page": page})
        if key:
            count = data.get("total_count") if isinstance(data, dict) else None
            if type(count) is not int or count < 0 or (total is not None and total != count):
                raise SnapshotError("collection_total_invalid_or_changed")
            total, batch = count, data.get(key)
        else:
            batch = data
        if not isinstance(batch, list) or len(batch) > 100 or any(not isinstance(r, dict) for r in batch):
            raise SnapshotError("collection_page_invalid")
        rows.extend(batch)
        identifiers = [r["id"] for r in rows if "id" in r]
        if len(set(identifiers)) != len(identifiers):
            raise SnapshotError("collection_identity_duplicate")
        if len(batch) < 100:
            if key and len(rows) != total:
                raise SnapshotError("collection_incomplete")
            return rows
    raise SnapshotError("collection_budget_exceeded")


def _git(root, *args):
    rc, out, _ = git(root, *args, timeout=30)
    if rc:
        raise SnapshotError("git_evidence_unavailable")
    return out.strip()


def _ancestor(root, sha, target):
    if not all(isinstance(s, str) and re.fullmatch(r"[0-9a-f]{40}", s) for s in (sha, target)):
        raise SnapshotError("ancestor_identity_invalid")
    rc, _, _ = git(root, "merge-base", "--is-ancestor", sha, target, timeout=30)
    if rc not in (0, 1):
        raise SnapshotError("historical_ancestry_unavailable")
    return rc == 0


def _pull(client, number, ci, signatures, policy):
    if type(number) is not int or number < 1:
        raise SnapshotError("dependency_pr_invalid")
    pr = _object(client, f"repos/{client.repo}/pulls/{number}")
    links = client.closing_issue_numbers(number)
    if not links.ok:
        raise SnapshotError(links.reason if links.reason == "github_read_permission_denied" else "closing_issues_unavailable", pr=number)
    head_repo = (pr["head"].get("repo") or {}).get("full_name")
    item = {"number": number, "merged": pr["merged"], "state": pr["state"],
            "base_ref": pr["base"]["ref"], "base_sha": pr["base"]["sha"],
            "head_sha": pr["head"]["sha"], "merge_sha": pr["merge_commit_sha"],
            "head_ref": pr["head"].get("ref"), "head_repo": head_repo,
            "same_repo_head": _same_repo(pr["head"], client.repo), "merged_at": pr.get("merged_at"),
            "changed_files": pr["changed_files"], "closing_issues": links.items}
    ci[str(number)] = _ci(client, item, policy, signatures)
    if item["merged"] is True and any(run.get("pull_requests") == [] for run in ci[str(number)]):
        # После слияния GitHub снимает связь run→PR; однозначность head-коммита проверяет модель.
        associated = collection(client, f"repos/{client.repo}/commits/{item['head_sha']}/pulls")
        item["head_prs"] = sorted(p["number"] for p in associated
                                  if (p.get("head") or {}).get("sha") == item["head_sha"])
    return item


def _object(client, path):
    value = client.read_page(path)
    if not isinstance(value, dict):
        raise SnapshotError("api_object_missing")
    return value


def published(client):
    releases = collection(client, f"repos/{client.repo}/releases")
    stable = [r for r in releases if r.get("draft") is False and r.get("prerelease") is False
              and re.fullmatch(r"v\d+\.\d+\.\d+", r.get("tag_name", ""))]
    if not stable:
        raise SnapshotError("published_release_unknown")
    row = max(stable, key=lambda r: release_plan._version(r["tag_name"][1:]))
    tag = row["tag_name"]
    ref = _object(client, f"repos/{client.repo}/git/ref/tags/{quote(tag, safe='')}")
    obj = ref["object"]
    for _ in range(8):
        if obj["type"] == "commit":
            break
        if obj["type"] != "tag" or not re.fullmatch(r"[0-9a-f]{40}", obj["sha"]):
            raise SnapshotError("release_tag_invalid")
        obj = _object(client, f"repos/{client.repo}/git/tags/{obj['sha']}")["object"]
    else:
        raise SnapshotError("release_tag_depth_exceeded")
    if not re.fullmatch(r"[0-9a-f]{40}", obj["sha"]):
        raise SnapshotError("release_commit_invalid")
    return {"version": tag[1:], "sha": obj["sha"], "tag": tag,
            "id": row["id"], "published_at": row["published_at"]}


def _runs(client, workflow, sha):
    return collection(client, f"repos/{client.repo}/actions/workflows/{workflow}/runs",
                      key="workflow_runs", params={"head_sha": sha, "event": "pull_request"})


def _run_signature(rows):
    return sorted((r["id"], r["run_attempt"], r["status"], r.get("conclusion")) for r in rows)


def _changed_run(before, after):
    """Один изменённый run/attempt; значения status/conclusion наружу не выводятся."""
    changed = [r for r in after if r not in before] or [r for r in before if r not in after]
    return {"run_id": changed[0][0], "attempt": changed[0][1]} if changed else {}


def _ci(client, pr, policy, signatures):
    result = []
    for workflow in policy:
        runs = _runs(client, workflow, pr["head_sha"])
        signatures[(workflow, pr["head_sha"])] = _run_signature(runs)
        if not runs:
            continue
        row = max(runs, key=lambda r: (r["id"], r["run_attempt"]))
        keys = ("id", "run_attempt", "path", "head_sha", "head_branch", "event", "status", "conclusion",
                "created_at", "pull_requests")
        run = {k: row.get(k) for k in keys}
        run["head_repository"] = (row.get("head_repository") or {}).get("full_name")
        attempt = run["run_attempt"]
        if type(run["id"]) is not int or type(attempt) is not int or attempt < 1:
            raise SnapshotError("workflow_identity_invalid", pr=pr["number"], workflow=workflow)
        jobs = collection(client, f"repos/{client.repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs", key="jobs")
        run.update(queried_attempt=attempt, total_jobs=len(jobs),
                   jobs=[{k: j.get(k) for k in ("id", "name", "status", "conclusion")} for j in jobs])
        result.append(run)
    return result


def _release_ci(client, prefix, head):
    release_runs = collection(client, f"{prefix}/actions/workflows/release.yml/runs",
                              key="workflow_runs", params={"head_sha": head})
    release_ci = []
    if release_runs:
        raw = max(release_runs, key=lambda r: (r["id"], r["run_attempt"]))
        run = {k: raw.get(k) for k in ("id", "run_attempt", "path", "head_sha", "head_branch", "event", "status", "conclusion")}
        jobs = collection(client, f"{prefix}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", key="jobs")
        run.update(queried_attempt=run["run_attempt"], total_jobs=len(jobs),
                   jobs=[{k: j.get(k) for k in ("id", "name", "status", "conclusion", "steps")} for j in jobs])
        release_ci.append(run)
    return release_runs, release_ci


def _same_repo(side, repository, *, url=False):
    if not isinstance(side, dict) or not isinstance(side.get("repo"), dict):
        return False
    value = side["repo"].get("url" if url else "full_name")
    expected = f"https://api.github.com/repos/{repository}" if url else repository
    return isinstance(value, str) and value.casefold() == expected.casefold()


def _open_identity(raw, repository, branch):
    if (raw.get("state") != "open" or raw.get("merged") is not False
            or raw["base"]["ref"] != branch
            or any(not _same_repo(raw.get(part), repository) for part in ("head", "base"))):
        return None
    number = raw["number"]
    if type(number) is not int or number < 1:
        raise SnapshotError("open_pr_identity_invalid")
    identity = {"number": number, "head_sha": raw["head"]["sha"], "base_sha": raw["base"]["sha"]}
    if any(not isinstance(identity[k], str) or not re.fullmatch(r"[0-9a-f]{40}", identity[k])
           for k in ("head_sha", "base_sha")):
        raise SnapshotError("open_pr_sha_invalid", pr=number)
    return identity


def _open_ci(client, branch, policy, signatures):
    prefix = f"repos/{client.repo}"
    candidates = collection(client, f"{prefix}/pulls", params={"state": "open"})
    if len(candidates) > 100:
        raise SnapshotError("open_pr_budget_exceeded")
    archive, queries = [], []
    seen = set()
    for candidate in sorted(candidates, key=lambda c: c.get("number", 0)):
        number = candidate.get("number")
        if type(number) is not int or number < 1 or number in seen:
            raise SnapshotError("open_pr_inventory_ambiguous", pr=number)
        seen.add(number)
        identity = _open_identity(_object(client, f"{prefix}/pulls/{number}"), client.repo, branch)
        if identity is None:
            continue
        runs = _ci(client, identity, policy, signatures)
        # Native association must name the same repository, not merely the same SHA/number.
        repository_bound = all(any(type(p.get("number")) is int and p.get("number") == number
            and p.get("head", {}).get("sha") == identity["head_sha"]
            and p.get("base", {}).get("sha") == identity["base_sha"]
            and all(_same_repo(p.get(part), client.repo, url=True) for part in ("head", "base"))
            for p in run.get("pull_requests", [])) for run in runs)
        ok, evidence = release_plan._ci_observed(identity, runs, policy)
        job_ids_valid = all(all(type(j.get("id")) is int and j["id"] > 0 for j in r["jobs"])
                            and len({j["id"] for j in r["jobs"]}) == len(r["jobs"]) for r in runs)
        if repository_bound and job_ids_valid and ok:
            archive.append({"pr": number, "head": identity["head_sha"], "base": identity["base_sha"],
                            "ci_evidence": evidence})
            # Финальный барьер сверяет только то, что легло в архив. PR, чьи проверки ещё идут,
            # в снимок не входят, и их движение не обнуляет план (#1446: пока команда работает,
            # у какого-то PR проверки идут почти всегда).
            queries.append({"identity": identity, "jobs_digest": release_plan.digest(runs)})
    return archive, queries


def _verify_open(client, branch, queries, policy):
    for query in queries:
        identity = query["identity"]
        raw = _object(client, f"repos/{client.repo}/pulls/{identity['number']}")
        current = _open_identity(raw, client.repo, branch)
        if current != identity:
            field = next((k for k in ("head_sha", "base_sha") if current and current[k] != identity[k]), "identity")
            raise SnapshotError("open_pr_identity_changed", pr=identity["number"], field=field)
        runs = _ci(client, identity, policy, {})
        if release_plan.digest(runs) != query["jobs_digest"]:
            raise SnapshotError("open_pr_ci_changed", pr=identity["number"], field="jobs")


def capture(root, client=None):
    """На любой ошибке отдаёт complete=False. Никаких write API или fallback-токенов."""
    root = Path(root)
    snapshot = {"complete": False, "unchanged": False}
    stage = "repository"
    try:
        client = client or GitHubClient(repo=parse_slug(_git(root, "remote", "get-url", "origin")))
        if not parse_slug(client.repo):
            raise SnapshotError("repository_unknown")
        prefix = f"repos/{client.repo}"
        repo = _object(client, prefix)
        if repo.get("full_name", "").casefold() != client.repo.casefold():
            raise SnapshotError("repository_mismatch")
        branch = repo["default_branch"]
        path = f"{prefix}/commits/{quote(branch, safe='')}"
        head = _object(client, path)["sha"]
        if _git(root, "rev-parse", "HEAD") != head or _git(root, "status", "--porcelain", "--untracked-files=all"):
            raise SnapshotError("checkout_not_default_branch")
        stage = "release_baseline"
        baseline = published(client)
        _git(root, "merge-base", "--is-ancestor", baseline["sha"], head)
        log = _git(root, "log", "--first-parent", "--format=%H %P", f"{baseline['sha']}..{head}")
        commits = [{"sha": line.split()[0], "parents": line.split()[1:]} for line in log.splitlines()]
        inputs = release_plan.input_digests(root)
        policy = json.loads((root / "quality/premerge-checks.json").read_text())
        release_plan.validate_policy(policy)
        stage = "open_pr_ci"
        ci_archive, open_queries = _open_ci(client, branch, policy, signatures={})
        # Полный реестр issues; отсутствие закрытой задачи не маскируется default limit=40.
        issue_path = f"{prefix}/issues"
        stage = "issue_inventory"
        raw_issues = collection(client, issue_path, params={"state": "all"})
        relevant = [i for i in raw_issues if "pull_request" not in i]
        issues = [{"number": i["number"], "state": i["state"]} for i in relevant]
        issue_closures = {}
        stage = "pull_links_and_ci"
        pulls, signatures, ci, seen = [], {}, {}, set()
        for commit in commits:
            associated = collection(client, f"{prefix}/commits/{commit['sha']}/pulls")
            for candidate in associated:
                number = candidate["number"]
                if number in seen:
                    continue
                seen.add(number)
                item = _pull(client, number, ci, signatures, policy)
                if item["merged"] and item["merge_sha"] == commit["sha"]:
                    pulls.append(item)
        plan = yaml.safe_load((root / "planning/plan.yaml").read_text())
        intent = release_plan._intent(plan)
        current = (root / "VERSION").read_text().strip()
        target = (current if release_plan._version(current) > release_plan._version(baseline["version"])
                  else release_plan.release_assembly.assemble(root, milestone=intent["milestone"]).get("target_version"))
        stage = "dependencies"
        historical = []
        dependencies = release_plan.dependency_records(root, plan, target) if target else {}
        issue_index = {i["number"]: i for i in raw_issues if "pull_request" not in i}
        for dep in dependencies.values():
            if dep.get("status") != "done":
                continue
            numbers = [dep["pr"]] if dep.get("pr") else []
            number = dep.get("issue")
            if number and number in issue_index:
                issue = issue_index[number]
                if number not in {i["number"] for i in issues}:
                    issues.append({"number": number, "state": issue["state"]})
                events = issue_closures.get(number)
                if events is None:
                    events = collection(client, f"{prefix}/issues/{number}/events")
                    issue_closures[number] = events
                for event in events:
                    sha = event.get("commit_id")
                    if event.get("event") == "closed" and sha and _ancestor(root, sha, baseline["sha"]):
                        associated = collection(client, f"{prefix}/commits/{sha}/pulls")
                        numbers.extend(p["number"] for p in associated)
            for number in numbers:
                if number in seen:
                    continue
                seen.add(number)
                item = _pull(client, number, ci, signatures, policy)
                if item["merged"] and _ancestor(root, item["merge_sha"], baseline["sha"]):
                    item["merge_parents"] = _git(root, "show", "-s", "--format=%P", item["merge_sha"]).split()
                    historical.append({**item, "published_ancestor": baseline["sha"]})
        stage = "final_source_consistency"
        _verify_open(client, branch, open_queries, policy)
        release_runs, release_ci = _release_ci(client, prefix, head)
        closing_queries = [{"pr": p["number"], "issues": p["closing_issues"]} for p in [*pulls, *historical]]
        for item in closing_queries:
            links = client.closing_issue_numbers(item["pr"])
            if not links.ok or links.items != item["issues"]:
                raise SnapshotError("closing_issues_changed", pr=item["pr"], field="closing_issues")
        # Rerun/issue edits/main changes invalidate this read, even if all initial rows looked green.
        if collection(client, issue_path, params={"state": "all"}) != raw_issues:
            raise SnapshotError("issues_changed", field="issues")
        for (workflow, sha), signature in signatures.items():
            current = _run_signature(_runs(client, workflow, sha))
            if current != signature:
                raise SnapshotError("ci_changed", workflow=workflow, field="ci_signature", **_changed_run(signature, current))
        current = _run_signature(collection(client, f"{prefix}/actions/workflows/release.yml/runs",
                                           key="workflow_runs", params={"head_sha": head}))
        previous = _run_signature(release_runs)
        if current != previous:
            raise SnapshotError("release_ci_changed", workflow="release.yml", field="release_ci_signature", **_changed_run(previous, current))
        if _object(client, path)["sha"] != head:
            raise SnapshotError("default_branch_changed", field="main_sha")
        if published(client) != baseline:
            raise SnapshotError("published_release_changed", field="published_release")
        if inputs != release_plan.input_digests(root):
            raise SnapshotError("release_inputs_changed", field="input_digests")
        validation = {"open_ci_queries": open_queries,
                      "closing_queries": closing_queries, "issues_digest": release_plan.digest(raw_issues),
                      "ci_queries": [{"workflow": w, "sha": sha, "signature": signature}
                                     for (w, sha), signature in sorted(signatures.items())],
                      "release_signature": _run_signature(release_runs),
                      "release_jobs_digest": release_plan.digest(release_ci)}
        snapshot.update(repository=client.repo, source={"sha": head, "branch": branch,
                        "version": (root / "VERSION").read_text().strip()}, published=baseline,
                        commits=commits, issues=issues, pulls=pulls, dependency_pulls=historical,
                        ci=ci, ci_archive=ci_archive, input_digests=inputs,
                        release_ci=release_ci, validation=validation, complete=True, unchanged=True)
    except (GitHubError, SnapshotError, ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        denied = "github_read_permission_denied" in str(exc) or "HTTP 403" in str(exc)
        snapshot["reason"] = "github_read_permission_denied" if denied else "release_snapshot_unavailable_incomplete_or_changed"
        snapshot["failure_stage"] = stage
        if denied:
            diagnostic = {"code": "github_read_permission_denied"}
        elif isinstance(exc, SnapshotError):
            diagnostic = exc.diagnostic
        else:
            code = ("github_read_failed" if isinstance(exc, GitHubError) else
                    "source_io_unavailable" if isinstance(exc, OSError) else "source_invalid")
            diagnostic = {"code": code}
        snapshot["diagnostic"] = diagnostic
    return snapshot


def refresh(root, client=None):
    from ai_ops_kit.devtools import release_plan_state
    client = client or GitHubClient(repo=parse_slug(_git(root, "remote", "get-url", "origin")))
    snapshot = capture(root, client)
    snapshot.setdefault("repository", client.repo)
    publisher = None
    current_run = None
    if os.environ.get("GITHUB_ACTIONS") == "true":
        current_run = int(os.environ["GITHUB_RUN_ID"])
        publisher = {"run_id": current_run, "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
                     "checkout_sha": _git(root, "rev-parse", "HEAD"),
                     "branch": os.environ["GITHUB_REF_NAME"]}
        if (publisher["checkout_sha"] != os.environ.get("GITHUB_SHA")
                or client.repo != os.environ.get("GITHUB_REPOSITORY")):
            raise SnapshotError("publisher source mismatch")
    prior = release_plan_state.previous(client, current_run=current_run)
    report = release_plan.build(root, snapshot, prior=prior)
    report = release_plan_state.project(report, prior, publisher)
    return report


def emit_summary(root):
    """Только после подтверждённого deploy, в выделенную summary текущего шага."""
    from ai_ops_kit.devtools import release_plan_state
    from ai_ops_kit.ui.presenter_core import render
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("AI_OPS_RELEASE_DEPLOY_CONFIRMED") != "success":
        raise SnapshotError("summary requires confirmed stock Pages deploy")
    report = json.loads((Path(root) / "dashboard/data.json").read_text())["release_plan"]
    publisher = report["publisher"]
    if (publisher["run_id"] != int(os.environ["GITHUB_RUN_ID"])
            or publisher["attempt"] != int(os.environ["GITHUB_RUN_ATTEMPT"])
            or publisher["checkout_sha"] != os.environ["GITHUB_SHA"]
            or publisher["digest"] != release_plan_state.payload_digest(report)):
        raise SnapshotError("summary publisher mismatch")
    if report["transition"]["changed"]:
        # Dedicated GITHUB_STEP_SUMMARY: повтор перезаписывает тот же результат, не добавляет дубль.
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(render(report["message"]) + "\n", encoding="utf-8")
    return 0


def verify_projection(root, report, client):
    """Последний барьер перед deploy: source, issues, rerun/attempt и release jobs."""
    prefix = f"repos/{client.repo}"
    repo = _object(client, prefix)
    head = _object(client, f"{prefix}/commits/{quote(repo['default_branch'], safe='')}")["sha"]
    if head != _git(root, "rev-parse", "HEAD"):
        raise SnapshotError("stale checkout")
    changed = _git(root, "diff", "--name-only", "HEAD").splitlines()
    if any(p not in ("dashboard/data.json", "dashboard/index.html") for p in changed):
        raise SnapshotError("publisher checkout changed outside generated projection")
    if _git(root, "ls-files", "--others", "--exclude-standard"):
        raise SnapshotError("publisher contains untracked input")
    if report.get("source") is None:
        # Разрешено опубликовать явную неизвестность, а не старый зелёный план.
        if report.get("composition_available") or report.get("release_ready"):
            raise SnapshotError("invalid unknown projection")
        return
    baseline = published(client)
    if (report["source"]["sha"] != head or report["input_digests"] != release_plan.input_digests(root)
            or report["published"] != {k: baseline[k] for k in report["published"]}):
        raise SnapshotError("projection source changed")
    validation = report["validation"]
    _verify_open(client, repo['default_branch'], validation.get("open_ci_queries", []),
                 json.loads((Path(root) / "quality/premerge-checks.json").read_text()))
    raw_issues = collection(client, f"{prefix}/issues", params={"state": "all"})
    if release_plan.digest(raw_issues) != validation["issues_digest"]:
        raise SnapshotError("projection issue source changed")
    for item in validation["closing_queries"]:
        links = client.closing_issue_numbers(item["pr"])
        if not links.ok or links.items != item["issues"]:
            raise SnapshotError("projection issue links changed")
    for item in validation["ci_queries"]:
        if _run_signature(_runs(client, item["workflow"], item["sha"])) != [tuple(r) for r in item["signature"]]:
            raise SnapshotError("projection CI changed")
    runs, ci = _release_ci(client, prefix, head)
    if (_run_signature(runs) != [tuple(r) for r in validation["release_signature"]]
            or release_plan.digest(ci) != validation["release_jobs_digest"]):
        raise SnapshotError("projection release evidence changed")
    if _object(client, f"{prefix}/commits/{quote(repo['default_branch'], safe='')}")["sha"] != head:
        raise SnapshotError("projection source changed during final validation")
