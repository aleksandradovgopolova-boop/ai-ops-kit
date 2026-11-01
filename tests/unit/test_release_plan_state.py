"""Переходы без дублей, недоказанная история и provenance последней публикации."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import release_plan as rp, release_plan_state as state
from ai_ops_kit.integrations.github import GitHubError

ROOT = Path(__file__).resolve().parents[2]
SHA = "1" * 40
PUBLISHER = {"run_id": 100, "attempt": 1, "checkout_sha": SHA, "branch": "main"}


def report():
    value = {"schema_version": 1, "kind": "kit-release-plan", "repository": "owner/kit",
             "cycle_id": "kit:4.12.0", "target_version": "4.12.0", "included_commits": [{"sha": SHA}],
             "composition_available": True, "implementation_evidence_complete": True,
             "release_ready": False, "blockers": ["release_bump_pending"], "deferred_issues": [],
             "source": {"sha": SHA}}
    value["semantic_fingerprint"] = rp.semantic_fingerprint(value)
    return value


class PublisherClient:
    repo = "owner/kit"

    def __init__(self, *, branch="main", sha=SHA, attempt=1, event="push", newer=False):
        self.branch, self.sha, self.attempt, self.event, self.newer = branch, sha, attempt, event, newer
        self.calls = []

    def read_page(self, path, params=None):
        self.calls.append(path)
        if path == "repos/owner/kit":
            return {"default_branch": "main"}
        if path.endswith("/runs"):
            row = {"id": 101 if self.newer else 100, "run_attempt": self.attempt,
                   "head_sha": self.sha, "head_branch": self.branch,
                   "event": self.event, "path": ".github/workflows/status-dashboard.yml"}
            return {"workflow_runs": [row], "total_count": 1}
        return {"total_count": 1, "jobs": [{"id": 1, "steps": [
            {"name": "Опубликовать на GitHub Pages", "status": "completed", "conclusion": "success"}]}]}


def test_same_facts_repeated_or_reordered_do_not_create_notice():
    base = report()
    prior = state.project(base, None, PUBLISHER)
    after = state.project(base, prior, {**PUBLISHER, "run_id": 101})
    assert after["transition"]["history"] == "verified"
    assert after["transition"]["changed"] is False
    assert after["transition"]["notice_id"] is None
    assert after["semantic_fingerprint"] == prior["semantic_fingerprint"]


def test_semantic_failure_gets_one_deterministic_transition_not_human_receipt():
    prior = state.project(report(), None, PUBLISHER)
    changed = report()
    changed["blockers"].append("implementation_ci_incomplete")
    changed["implementation_evidence_complete"] = False
    changed["semantic_fingerprint"] = rp.semantic_fingerprint(changed)
    first = state.project(changed, prior)
    second = state.project(changed, prior)
    assert first["transition"]["notice_id"] == second["transition"]["notice_id"]
    assert first["transition"]["changed"]
    assert first["transition"]["human_delivery"] == "unknown"
    assert not state.project(changed, first)["transition"]["changed"]


def test_missing_corrupt_or_untrusted_history_is_unknown_not_empty_success():
    projected = state.project(report(), None)
    assert projected["transition"] == {"history": "unknown", "changed": False,
                                         "notice_id": None, "human_delivery": "unknown"}
    assert projected["message"]["kind"] == "user-message"
    assert projected["message"]["status"] == "degraded"
    assert state.previous(PublisherClient(), read=lambda _: {}) is None


def test_previous_projection_needs_matching_latest_real_deploy():
    payload = state.project(report(), None, PUBLISHER)
    assert state.previous(PublisherClient(), read=lambda _: {"release_plan": payload}) == payload
    assert state.previous(PublisherClient(newer=True), read=lambda _: {"release_plan": payload}) is None


@pytest.mark.parametrize("change", ["digest", "semantic", "wrong_sha", "wrong_branch", "wrong_attempt", "pr_event"])
def test_wrong_provenance_cannot_become_a_verified_prior(change):
    payload = state.project(report(), None, PUBLISHER)
    kwargs = {}
    if change == "digest":
        payload["target_version"] = "9.0.0"
    elif change == "semantic":
        payload["semantic_fingerprint"] = "0" * 64
        payload["publisher"]["digest"] = state.payload_digest(payload)
    elif change == "wrong_sha":
        kwargs["sha"] = "2" * 40
    elif change == "wrong_branch":
        kwargs["branch"] = "untrusted"
        payload["publisher"]["branch"] = "untrusted"
    elif change == "wrong_attempt":
        kwargs["attempt"] = 2
    else:
        kwargs["event"] = "pull_request"
    assert state.previous(PublisherClient(**kwargs), read=lambda _: {"release_plan": payload}) is None


def test_permission_error_does_not_trigger_stronger_token_or_write():
    class Denied(PublisherClient):
        def read_page(self, *args, **kwargs):
            raise GitHubError("HTTP 403")
    payload = state.project(report(), None, PUBLISHER)
    assert state.previous(Denied(), read=lambda _: {"release_plan": payload}) is None


def test_projection_is_pure_and_never_touches_worktree_or_prior(tmp_path):
    before = report()
    prior = deepcopy(before)
    target = tmp_path / "owner.txt"
    target.write_text("owner")
    state.project(before, prior, PUBLISHER)
    assert before == prior and target.read_text() == "owner"
    assert list(tmp_path.iterdir()) == [target]


def test_canonical_digest_does_not_include_itself():
    value = state.project(report(), None, PUBLISHER)
    assert value["publisher"]["digest"] == state.payload_digest(value)
    value["message"]["summary"] = "altered"
    assert value["publisher"]["digest"] != state.payload_digest(value)


def test_pages_url_is_fixed_repo_origin_without_credentials_or_user_input_url():
    assert state.page_url("Owner/kit") == "https://owner.github.io/kit/data.json"
    assert state.page_url("Owner/owner.github.io") == "https://owner.github.io/data.json"
    with pytest.raises(ValueError):
        state.page_url("https://evil.invalid/data.json")
    with pytest.raises(ValueError):
        state._SamePage().redirect_request(type("Req", (), {"full_url": "https://owner.github.io/kit/data.json"})(),
                                          None, 302, "", {}, "https://evil.invalid")


def test_publisher_runs_trusted_checkout_serially_without_new_token_permissions():
    source = (ROOT / ".github/workflows/status-dashboard.yml").read_text()
    workflow = yaml.safe_load(source)
    assert workflow["permissions"] == {"contents": "read", "issues": "read", "actions": "read", "pages": "write", "id-token": "write"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["jobs"]["build-and-deploy"]["if"] == "${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    assert "pull_request_target" not in source
    steps = workflow["jobs"]["build-and-deploy"]["steps"]
    checkout = steps[0]
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    assert any("--release-plan" in s.get("run", "") for s in steps)
    verify = next(i for i, s in enumerate(steps) if "::test_live_projection_is_current_before_deploy" in s.get("run", ""))
    deploy = next(i for i, s in enumerate(steps) if s.get("id") == "deploy")
    summary = next(i for i, s in enumerate(steps) if "--release-summary" in s.get("run", ""))
    assert verify < deploy < summary
    assert steps[verify]["env"]["AI_OPS_RELEASE_PROJECTION_VERIFY"] == "1"
    assert steps[summary]["env"]["AI_OPS_RELEASE_DEPLOY_CONFIRMED"] == "${{ steps.deploy.outcome }}"


def test_dashboard_snapshot_is_the_same_object_and_script_safe(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_dashboard", ROOT / "dashboard/build_data.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    html = tmp_path / "index.html"
    html.write_text("/* SNAPSHOT:BEGIN */\nold\n/* SNAPSHOT:END */")
    value = {"release_plan": {"message": {"summary": "</script><script>bad</script>"}}}
    assert builder.sync_snapshot(html, value) == 1
    raw = html.read_text().split("const SNAPSHOT = ")[1].split(";\n")[0]
    assert "</script>" not in raw and json.loads(raw) == value


def test_summary_requires_actual_deploy_and_retry_replaces_one_result(tmp_path, monkeypatch):
    from ai_ops_kit.devtools import release_plan_sources as src
    prior = state.project(report(), None, PUBLISHER)
    current = report()
    current["blockers"] = []
    current["release_ready"] = True
    current["semantic_fingerprint"] = rp.semantic_fingerprint(current)
    payload = state.project(current, prior, PUBLISHER)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard/data.json").write_text(json.dumps({"release_plan": payload}))
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("AI_OPS_RELEASE_DEPLOY_CONFIRMED", "failure")
    with pytest.raises(src.SnapshotError):
        src.emit_summary(tmp_path)
    assert not summary.exists()
    monkeypatch.setenv("AI_OPS_RELEASE_DEPLOY_CONFIRMED", "success")
    assert src.emit_summary(tmp_path) == 0
    first = summary.read_bytes()
    assert src.emit_summary(tmp_path) == 0 and summary.read_bytes() == first
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(src.SnapshotError):
        src.emit_summary(tmp_path)


def test_known_idle_projects_a_successful_empty_result_without_release_readiness():
    current = report()
    current.update(cycle_state="idle", target_version=None, composition_available=True,
                   included_commits=[], blockers=[], release_ready=False)
    current["semantic_fingerprint"] = rp.semantic_fingerprint(current)
    result = state.project(current, None)
    assert result["message"]["status"] == "ok"
    assert "новых изменений" in result["message"]["summary"]
    assert not result["release_ready"] and result["transition"]["human_delivery"] == "unknown"
