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


@pytest.mark.parametrize("prior", [None, {"repository": "owner/kit"}])
def test_refresh_supplies_only_previous_boundary_result_to_model(monkeypatch, tmp_path, prior):
    from ai_ops_kit.devtools import release_plan_state as state
    calls = []
    client = type("ReadClient", (), {"repo": "owner/kit"})()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(src, "capture", lambda root, c: {"repository": c.repo})
    def previous(c, *, current_run):
        assert c is client and current_run is None
        calls.append("verified-boundary")
        return prior
    def build(root, snapshot, *, prior):
        calls.append("model")
        assert calls == ["verified-boundary", "model"]
        return {"prior": prior}
    monkeypatch.setattr(state, "previous", previous)
    monkeypatch.setattr(rp, "build", build)
    monkeypatch.setattr(state, "project", lambda report, old, publisher: report)
    assert src.refresh(tmp_path, client) == {"prior": prior}


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
        if tail == "/pulls":
            return []
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


class ProducerClient(Client):
    """Платформа до/после реального fixture merge; никаких внешних API."""
    def __init__(self, original, feature):
        super().__init__(original.head, original.base, original.policy)
        self.original, self.feature, self.phase = original.head, feature, "open"
        self.foreign = False
        self.spoof = False

    def read_page(self, path, params=None):
        params = params or {}
        tail = path.removeprefix("repos/owner/kit")
        if tail == "/pulls":
            return [{"id": 11, "number": 11}] if self.phase == "open" else []
        if tail == "/pulls/11":
            repo = "foreign/kit" if self.foreign else self.repo
            return {"number": 11, "merged": self.phase == "merged", "state": "closed" if self.phase == "merged" else "open",
                    "merge_commit_sha": self.head if self.phase == "merged" else None,
                    "head": {"sha": self.feature, "repo": {"full_name": repo}},
                    "base": {"sha": self.original, "ref": "main", "repo": {"full_name": self.repo}},
                    "changed_files": 1}
        if tail == f"/commits/{self.original}/pulls":
            return [{"id": 10, "number": 10}]
        if self.phase == "merged" and tail == f"/commits/{self.head}/pulls":
            return [{"id": 11, "number": 11}]
        if tail == f"/commits/{self.feature}/pulls":
            return [{"id": 11, "number": 11, "head": {"sha": self.feature}}]
        if tail == "/pulls/10":
            return {"number": 10, "merged": True, "state": "closed", "merge_commit_sha": self.original,
                    "head": {"sha": "3" * 40}, "base": {"ref": "main", "sha": self.base}, "changed_files": 1}
        for i, (workflow, names) in enumerate(self.policy.items(), start=1):
            if tail == f"/actions/workflows/{workflow}/runs" and params.get("head_sha") == self.feature:
                origin = "https://api.github.com/repos/" + ("foreign/kit" if self.spoof else self.repo)
                assoc = {"number": 11, "head": {"sha": self.feature, "repo": {"url": origin}},
                         "base": {"sha": self.original, "repo": {"url": origin}}}
                return {"total_count": 1, "workflow_runs": [{"id": 100+i, "run_attempt": 1,
                    "path": ".github/workflows/"+workflow, "head_sha": self.feature,
                    "event": "pull_request", "status": "completed", "conclusion": "success",
                    "pull_requests": [assoc] if self.phase == "open" else []}]}
            if tail == f"/actions/runs/{100+i}/attempts/1/jobs":
                jobs = [{"id": 1000+i*100+j, "name": n, "status": "completed", "conclusion": "success"}
                        for j, n in enumerate(names)]
                return {"total_count": len(jobs), "jobs": jobs}
        return super().read_page(path, params)


@pytest.fixture
def producer_case(source_case):
    root, original = source_case
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    git("checkout", "-b", "fixture-feature")
    (root / "feature.txt").write_text("actual fixture change\n")
    git("add", "feature.txt")
    git("commit", "-m", "feat: future change")
    feature = git("rev-parse", "HEAD")
    git("checkout", "main")
    return root, ProducerClient(original, feature), git


def _verified_fixture_archive(report, *, forged=False, tampered=False):
    from ai_ops_kit.devtools import release_plan_state as state
    publisher = {"run_id": 900, "attempt": 1, "checkout_sha": report["source"]["sha"], "branch": "main"}
    payload = state.project(report, None, publisher)
    if tampered:
        payload["ci_archive"][0]["head"] = "f" * 40
    class Deployment:
        repo = "owner/kit"
        def read_page(self, path, params=None):
            if path == "repos/owner/kit":
                return {"default_branch": "main"}
            if path.endswith("/runs"):
                return {"workflow_runs": [{"id": 900, "run_attempt": 1, "path": ".github/workflows/status-dashboard.yml",
                    "event": "push", "head_branch": "main", "head_sha": publisher["checkout_sha"]}]}
            return {"total_count": 1, "jobs": [{"id": 901, "steps": [{"name": "Опубликовать на GitHub Pages",
                            "status": "completed", "conclusion": "failure" if forged else "success"}]}]}
    # Моделируется реальный trust boundary, а не самостоятельный verified:true/digest.
    return state.previous(Deployment(), read=lambda _: {"release_plan": payload})


def test_producer_published_archive_and_lost_association_lookup_end_to_end(producer_case):
    root, client, git = producer_case
    before = src.capture(root, client)
    assert before["complete"] and len(before["ci_archive"]) == 1
    report = rp.build(root, before)
    prior = _verified_fixture_archive(report)
    assert prior is not None and prior["ci_archive"][0]["head"] == client.feature
    git("merge", "--no-ff", "--no-edit", "fixture-feature")
    client.head, client.phase = git("rev-parse", "HEAD"), "merged"
    assert git("show", "-s", "--format=%P", "HEAD").split()[0] == client.original
    after = src.capture(root, client)
    assert after["complete"] and after["ci"]["11"][0]["pull_requests"] == []
    saved = deepcopy(after), deepcopy(prior)
    assert not rp.build(root, after)["implementation_evidence_complete"]
    recovered = rp.build(root, after, prior=prior)
    assert recovered["implementation_evidence_complete"]
    assert not recovered["release_ready"] and recovered["publication_authorized"] is None
    assert (after, prior) == saved and not git("status", "--porcelain")


@pytest.mark.parametrize("failure", ["untrusted_deploy", "tampered_archive", "base", "parent", "head", "policy", "rerun", "jobs"])
def test_premerge_archive_never_authenticates_changed_or_untrusted_history(producer_case, failure):
    root, client, git = producer_case
    report = rp.build(root, src.capture(root, client))
    prior = _verified_fixture_archive(report, forged=failure == "untrusted_deploy", tampered=failure == "tampered_archive")
    git("merge", "--no-ff", "--no-edit", "fixture-feature")
    client.head, client.phase = git("rev-parse", "HEAD"), "merged"
    snap = src.capture(root, client)
    if failure in ("untrusted_deploy", "tampered_archive"):
        assert prior is None
    elif failure in ("base", "head"):
        prior["ci_archive"][0][failure] = "f" * 40
    elif failure == "parent":
        # Preserve complete ancestry but place another base before the actual merge.
        merged = next(c for c in snap["commits"] if c["sha"] == client.head)
        merged["parents"][0] = client.base
        snap["commits"] = [merged]
    elif failure == "policy":
        prior["input_digests"]["quality/premerge-checks.json"] = "f" * 64
    elif failure == "rerun":
        snap["ci"]["11"][0]["run_attempt"] = snap["ci"]["11"][0]["queried_attempt"] = 2
    else:
        snap["ci"]["11"][0]["jobs"][0]["id"] += 1
    assert not rp.build(root, snap, prior=prior)["implementation_evidence_complete"]
    assert not rp.build(root, snap, prior=prior)["release_ready"]


@pytest.mark.parametrize("spoof", [False, True])
def test_producer_rejects_foreign_repository_and_spoofed_native_association(producer_case, spoof):
    root, client, _ = producer_case
    client.spoof, client.foreign = spoof, not spoof
    snap = src.capture(root, client)
    assert snap["complete"] and snap["ci_archive"] == []


@pytest.mark.parametrize("change", ["head", "closed", "job_id", "job_failed", "job_missing"])
def test_producer_final_barrier_detects_identity_and_job_mutation(producer_case, monkeypatch, change):
    root, client, _ = producer_case
    snap = src.capture(root, client)
    assert len(snap["ci_archive"]) == 1
    original = client.read_page
    def changed(path, params=None):
        value = deepcopy(original(path, params))
        if path.endswith("/pulls/11"):
            if change == "head":
                value["head"]["sha"] = "f" * 40
            elif change == "closed":
                value["state"], value["merged"] = "closed", True
        if "/actions/runs/101/" in path:
            if change == "job_id":
                value["jobs"][0]["id"] += 1
            elif change == "job_failed":
                value["jobs"][0]["conclusion"] = "failure"
            elif change == "job_missing":
                value["jobs"] = []
                value["total_count"] = 0
        return value
    monkeypatch.setattr(client, "read_page", changed)
    with pytest.raises(src.SnapshotError):
        src._verify_open(client, "main", snap["validation"]["open_ci_queries"], client.policy)


def test_archive_predeploy_verification_is_wired_to_existing_publisher(producer_case, monkeypatch):
    root, client, _ = producer_case
    snap = src.capture(root, client)
    report = rp.build(root, snap)
    def barrier(c, branch, queries, policy):
        assert c is client and branch == "main" and len(queries) == 1
        raise src.SnapshotError("fixture proves final producer barrier executed")
    monkeypatch.setattr(src, "_verify_open", barrier)
    with pytest.raises(src.SnapshotError, match="producer barrier executed"):
        src.verify_projection(root, report, client)


@pytest.mark.parametrize("failure", ["run_failed", "job_failed", "missing_id", "duplicate_id"])
def test_producer_does_not_archive_incomplete_or_failed_ci(producer_case, monkeypatch, failure):
    root, client, _ = producer_case
    original = client.read_page
    def changed(path, params=None):
        value = deepcopy(original(path, params))
        if failure == "run_failed" and isinstance(value, dict) and value.get("workflow_runs"):
            value["workflow_runs"][0]["conclusion"] = "failure"
        if "/actions/runs/101/" in path:
            if failure == "job_failed":
                value["jobs"][0]["conclusion"] = "failure"
            elif failure == "missing_id":
                value["jobs"][0].pop("id")
            elif failure == "duplicate_id":
                value["jobs"].append(deepcopy(value["jobs"][0]))
                value["total_count"] += 1
        return value
    monkeypatch.setattr(client, "read_page", changed)
    snap = src.capture(root, client)
    assert snap.get("ci_archive", []) == []
    assert not rp.build(root, snap)["release_ready"]


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
    assert "diagnostic" not in snap and "unavailable_diagnostic" not in result


@pytest.mark.parametrize("mode,code,field", [
    ("403", "github_read_permission_denied", None),
    ("truncated", "collection_incomplete", None),
    ("main_changed", "default_branch_changed", "main_sha"),
    ("issue_changed", "issues_changed", "issues"),
    ("rerun", "ci_changed", "ci_signature"),
])
def test_capture_projects_safe_diagnostics_without_admitting_changed_source(source_case, mode, code, field):
    root, client = source_case
    client.mode = mode
    snap = src.capture(root, client)
    diagnostic = snap["diagnostic"]
    assert diagnostic["code"] == code
    if field:
        assert diagnostic["field"] == field
    if mode == "rerun":
        assert diagnostic == {"code": code, "workflow": "docs.yml", "run_id": 1,
                              "attempt": 2, "field": field}
    result = rp.build(root, snap)
    assert result["unavailable_diagnostic"] == diagnostic
    assert result["blockers"] == ["source_unknown_or_invalid"]
    assert not snap["complete"] and not snap["unchanged"]
    assert not result["composition_available"] and not result["release_ready"]
    assert result["publication_authorized"] is None and result["source"] is None
    if field:
        assert sum(p.endswith({"main_changed": "/commits/main", "issue_changed": "/issues",
                               "rerun": "/actions/workflows/docs.yml/runs"}[mode]) for p, _ in client.calls) > 1


@pytest.mark.parametrize("change,code,field", [
    ("head", "open_pr_identity_changed", "head_sha"),
    ("base", "open_pr_identity_changed", "base_sha"),
    ("closed", "open_pr_identity_changed", "identity"),
    ("jobs", "open_pr_ci_changed", "jobs"),
])
def test_open_pr_diagnostic_identifies_actual_mutation(producer_case, monkeypatch, change, code, field):
    root, client, _ = producer_case
    original, reads, mutations = client.read_page, {}, []
    def read(path, params=None):
        data = deepcopy(original(path, params))
        reads[path] = reads.get(path, 0) + 1
        if reads[path] > 1 and path.endswith("/pulls/11") and change != "jobs":
            before = deepcopy(data)
            if change == "closed":
                data["state"], data["merged"] = "closed", True
            else:
                data[change]["sha"] = "f" * 40
            assert data != before
            mutations.append(path)
        if reads[path] > 1 and "/actions/runs/101/" in path and change == "jobs":
            data["jobs"][0]["id"] += 1
            mutations.append(path)
        return data
    monkeypatch.setattr(client, "read_page", read)
    snap = src.capture(root, client)
    assert mutations and not snap["complete"]
    assert snap["diagnostic"] == {"code": code, "pr": 11, "field": field}
    assert not rp.build(root, snap)["release_ready"]


@pytest.mark.parametrize("change,code,field", [
    ("links", "closing_issues_changed", "closing_issues"),
    ("release_ci", "release_ci_changed", "release_ci_signature"),
    ("published", "published_release_changed", "published_release"),
    ("inputs", "release_inputs_changed", "input_digests"),
])
def test_remaining_final_consistency_branches_keep_specific_diagnostics(source_case, monkeypatch, change, code, field):
    root, client = source_case
    reads, mutations = {}, []
    original = client.read_page
    def read(path, params=None):
        data = deepcopy(original(path, params))
        reads[path] = reads.get(path, 0) + 1
        if change == "release_ci" and path.endswith("/workflows/release.yml/runs") and reads[path] > 1:
            data = {"total_count": 1, "workflow_runs": [{"id": 99, "run_attempt": 1,
                    "status": "in_progress", "conclusion": None}]}
            mutations.append(path)
        if change == "published" and path.endswith("/releases") and reads[path] > 1:
            data[0]["id"] += 1
            mutations.append(path)
        return data
    monkeypatch.setattr(client, "read_page", read)
    if change == "links":
        calls = []
        def links(number):
            calls.append(number)
            items = [9] if len(calls) == 1 else []
            if len(calls) > 1:
                mutations.append(number)
            return FetchResult(True, items=items)
        monkeypatch.setattr(client, "closing_issue_numbers", links)
    if change == "inputs":
        verify = src._verify_open
        def mutate(*args):
            verify(*args)
            (root / "VERSION").write_text("4.12.0\n")
            assert (root / "VERSION").read_text() == "4.12.0\n"
            mutations.append("VERSION")
        monkeypatch.setattr(src, "_verify_open", mutate)
    snap = src.capture(root, client)
    assert mutations and not snap["complete"]
    diagnostic = {"code": code, "field": field}
    if change == "links":
        diagnostic["pr"] = 10
    if change == "release_ci":
        diagnostic.update(workflow="release.yml", run_id=99, attempt=1)
    assert snap["diagnostic"] == diagnostic
    assert rp.build(root, snap)["unavailable_diagnostic"] == diagnostic
    assert not rp.build(root, snap)["release_ready"]


@pytest.mark.parametrize("error,code", [
    (GitHubError, "github_read_failed"), (OSError, "source_io_unavailable"),
    (ValueError, "source_invalid"), (TypeError, "source_invalid"),
    (KeyError, "source_invalid"), (src.SnapshotError, "snapshot_invalid"),
    (src.yaml.YAMLError, "source_invalid"),
])
def test_exception_text_never_escapes_diagnostics(source_case, monkeypatch, capsys, caplog, error, code):
    root, client = source_case
    secret = "SENSITIVE_TOKEN_person@example.invalid_title_body_api_payload"
    def fail(*args):
        raise error(secret)
    monkeypatch.setattr(client, "read_page", fail)
    snap = src.capture(root, client)
    assert snap["diagnostic"] == {"code": code}
    report = rp.build(root, snap)
    assert report["unavailable_diagnostic"] == {"code": code}
    captured = capsys.readouterr()
    assert secret not in json.dumps([snap, report]) + captured.out + captured.err + caplog.text
    assert not report["release_ready"]


@pytest.mark.parametrize("mode,code", [
    ("total", "collection_total_invalid_or_changed"),
    ("page", "collection_page_invalid"),
    ("duplicate", "collection_identity_duplicate"),
    ("incomplete", "collection_incomplete"),
    ("budget", "collection_budget_exceeded"),
])
def test_collection_diagnostics_never_copy_malformed_payload(mode, code):
    class Pages:
        def read_page(self, path, params):
            if mode == "total":
                return {"total_count": "SECRET", "jobs": []}
            if mode == "page":
                return {"total_count": 1, "jobs": ["SECRET"]}
            if mode == "duplicate":
                return {"total_count": 2, "jobs": [{"id": 1, "title": "SECRET"}] * 2}
            if mode == "incomplete":
                return {"total_count": 1, "jobs": []}
            return {"total_count": 10001, "jobs": [{"id": params["page"] * 100 + n} for n in range(100)]}
    with pytest.raises(src.SnapshotError) as caught:
        src.collection(Pages(), "fixture", key="jobs")
    assert caught.value.diagnostic == {"code": code}


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


def test_in_flight_open_pr_ci_does_not_void_the_plan(producer_case, monkeypatch):
    """#1446: пока у открытого PR идут проверки, его движение не обнуляет план выпуска."""
    root, client, _ = producer_case
    original, reads = client.read_page, {"jobs": 0}
    def flowing(path, params=None):
        value = deepcopy(original(path, params))
        if "/actions/runs/10" in path and path.endswith("/jobs"):
            reads["jobs"] += 1
            done = reads["jobs"] > len(client.policy)            # второе чтение — проверки дошли
            for job in value["jobs"]:
                job["status"], job["conclusion"] = ("completed", "success") if done else ("in_progress", None)
        return value
    monkeypatch.setattr(client, "read_page", flowing)
    snap = src.capture(root, client)
    assert snap["complete"], snap.get("diagnostic")
    assert snap["ci_archive"] == [] and snap["validation"]["open_ci_queries"] == []


def _merged_with_native_fields(producer_case, monkeypatch, failure=None):
    root, client, git = producer_case
    git("merge", "--no-ff", "--no-edit", "fixture-feature")
    client.head, client.phase = git("rev-parse", "HEAD"), "merged"
    original = client.read_page
    def platform(path, params=None):
        value = deepcopy(original(path, params))
        if path.endswith("/pulls/11"):
            value["head"]["ref"] = "fixture-feature"
            value["merged_at"] = "2026-11-02T00:00:00Z"
            if failure == "fork":
                value["head"]["repo"]["full_name"] = "foreign/kit"
        if path.endswith(f"/commits/{client.feature}/pulls") and failure == "ambiguous":
            value.append({"id": 12, "number": 12, "head": {"sha": client.feature}})
        if isinstance(value, dict) and params and params.get("head_sha") == client.feature:
            for run in value.get("workflow_runs", []):
                run.update(head_branch="other-branch" if failure == "branch" else "fixture-feature",
                           head_repository={"full_name": "foreign/kit" if failure == "run_fork" else "owner/kit"},
                           created_at="2026-11-03T00:00:00Z" if failure == "after_merge" else "2026-11-01T00:00:00Z")
        return value
    monkeypatch.setattr(client, "read_page", platform)
    snap = src.capture(root, client)
    assert snap["complete"], snap.get("diagnostic")
    if failure == "parent":
        merged = next(c for c in snap["commits"] if c["sha"] == client.head)
        merged["parents"][0] = client.base
        snap["commits"] = [merged]
    return root, snap


def test_merged_pr_ci_is_bound_without_any_archive(producer_case, monkeypatch):
    """#1446: сливаем сразу по зелёному — архив не успевает; связь восстанавливается из самого GitHub."""
    root, snap = _merged_with_native_fields(producer_case, monkeypatch)
    assert snap["ci"]["11"][0]["pull_requests"] == [] and snap["pulls"][0]["head_prs"] == [11]
    report = rp.build(root, snap)
    assert report["implementation_evidence_complete"]
    assert not report["release_ready"] and report["publication_authorized"] is None


@pytest.mark.parametrize("failure", ["fork", "run_fork", "branch", "after_merge", "ambiguous", "parent"])
def test_post_merge_binding_never_accepts_a_lookalike_run(producer_case, monkeypatch, failure):
    root, snap = _merged_with_native_fields(producer_case, monkeypatch, failure)
    assert not rp.build(root, snap)["implementation_evidence_complete"]
