"""Полнота/стабильность API и отсутствие записи; реальная Git ancestry в temp repo."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import os
import subprocess

import pytest

from ai_ops_kit.devtools import release_plan as rp, release_plan_sources as src
from ai_ops_kit.integrations.github import GitHubClient, GitHubError, FetchResult

ROOT = Path(__file__).resolve().parents[2]


class Client:
    repo = "owner/kit"

    def __init__(self, head, base, policy):
        self.calls, self.mode = [], "ok"
        self.head, self.base, self.policy = head, base, policy

    def closing_issue_numbers(self, number):
        return FetchResult(True, items=[9] if number == 10 else [], source="fixture")

    def read_page(self, path, params=None):
        params = params or {}
        self.calls.append((path, params))
        if self.mode == "403":
            raise GitHubError("HTTP 403")
        prefix = "repos/owner/kit"
        tail = path.removeprefix(prefix)
        if tail == "":
            return {"full_name": self.repo, "default_branch": "main"}
        if tail == "/commits/main":
            reads = len([p for p, _ in self.calls if p == path])
            return {"sha": "f" * 40 if self.mode == "main_changed" and reads > 1 else self.head}
        if tail == "/releases":
            return [{"id": 50, "draft": False, "prerelease": False, "tag_name": "v4.11.4", "published_at": "2026-10-26T12:00:00Z"}]
        if tail == "/git/ref/tags/v4.11.4":
            return {"object": {"type": "commit", "sha": self.base}}
        if tail == "/issues":
            rows = [{"id": 9, "number": 9, "state": "closed", "closed_at": "2026-10-30T12:00:00Z"},
                    {"id": 99, "number": 99, "state": "closed", "closed_at": "2026-10-30T12:00:00Z"}]
            reads = len([p for p, _ in self.calls if p == path])
            if self.mode == "issue_changed" and reads > 1:
                rows[0]["state"] = "open"
            return rows
        if tail == "/issues/9/events":
            return [{"id": 1, "event": "closed", "commit_id": self.head}]
        if tail == "/issues/99/events":
            return [{"id": 2, "event": "closed", "commit_id": None}]
        if tail == f"/commits/{self.head}/pulls":
            return [{"id": 10, "number": 10}]
        if tail == "/pulls/10":
            return {"number": 10, "merged": True, "state": "closed", "merge_commit_sha": self.head,
                    "head": {"sha": "3" * 40}, "base": {"ref": "main", "sha": self.base}, "changed_files": 1}
        for i, (workflow, names) in enumerate(self.policy.items(), start=1):
            if tail == f"/actions/workflows/{workflow}/runs":
                reads = len([p for p, _ in self.calls if p == path])
                return {"total_count": 1, "workflow_runs": [{"id": i, "run_attempt": 2 if self.mode == "rerun" and reads > 1 else 1,
                        "path": ".github/workflows/" + workflow, "head_sha": "3" * 40,
                        "event": "pull_request", "status": "completed", "conclusion": "success",
                        "pull_requests": [{"number": 10, "head": {"sha": "3" * 40}, "base": {"sha": self.base}}]}]}
            if tail == f"/actions/runs/{i}/attempts/1/jobs":
                jobs = [{"id": j, "name": n, "status": "completed", "conclusion": "success"} for j, n in enumerate(names)]
                return {"total_count": len(jobs) + (1 if self.mode == "truncated" else 0), "jobs": jobs}
        if tail == "/actions/workflows/release.yml/runs":
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError((path, params))


@pytest.fixture
def source_case(tmp_path):
    for name in rp._INPUTS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (tmp_path / "VERSION").write_text("4.11.4\n")
    (tmp_path / "planning/plan.yaml").write_text("work: []\n")
    (tmp_path / "history/plan-history.yaml").write_text("work: []\n")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True, stderr=subprocess.DEVNULL).strip()
    git("init", "-b", "main")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("add", "--", *rp._INPUTS)
    git("commit", "-m", "chore: baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "newsfragments").mkdir()
    (tmp_path / "newsfragments/new.feat.md").write_text("Новая возможность\n")
    git("add", "--", "newsfragments/new.feat.md")
    git("commit", "-m", "feat: implementation")
    head = git("rev-parse", "HEAD")
    policy = json.loads((tmp_path / "quality/premerge-checks.json").read_text())
    return tmp_path, Client(head, base, policy)


def test_actual_git_and_full_read_only_api_feed_the_machine_plan(source_case):
    root, client = source_case
    snap = src.capture(root, client)
    assert snap["complete"] and snap["unchanged"]
    result = rp.build(root, snap)
    assert result["plan_ready"] and result["target_version"] == "4.12.0"
    assert snap["pulls"][0]["closing_issues"] == [9]
    assert result["issues"][1]["implementation_observed"] is False
    assert all(path.startswith("repos/owner/kit") for path, _ in client.calls)


@pytest.mark.parametrize("mode", ["403", "truncated", "main_changed", "issue_changed", "rerun"])
def test_api_failure_and_mid_read_changes_fail_closed(source_case, mode):
    root, client = source_case
    client.mode = mode
    snap = src.capture(root, client)
    assert not snap["complete"] and not rp.build(root, snap)["release_ready"]


def test_dirty_tracked_checkout_does_not_produce_trusted_source(source_case):
    root, client = source_case
    (root / "VERSION").write_text("4.12.0\n")
    assert not src.capture(root, client)["complete"]


def test_read_only_capture_does_not_mutate_repo_or_invoke_write_api(source_case):
    root, client = source_case
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert src.capture(root, client)["complete"]
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert before == after
    assert not any(path.endswith(("/comments", "/merges")) for path, _ in client.calls)


def test_object_pagination_checks_all_pages_and_total():
    class Pages:
        def read_page(self, path, params):
            return {"total_count": 101, "jobs": [{"id": i} for i in (range(100) if params["page"] == 1 else [100])]}
    assert len(src.collection(Pages(), "jobs", key="jobs")) == 101
    class Broken(Pages):
        def read_page(self, path, params):
            value = super().read_page(path, params)
            if params["page"] == 2:
                value["total_count"] = 100
            return value
    with pytest.raises(src.SnapshotError):
        src.collection(Broken(), "jobs", key="jobs")


def test_raw_page_reuses_existing_transport_without_implicit_pagination(monkeypatch):
    client = GitHubClient(repo="owner/kit", transport="gh")
    calls = []
    monkeypatch.setattr(client, "_gh_api", lambda path, params, **kw: calls.append((path, params, kw)) or {"total_count": 0, "jobs": []})
    assert client.read_page("repos/owner/kit/actions/jobs") == {"total_count": 0, "jobs": []}
    assert calls[0][2] == {"paginate": False}
    for path in ("repos/foreign/kit", "https://evil.invalid", "repos/owner/kit/../other", "repos/owner/kit?x=1"):
        with pytest.raises(GitHubError):
            client.read_page(path)
    assert len(calls) == 1


def test_final_predeploy_barrier_rechecks_ci_attempt_and_issue_evidence(source_case):
    root, client = source_case
    snap = src.capture(root, client)
    result = rp.build(root, snap)
    assert result["plan_ready"]
    src.verify_projection(root, result, client)
    client.mode = "rerun"
    with pytest.raises(src.SnapshotError):
        src.verify_projection(root, result, client)


def test_untracked_fragment_cannot_influence_trusted_checkout_plan(source_case):
    root, client = source_case
    (root / "newsfragments/untracked.feat.md").write_text("not source")
    assert not src.capture(root, client)["complete"]


def test_duplicate_pages_are_not_evidence_of_full_inventory():
    class Duplicate:
        def read_page(self, path, params):
            return [{"id": 1}, {"id": 1}]
    with pytest.raises(src.SnapshotError):
        src.collection(Duplicate(), "issues")


def test_historical_dependency_reads_its_pr_ci_and_real_published_ancestry(source_case):
    root, client = source_case
    (root / "planning/plan.yaml").write_text("work:\n- id: next-kit-release-4-12-0\n  depends_on: [previous]\n")
    (root / "history/plan-history.yaml").write_text("work:\n- id: previous\n  status: done\n  pr: 11\n")
    subprocess.run(["git", "add", "--", "planning/plan.yaml", "history/plan-history.yaml"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--amend", "--no-edit"], cwd=root, check=True, capture_output=True)
    client.head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    original = client.read_page
    def read(path, params=None):
        if path.endswith("/pulls/11"):
            return {"number": 11, "merged": True, "state": "closed", "merge_commit_sha": client.base,
                    "head": {"sha": "4" * 40}, "base": {"ref": "main", "sha": "5" * 40}, "changed_files": 1}
        value = original(path, params)
        if params and params.get("head_sha") == "4" * 40:
            for run in value.get("workflow_runs", []):
                run["head_sha"] = "4" * 40
                run["pull_requests"] = [{"number": 11, "head": {"sha": "4" * 40}, "base": {"sha": "5" * 40}}]
        return value
    client.read_page = read
    snapshot = src.capture(root, client)
    assert snapshot["complete"] and snapshot["dependency_pulls"][0]["published_ancestor"] == client.base
    report = rp.build(root, snapshot)
    assert report["plan_ready"] and report["dependency_gaps"] == []
    assert len(report["included_commits"]) == 1


@pytest.mark.skipif(os.environ.get("AI_OPS_RELEASE_PROJECTION_VERIFY") != "1",
                    reason="live predeploy assertion runs only in stock dashboard publisher")
def test_live_projection_is_current_before_deploy():
    assert os.environ.get("GITHUB_ACTIONS") == "true", "live projection verification requires Actions context"
    assert os.environ.get("GITHUB_REF") == "refs/heads/" + os.environ["GITHUB_REF_NAME"]
    report = json.loads((ROOT / "dashboard/data.json").read_text())["release_plan"]
    client = GitHubClient(repo=os.environ["GITHUB_REPOSITORY"])
    src.verify_projection(ROOT, report, client)


def test_issue_closed_during_previous_release_publication_is_not_filtered_out(source_case):
    root, client = source_case
    original = client.read_page
    def read(path, params=None):
        data = original(path, params)
        if path.endswith("/issues"):
            data[0]["closed_at"] = "2026-10-26T11:59:00Z"  # before published_at, code is still in cut
        return data
    client.read_page = read
    snap = src.capture(root, client)
    assert snap["complete"] and snap["pulls"][0]["closing_issues"] == [9]
    assert rp.build(root, snap)["issues"][0]["ci_chain_observed"]


def test_canonical_closing_query_paginates_and_does_not_parse_pr_body(monkeypatch):
    client = GitHubClient(repo="owner/kit", transport="gh")
    pages = [
        {"totalCount": 2, "nodes": [{"number": 9, "repository": {"nameWithOwner": "owner/kit"}}],
         "pageInfo": {"hasNextPage": True, "endCursor": "next"}},
        {"totalCount": 2, "nodes": [{"number": 10, "repository": {"nameWithOwner": "foreign/kit"}}],
         "pageInfo": {"hasNextPage": False, "endCursor": "end"}},
    ]
    calls = []
    def page(number, cursor):
        calls.append((number, cursor))
        return pages.pop(0)
    monkeypatch.setattr(client, "_closing_page", page)
    result = client.closing_issue_numbers(20)
    assert result.ok and result.items == [9]
    assert calls == [(20, None), (20, "next")]


@pytest.mark.parametrize("failure", ["403", "partial", "bool_count", "duplicate", "repeated_cursor", "changed_total"])
def test_canonical_closing_query_never_turns_api_failure_into_empty_success(monkeypatch, failure):
    client = GitHubClient(repo="owner/kit", transport="gh")
    good = {"totalCount": 1, "nodes": [{"number": 9, "repository": {"nameWithOwner": "owner/kit"}}],
            "pageInfo": {"hasNextPage": False, "endCursor": "end"}}
    calls = []
    def page(number, cursor):
        calls.append(cursor)
        value = deepcopy(good)
        if failure == "403":
            raise GitHubError("HTTP 403")
        if failure == "partial":
            value["totalCount"] = 2
        elif failure == "bool_count":
            value["totalCount"] = True
        elif failure == "duplicate":
            value["nodes"] *= 2
            value["totalCount"] = 2
        elif failure == "repeated_cursor":
            value["pageInfo"] = {"hasNextPage": True, "endCursor": "same"}
        elif failure == "changed_total":
            value["totalCount"] = 2 if len(calls) == 1 else 3
            value["pageInfo"] = {"hasNextPage": True, "endCursor": "next"}
        return value
    monkeypatch.setattr(client, "_closing_page", page)
    result = client.closing_issue_numbers(20)
    assert not result.ok and result.items == []


def test_canonical_query_transport_is_fixed_read_only_without_mutation(monkeypatch):
    from types import SimpleNamespace
    calls = []
    payload = {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
        "totalCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
    def run(args, **kwargs):
        body = json.loads(kwargs["input"])
        assert "mutation" not in body["query"]
        assert body["variables"]["number"] == 20
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())
    monkeypatch.setattr("ai_ops_kit.integrations.github.subprocess.run", run)
    client = GitHubClient(repo="owner/kit", transport="gh")
    assert client.closing_issue_numbers(20).ok
    assert calls == [["gh", "api", "graphql", "--input", "-"]]


def test_missing_canonical_link_permission_invalidates_snapshot(source_case):
    root, client = source_case
    client.closing_issue_numbers = lambda _: FetchResult(False, reason="HTTP 403")
    assert not src.capture(root, client)["complete"]
