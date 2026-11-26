"""Частное чтение версии Кита и PR обновления в выбранном репозитории GitHub."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import re
from urllib.parse import quote

import yaml

from ai_ops_kit.integrations.github import GitHubClient, GitHubError, parse_slug

_VERSION_PATH = ".ai/managed/VERSION"
_CONFIG_PATH = ".ai-ops.yaml"
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
_READ_ERRORS = (GitHubError, KeyError, IndexError, AttributeError, TypeError, ValueError, RecursionError, yaml.YAMLError)


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _oid(value: str) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "invalid_oid")
    return value


class _Repository:
    """Протокольные чтения Git. Кешировать можно только объекты с неизменяемым SHA."""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client
        self.repo = client.repo
        self.objects: dict[tuple[str, str], dict] = {}

    def read(self, path: str = "", params: dict | None = None) -> dict | list:
        prefix = f"repos/{self.repo}"
        return self.client.read_page(f"{prefix}/{path}" if path else prefix, params)

    def default_branch(self) -> tuple[int, str, str]:
        meta = self.read()
        name_on_server = meta["full_name"]
        _require(isinstance(name_on_server, str) and name_on_server.lower() == self.repo.lower(), "repository_mismatch")
        repo_id, name = meta["id"], meta["default_branch"]
        _require(type(repo_id) is int and repo_id > 0 and isinstance(name, str) and name, "invalid_repository")
        ref = self.read("git/ref/heads/" + quote(name, safe=""))
        _require(ref["ref"] == "refs/heads/" + name and ref["object"]["type"] == "commit", "invalid_ref")
        return repo_id, name, _oid(ref["object"]["sha"])

    def git_object(self, kind: str, sha: str) -> dict:
        key = (kind, _oid(sha))
        if key not in self.objects:
            obj = self.read(f"git/{kind}/{sha}")
            _require(isinstance(obj, dict) and obj["sha"] == sha, "git_object_mismatch")
            self.objects[key] = obj
        return self.objects[key]

    def file(self, commit: str, path: str, limit: int) -> tuple[bytes, str]:
        tree = self.git_object("commits", commit)["tree"]["sha"]
        parts = path.split("/")
        for index, part in enumerate(parts):
            listing = self.git_object("trees", tree)
            _require(listing["truncated"] is False and isinstance(listing["tree"], list), "incomplete_tree")
            entries = [e for e in listing["tree"] if e["path"] == part]
            _require(len(entries) == 1, "missing_entry")
            entry = entries[0]
            if index < len(parts) - 1:
                _require((entry["mode"], entry["type"]) == ("040000", "tree"), "not_directory")
                tree = entry["sha"]
        _require(entry["mode"] in ("100644", "100755") and entry["type"] == "blob", "not_regular")
        _require(type(entry["size"]) is int and 0 < entry["size"] <= limit, "blob_size")
        oid = _oid(entry["sha"])
        blob = self.git_object("blobs", oid)
        _require(blob["encoding"] == "base64" and type(blob["size"]) is int
                 and blob["size"] == entry["size"], "invalid_blob")
        data = base64.b64decode("".join(blob["content"].splitlines()), validate=True)
        header = f"blob {len(data)}\0".encode("ascii")
        _require(len(data) == entry["size"] and hashlib.sha1(header + data).hexdigest() == oid, "blob_mismatch")
        return data, oid

    def installation(self, sha: str) -> tuple[dict, dict]:
        data, managed = self.file(sha, _VERSION_PATH, 256)
        value = data.decode("ascii").strip()
        config, declared = self.file(sha, _CONFIG_PATH, 1024 * 1024)
        parent = yaml.safe_load(config)["parent"]
        _require(_VERSION.fullmatch(value) and parent["installed_version"] == value, "versions_disagree")
        version = {"state": "observed", "value": value, "blobs": {_VERSION_PATH: managed, _CONFIG_PATH: declared}}
        return version, _declared_policy(parent)

    def transition(self, head: str, value: str) -> tuple[str, str]:
        history = self.read("commits", {"sha": head, "path": _VERSION_PATH, "per_page": 1})
        _require(isinstance(history, list) and len(history) == 1, "version_history_unknown")
        merge = _oid(history[0]["sha"])
        if merge != head:
            reach = self.read(f"compare/{merge}...{head}", {"per_page": 1})
            _require(reach["status"] == "ahead" and reach["base_commit"]["sha"] == merge
                     and reach["merge_base_commit"]["sha"] == merge, "not_an_ancestor")
        _require(self.installation(merge)[0]["value"] == value, "merge_version_mismatch")
        parents = self.git_object("commits", merge)["parents"]
        _require(isinstance(parents, list) and len(parents) in (1, 2), "first_parent_unknown")
        previous = self.installation(_oid(parents[0]["sha"]))[0]["value"]
        _require(previous != value, "no_version_transition")
        return merge, previous

    def update_pr(self, repo_id: int, branch: str, head: str, value: str) -> dict:
        merge, previous = self.transition(head, value)
        associated = self.read(f"commits/{merge}/pulls", {"per_page": 100})
        _require(isinstance(associated, list) and len(associated) < 100, "ambiguous_associations")
        matches = [p["number"] for p in associated if p["merge_commit_sha"] == merge
                   and p["base"]["ref"] == branch and p["base"]["repo"]["id"] == repo_id]
        _require(len(matches) == 1 and type(matches[0]) is int and matches[0] > 0, "pr_unknown")
        number = matches[0]
        pr = self.read(f"pulls/{number}")
        base = pr["base"]["repo"]
        _require(type(pr["number"]) is int and pr["number"] == number and pr["state"] == "closed" and pr["merged"] is True
                 and pr["merge_commit_sha"] == merge and pr["base"]["ref"] == branch
                 and type(base["id"]) is int and base["id"] == repo_id
                 and isinstance(base["full_name"], str) and base["full_name"].lower() == self.repo.lower(), "pr_mismatch")
        merged_at = pr["merged_at"]
        _require(isinstance(merged_at, str), "merge_time_unknown")
        _require(datetime.fromisoformat(merged_at.replace("Z", "+00:00")).utcoffset() is not None, "merge_time_unknown")
        return {"state": "observed", "number": number, "merge_sha": merge, "merged_at": merged_at,
                "from_version": previous, "to_version": value}


def _declared_policy(parent: dict) -> dict:
    """Только три объявленных параметра. Пустое поле означает отсутствие наблюдения."""
    policy = {}
    for key in ("update_channel", "update_policy", "allowed_version_range"):
        value = parent.get(key)
        policy[key] = value if isinstance(value, str) and 0 < len(value) <= 120 and value.isprintable() else None
    return policy


def observe(repo: str) -> dict:
    """Неизвестный PR допускает наблюдение версии. Смена ветки обесценивает оба факта."""
    row = {"repo": repo, "default_branch": {"state": "unknown"}, "version": {"state": "unknown"},
           "policy": _declared_policy({}), "update_pr": {"state": "unknown"}, "production_runtime": "unknown", "production_restore": "unknown"}
    if not repo or parse_slug(repo) != repo or repo.count("/") != 1 or {".", ".."}.intersection(repo.split("/")):
        return {**row, "reason": "invalid_repository"}
    source = _Repository(GitHubClient(repo=repo))
    stage = "default_branch"
    try:
        identity = source.default_branch()
        repo_id, branch, head = identity
        stage = "version"
        version, policy = source.installation(head)
        try:
            pull = source.update_pr(repo_id, branch, head, version["value"])
        except _READ_ERRORS:
            pull = {"state": "unknown"}
        stage = "freshness"
        _require(source.default_branch() == identity, "changed")
    except _READ_ERRORS:
        return {**row, "reason": stage + "_unverified"}
    return {**row, "default_branch": {"state": "observed", "name": branch, "sha": head},
            "version": version, "policy": policy, "update_pr": pull}
