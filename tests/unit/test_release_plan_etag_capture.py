"""Сквозное условное чтение внутри capture с настоящим Git и локальным API fixture."""
import json
import subprocess

import pytest

from ai_ops_kit.devtools import release_plan as rp, release_plan_sources as src
from ai_ops_kit.integrations.github import GitHubClient
from test_release_plan_sources import source_case as _source_case_fixture


@pytest.fixture
def source_case(tmp_path):
    return _source_case_fixture.__wrapped__(tmp_path)


@pytest.mark.parametrize("mode", ["unchanged", "rerun", "403", "invalid-json", "stderr-403", "network"])
def test_capture_revalidates_real_client_workflow_pages(source_case, monkeypatch, mode):
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    from ai_ops_kit.devtools import release_plan_etags

    root, fixture = source_case
    client = GitHubClient(fixture.repo, transport="gh")
    monkeypatch.setenv("GH_TOKEN", "offline-fixture")
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.setattr(client, "closing_issue_numbers", fixture.closing_issue_numbers)
    monkeypatch.setattr(client, "read_page", fixture.read_page)
    baseline, repeats = set(), []
    actual = subprocess.run

    def run(cmd, **kwargs):
        if list(cmd[:2]) != ["gh", "api"]:
            return actual(cmd, **kwargs)
        assert "--include" in cmd
        endpoint = cmd[-1]
        parsed = urlsplit(endpoint)
        if parsed.path.endswith("/docs.yml/runs"):
            if mode == "invalid-json":
                return SimpleNamespace(returncode=0, stdout=b'HTTP/2.0 200 OK\nX-Test: 1\r\n\r\n{"private-input":', stderr=b"")
            if mode in ("stderr-403", "network"):
                stderr = b"gh: permission denied (HTTP 403)" if mode == "stderr-403" else b"dial tcp: private-host"
                return SimpleNamespace(returncode=1, stdout=b"", stderr=stderr)
        if endpoint in baseline:
            assert 'If-None-Match: "version-1"' in cmd
            repeats.append(endpoint)
            if mode == "unchanged":
                return SimpleNamespace(returncode=1, stdout=b"HTTP/2.0 304 Not Modified\nEtag: \"version-1\"\r\n\r\n",
                                       stderr=b"gh: HTTP 304\n")
            if mode == "403":
                return SimpleNamespace(returncode=1, stdout=b"HTTP/2.0 403 Forbidden\nX-Test: 1\r\n\r\n", stderr=b"")
        baseline.add(endpoint)
        page = fixture.read_page(parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()})
        if repeats:
            page["workflow_runs"][0]["run_attempt"] = 2
        return SimpleNamespace(returncode=0, stdout=b"HTTP/2.0 200 OK\nEtag: \"version-1\"\r\n\r\n" + json.dumps(page).encode(),
                               stderr=b"")
    monkeypatch.setattr(release_plan_etags.subprocess, "run", run)
    snap = src.capture(root, client)
    if mode in ("invalid-json", "stderr-403", "network"):
        code = "github_read_permission_denied" if mode == "stderr-403" else "github_read_failed"
        assert not snap["complete"] and not snap["unchanged"]
        assert snap["diagnostic"] == {"code": code, "pr": 10, "workflow": "docs.yml", "field": "workflow_runs"}
        assert "private-" not in json.dumps(snap)
        return
    assert len(baseline) == len(fixture.policy)
    if mode == "unchanged":
        assert len(repeats) == len(baseline)
        assert snap["complete"] and snap["unchanged"] and rp.build(root, snap)["composition_available"]
        assert any("/attempts/1/jobs" in path for path, _ in fixture.calls)
    else:
        assert len(repeats) == 1 and not snap["complete"]
        if mode == "rerun":
            assert snap["diagnostic"]["code"] == "ci_changed"
        else:
            assert snap["reason"] == "github_read_permission_denied"
