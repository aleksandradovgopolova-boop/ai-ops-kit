"""Условный запрос каждый раз доходит до сервера, прежние данные требуют его 304."""
import json
from types import SimpleNamespace

import pytest

from ai_ops_kit.devtools import release_plan_etags as etags
from ai_ops_kit.devtools import release_plan_sources as source
from ai_ops_kit.integrations.github import GitHubClient, GitHubError


SHA = "a" * 40
PATH = "repos/example/kit/actions/workflows/docs.yml/runs"
PARAMS = {"head_sha": SHA, "event": "pull_request", "page": 1, "per_page": 100}


def response(status=200, *, etag=None, attempt=1, rc=0, stderr=b"", extra=b""):
    body = (json.dumps({"total_count": 1, "workflow_runs": [
        {"id": 18, "run_attempt": attempt, "status": "completed", "conclusion": "success"}]}).encode()
        if status == 200 else b"")
    raw = f"HTTP/2.0 {status}\n".encode() + (f"Etag: {etag}\r\n".encode() if etag else b"")
    return SimpleNamespace(returncode=rc, stdout=raw + b"Content-Type: application/json\r\n" + extra + b"\r\n" + body, stderr=stderr)


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "offline-fixture")
    monkeypatch.delenv("GH_HOST", raising=False)
    client = GitHubClient("example/kit", transport="gh")
    calls, replies = [], []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return replies.pop(0)
    monkeypatch.setattr(etags.subprocess, "run", run)
    return client, calls, replies


def test_confirmed_304_reuses_exact_unmutated_representation(transport):
    client, calls, replies = transport
    replies.extend([response(etag='W/"one"'), response(304, etag='W/"one"', rc=1, stderr=b"gh: HTTP 304\n")])
    reader = etags.capture_reader(client)
    first = source._runs(reader, "docs.yml", SHA)
    signature = source._run_signature(first)
    first.clear()
    assert source._run_signature(source._runs(reader, "docs.yml", SHA)) == signature
    assert calls[1][-1] == calls[0][-1]
    assert not any(h.startswith("If-None-Match") for h in calls[0])
    assert 'If-None-Match: W/"one"' in calls[1]


def test_changed_200_is_seen_by_normal_run_signature(transport):
    client, calls, replies = transport
    replies.extend([response(etag='"one"'), response(etag='"two"', attempt=2), response(304)])
    reader = etags.capture_reader(client)
    before, after, confirmed = [source._run_signature(source._runs(reader, "docs.yml", SHA)) for _ in range(3)]
    assert source._changed_run(before, after) == {"run_id": 18, "attempt": 2}
    assert after == confirmed and 'If-None-Match: "two"' in calls[2]


@pytest.mark.parametrize("bad", [response(403, rc=1), response(500, rc=1), response(304, rc=7),
                                 response(304, etag='"other"'), response(304, rc=1, stderr=b"other error")])
def test_error_never_returns_old_page(transport, bad):
    client, calls, replies = transport
    replies.extend([response(etag='"one"'), bad, response(attempt=2)])
    reader = etags.capture_reader(client)
    reader.read_page(PATH, PARAMS)
    with pytest.raises(GitHubError):
        reader.read_page(PATH, PARAMS)
    assert reader.read_page(PATH, PARAMS)["workflow_runs"][0]["run_attempt"] == 2
    assert not any(h.startswith("If-None-Match") for h in calls[-1])


@pytest.mark.parametrize("extra,tag", [(b"", None), (b"Cache-Control: private, no-store\r\n", '"one"')])
def test_no_validator_or_no_store_forces_full_read(transport, extra, tag):
    client, calls, replies = transport
    replies.extend([response(etag=tag, extra=extra), response()])
    reader = etags.capture_reader(client)
    reader.read_page(PATH, PARAMS)
    reader.read_page(PATH, PARAMS)
    assert not any(h.startswith("If-None-Match") for h in calls[-1])


def test_validator_does_not_cross_page_sha_path_or_capture(transport):
    client, calls, replies = transport
    reader = etags.capture_reader(client)
    paths_and_readers = [(reader, PATH, PARAMS), (reader, PATH, dict(PARAMS, page=2)),
        (reader, PATH, dict(PARAMS, head_sha="b"*40)), (reader, PATH.replace("docs", "lint"), PARAMS),
        (etags.capture_reader(client), PATH, PARAMS)]
    replies.extend(response(etag='"one"') for _ in paths_and_readers)
    for scoped, path, params in paths_and_readers:
        scoped.read_page(path, params)
    assert all(not any(h.startswith("If-None-Match") for h in call) for call in calls)


def test_unconfirmed_304_and_foreign_path(transport):
    client, calls, replies = transport
    reader = etags.capture_reader(client)
    replies.append(response(304))
    with pytest.raises(GitHubError):
        reader.read_page(PATH, PARAMS)
    with pytest.raises(GitHubError, match="outside repository"):
        reader.read_page(PATH.replace("example/", "other/"), PARAMS)
    assert len(calls) == 1


def test_rest_transport_and_gh_without_runtime_token_keep_their_existing_path(transport, monkeypatch):
    client, calls, _ = transport
    rest = GitHubClient("example/kit", transport="rest")
    assert etags.capture_reader(rest) is rest
    monkeypatch.delenv("GH_TOKEN")
    assert etags.capture_reader(client) is client
    assert not calls


@pytest.mark.parametrize("limit,value", [("_MAX_BODY", 1), ("_MAX_TOTAL", 1), ("_MAX_PAGES", 0)])
def test_oversize_pages_still_reach_server_without_retaining_bytes(transport, monkeypatch, limit, value):
    client, calls, replies = transport
    monkeypatch.setattr(etags, limit, value)
    reader = etags.capture_reader(client)
    replies.extend([response(etag='"one"'), response(etag='"two"', attempt=2)])
    reader.read_page(PATH, PARAMS)
    assert reader.read_page(PATH, PARAMS)["workflow_runs"][0]["run_attempt"] == 2
    assert not reader.pages and reader.bytes_held == 0
    assert not any(h.startswith("If-None-Match") for h in calls[-1])


def test_interrupted_response_cannot_reuse_previous_page(transport, monkeypatch):
    client, _, replies = transport
    reader = etags.capture_reader(client)
    replies.append(response(etag='"one"'))
    reader.read_page(PATH, PARAMS)
    def interrupted(*args, **kwargs):
        raise etags.subprocess.TimeoutExpired("gh api", 5)
    monkeypatch.setattr(etags.subprocess, "run", interrupted)
    with pytest.raises(GitHubError):
        reader.read_page(PATH, PARAMS)
    assert reader.bytes_held == 0 and not reader.pages


def test_changed_credential_context_cannot_consume_authorized_304(transport, monkeypatch):
    client, calls, replies = transport
    reader = etags.capture_reader(client)
    replies.append(response(etag='"one"'))
    reader.read_page(PATH, PARAMS)
    monkeypatch.setenv("GH_TOKEN", "different-offline-fixture")
    with pytest.raises(GitHubError, match="context changed"):
        reader.read_page(PATH, PARAMS)
    assert len(calls) == 1


def test_changed_supplier_is_a_release_input():
    from pathlib import Path
    from ai_ops_kit.devtools import release_plan
    root = Path(__file__).resolve().parents[2]
    inputs = release_plan.input_digests(root)
    assert "ai_ops_kit/devtools/release_plan_etags.py" in inputs


def test_full_cache_does_not_hide_later_pages_or_evict_an_unrelated_validator(transport, monkeypatch):
    client, calls, replies = transport
    reader = etags.capture_reader(client)
    wire = response(etag='"etag"')
    byte_count = len(wire.stdout.split(b"\r\n\r\n")[1])
    monkeypatch.setattr(etags, "_MAX_TOTAL", byte_count)
    replies.extend([wire, wire, wire, response(304)])
    for page in (1, 2, 2, 1):
        reader.read_page(PATH, dict(PARAMS, page=page))
    assert reader.bytes_held == byte_count and len(reader.pages) == 1
    assert not any(h.startswith("If-None-Match") for h in calls[2])
    assert 'If-None-Match: "etag"' in calls[3]
