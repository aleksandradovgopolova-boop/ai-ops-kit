"""Read-only GitHub fixture backed by regular files, trees and commits from real Git."""
import base64
from copy import deepcopy
import json
import subprocess

import pytest

from ai_ops_kit.devtools import release_assembly, release_child_observation as child
from ai_ops_kit.integrations import github

REPO = "example/child"
PREFIX = f"repos/{REPO}"
VERSION = ".ai/managed/VERSION"
CONFIG = ".ai-ops.yaml"


@pytest.fixture(scope="module")
def history(tmp_path_factory):
    root = tmp_path_factory.mktemp("child")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (root / VERSION).parent.mkdir(parents=True)
    commits = []
    for version in ("2.0.0", "1.0.0", "2.0.0"):
        (root / VERSION).write_text(version + "\n")
        (root / CONFIG).write_text(f"parent:\n  installed_version: {version}\n"
                                   '  update_channel: stable\n  update_policy: pr\n'
                                   '  allowed_version_range: ">=1.0.0 <3.0.0"\n  unrelated: private-extra-value\n')
        git("add", ".")
        git("commit", "-qm", version)
        commits.append(git("rev-parse", "HEAD"))
    git("commit", "--allow-empty", "-qm", "later")
    start, prev, merge = commits
    head = git("rev-parse", "HEAD")
    repo = {"id": 11, "full_name": REPO, "default_branch": "main"}
    pull = {"number": 2, "state": "closed", "merged": True, "merge_commit_sha": merge,
            "merged_at": "2026-02-07T12:00:00Z", "base": {"ref": "main", "sha": prev, "repo": repo}}
    pages = {"": repo, "git/ref/heads/main": {"ref": "refs/heads/main", "object": {"type": "commit", "sha": head}},
             "commits": [{"sha": merge}], f"compare/{merge}...{head}": {"status": "ahead",
             "base_commit": {"sha": merge}, "merge_base_commit": {"sha": merge}},
             f"commits/{merge}/pulls": [dict(pull)], "pulls/2": dict(pull)}
    for commit in (start, prev, merge, head):
        pages[f"git/commits/{commit}"] = {"sha": commit, "tree": {"sha": git("rev-parse", f"{commit}^{{tree}}")},
                                          "parents": [{"sha": p} for p in git("show", "-s", "--format=%P", commit).split()]}
        for directory in ("", ".ai", ".ai/managed"):
            tree = git("rev-parse", commit + ":" + directory)
            entries = []
            for line in git("ls-tree", "-l", tree).splitlines():
                mode, kind, oid, size, name = line.split()
                entry = {"mode": mode, "type": kind, "sha": oid, "path": name}
                if kind == "blob":
                    data = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", oid])
                    entry["size"] = int(size)
                    pages[f"git/blobs/{oid}"] = {"encoding": "base64", "sha": oid, "size": len(data),
                                                 "content": base64.encodebytes(data).decode()}
                entries.append(entry)
            pages[f"git/trees/{tree}"] = {"sha": tree, "tree": entries, "truncated": False}
    return pages, git, merge, head


@pytest.fixture
def api(history, monkeypatch):
    pages, git, merge, head = history
    pages = deepcopy(pages)
    calls = []
    monkeypatch.setattr(github, "_has_gh", lambda: True)

    def read(client, path, params=None, *, paginate=True):
        assert paginate is False
        calls.append((path, params))
        if client.repo == "example/unavailable":
            raise github.GitHubError("private error text")
        assert path == PREFIX or path.startswith(PREFIX + "/")
        result = pages[path[len(PREFIX):].lstrip("/")]
        return result() if callable(result) else result
    monkeypatch.setattr(github.GitHubClient, "_gh_api", read)
    return pages, git, merge, head, calls


def test_owner_cli_reads_selected_repositories_and_preserves_git_state(api, tmp_path, monkeypatch, capsys):
    pages, git, merge, head, calls = api
    monkeypatch.chdir(tmp_path)
    refs = git("show-ref")
    assert pages["pulls/2"]["base"]["sha"] == git("rev-parse", merge + "^")
    assert git("show", f"{merge}^:{VERSION}") == "1.0.0"
    assert git("show", f"{merge}:{VERSION}") == "2.0.0"
    rc = release_assembly.main(["cli", "--child-delivery", "example/unavailable", REPO])
    output = capsys.readouterr().out
    bad, good = json.loads(output)["rows"]
    assert rc == 1 and bad["version"]["state"] == "unknown" and "private error text" not in output
    assert good["version"] == {"state": "observed", "value": "2.0.0",
                               "blobs": {p: git("rev-parse", f"{head}:{p}") for p in (VERSION, CONFIG)}}
    assert good["update_pr"] == {"state": "observed", "number": 2, "merge_sha": merge,
                                 "merged_at": pages["pulls/2"]["merged_at"], "from_version": "1.0.0",
                                 "to_version": "2.0.0"}
    assert good["default_branch"]["sha"] == head
    assert good["policy"] == {"update_channel": "stable", "update_policy": "pr", "allowed_version_range": ">=1.0.0 <3.0.0"}
    assert "private-extra-value" not in output
    assert good["production_runtime"] == good["production_restore"] == "unknown"
    assert (PREFIX + "/commits", {"sha": head, "path": VERSION, "per_page": 1}) in calls
    assert calls[-1][0] == PREFIX + "/git/ref/heads/main"
    assert git("status", "--porcelain") == "" and git("show-ref") == refs and not list(tmp_path.iterdir())


@pytest.mark.parametrize("case", ["unmerged", "wrong_merge", "wrong_repo", "wrong_name", "wrong_base", "no_transition",
                                  "not_ancestor", "ambiguous", "pr_unavailable", "unexpected_type", "bad_time", "parent_config_conflict", "missing_base_sha"])
def test_unverified_pr_keeps_observed_version(api, case):
    pages, git, merge, head, _ = api
    pr = deepcopy(pages["pulls/2"])
    pages["pulls/2"] = pr
    if case == "unmerged":
        pr["merged"] = False
    elif case == "wrong_merge":
        pr["merge_commit_sha"] = head
    elif case == "wrong_repo":
        pr["base"]["repo"]["id"] += 1
    elif case == "wrong_name":
        pr["base"]["repo"]["full_name"] = "other/child"
    elif case == "missing_base_sha":
        del pr["base"]["sha"]
    elif case == "wrong_base":
        pr["base"]["ref"] = "draft"
    elif case == "no_transition":
        pages["git/commits/" + merge]["parents"] = [{"sha": head}]
    elif case == "parent_config_conflict":
        tree = pages["git/trees/" + git("rev-parse", merge + "^:")]
        next(e for e in tree["tree"] if e["path"] == CONFIG)["sha"] = git("rev-parse", f"{head}:{CONFIG}")
    elif case == "not_ancestor":
        pages[f"compare/{merge}...{head}"]["merge_base_commit"]["sha"] = "a" * 40
    elif case == "ambiguous":
        pages[f"commits/{merge}/pulls"] *= 2
    elif case == "pr_unavailable":
        del pages["pulls/2"]
    elif case == "unexpected_type":
        pr["base"]["repo"]["full_name"] = []
    else:
        pr["merged_at"] = "yesterday"
    row = child.observe(REPO)
    assert row["version"]["value"] == "2.0.0" and row["update_pr"]["state"] == "unknown"


def test_rebased_pr_with_no_net_version_change_cannot_claim_its_last_commit(api):
    pages, git, merge, head, _ = api
    base = git("rev-parse", merge + "~2")
    pages["pulls/2"]["base"]["sha"] = base
    assert git("rev-list", "--count", f"{base}..{merge}") == "2"
    assert git("show", f"{base}:{VERSION}") == git("show", f"{merge}:{VERSION}") == "2.0.0"
    assert git("show", f"{merge}^:{VERSION}") == "1.0.0"
    row = child.observe(REPO)
    assert row["default_branch"]["sha"] == head and row["version"]["value"] == "2.0.0"
    assert row["update_pr"]["state"] == "unknown"


@pytest.mark.parametrize("case", ["blob_bytes", "config_conflict", "symlink", "incomplete_tree", "head_moves",
                                  "default_changes", "repository_replaced"])
def test_unverified_version_never_claims_delivery(api, case):
    pages, git, _, head, _ = api
    tree = pages["git/trees/" + git("rev-parse", head + ":")]
    if case == "blob_bytes":
        pages["git/blobs/" + git("rev-parse", f"{head}:{VERSION}")]["content"] = "My4wLjAK"
    elif case == "config_conflict":
        entry = next(e for e in tree["tree"] if e["path"] == CONFIG)
        entry["sha"] = git("rev-parse", f"{head}~2:{CONFIG}")
    elif case == "symlink":
        next(e for e in tree["tree"] if e["path"] == CONFIG)["mode"] = "120000"
    elif case == "incomplete_tree":
        tree["truncated"] = True
    elif case == "head_moves":
        ref = pages["git/ref/heads/main"]
        response = iter([ref, {**ref, "object": {"type": "commit", "sha": "c" * 40}}])
        pages["git/ref/heads/main"] = lambda: next(response)
    else:
        meta = pages[""]
        other = {**meta, "default_branch": "trunk"} if case == "default_changes" else {**meta, "id": 12}
        response = iter([meta, other])
        pages[""] = lambda: next(response)
    row = child.observe(REPO)
    assert row["version"]["state"] == row["update_pr"]["state"] == "unknown"


@pytest.mark.parametrize("slug", [".", "../child", "org/..", "https://github.com/example/child", "org/r?x=1"])
def test_requires_explicit_slug_without_requests(api, slug):
    assert child.observe(slug)["reason"] == "invalid_repository"
    assert api[-1] == []


def test_stock_mode_succeeds_for_observed_pr(api, capsys):
    assert release_assembly.main(["cli", "--child-delivery", REPO]) == 0
    assert json.loads(capsys.readouterr().out)["rows"][0]["repo"] == REPO


def test_missing_or_malformed_policy_fields_do_not_invalidate_the_version(api):
    pages, git, _, head, _ = api
    # Независимая точная пара blob для старого формата конфига.
    data = b"parent:\n  installed_version: 2.0.0\n  update_policy: []\n"
    oid = subprocess.check_output(["git", "hash-object", "--stdin"], input=data).decode().strip()
    tree = pages["git/trees/" + git("rev-parse", head + ":")]
    next(e for e in tree["tree"] if e["path"] == CONFIG).update(sha=oid, size=len(data))
    pages["git/blobs/" + oid] = {"sha": oid, "size": len(data), "encoding": "base64",
                                 "content": base64.encodebytes(data).decode()}
    row = child.observe(REPO)
    assert row["version"]["value"] == "2.0.0"
    assert row["policy"] == {"update_channel": None, "update_policy": None, "allowed_version_range": None}
