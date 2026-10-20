"""Пульт показывает фактические результаты, не превращая пропуски в успех."""
import datetime as dt
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
SLUG = "owner/kit"


def load():
    spec = importlib.util.spec_from_file_location("dashboard_evidence_test", KIT / "dashboard/build_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    mod = load()
    monkeypatch.setattr(mod, "repo_slug", lambda root: {"owner": "owner", "name": "kit"})
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, SHA))
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/premerge-checks.json").write_text(json.dumps({
        "package-quality.yml": ["lint", "security-scan"], "docs.yml": ["build"]}))
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/package-quality.yml").write_text(
        "jobs:\n  lint: {}\n  security-scan:\n    if: github.event_name == 'pull_request'\n")
    for name, job in (("nightly-quality.yml", "heavy-gates"), ("nightly-coverage.yml", "coverage")):
        (tmp_path / f".github/workflows/{name}").write_text(f"jobs:\n  {job}: {{}}\n")
    names = [("package-quality.yml", "lint"), ("docs.yml", "build"),
             ("nightly-quality.yml", "heavy-gates"), ("nightly-coverage.yml", "coverage")]
    runs, jobs = [], {}
    for i, (workflow, name) in enumerate(names, 1):
        runs.append({"id": i, "run_attempt": 2, "path": f".github/workflows/{workflow}",
                     "head_sha": SHA, "head_branch": "main", "event": "push",
                     "repository": {"full_name": SLUG}, "status": "completed", "conclusion": "success",
                     "html_url": f"https://github.com/{SLUG}/actions/runs/{i}"})
        jobs[i] = [{"name": name, "head_sha": SHA, "run_id": i, "run_attempt": 2,
                    "status": "completed", "conclusion": "success"}]
    def api(root, slug, path, collection=None):
        assert slug == SLUG
        if path.startswith("releases"):
            return [{"draft": False, "prerelease": False, "tag_name": "v1.2.3",
                     "published_at": "2026-10-19T00:00:00Z", "html_url": "https://github.com/owner/kit/releases/tag/v1.2.3"}]
        if path.startswith("actions/runs?"):
            assert f"head_sha={SHA}" in path
            return runs
        run_id = int(path.split("/")[2])
        assert "/attempts/2/jobs" in path
        return jobs[run_id]
    monkeypatch.setattr(mod, "_github", api)
    return mod, tmp_path, runs, jobs


def test_complete_exact_head_and_attempt_are_success(evidence):
    mod, root, _, _ = evidence
    result = mod.delivery_evidence(root)
    assert result["tech"]["state"] == "green"
    assert result["tech"]["passed"] == result["tech"]["total"] == 4
    assert result["tech"]["head"] == SHA
    assert len(result["tech"]["sources"]) == 4
    assert result["release"]["tag"] == "v1.2.3"


@pytest.mark.parametrize("change", ["old_head", "old_attempt", "missing", "duplicate", "skipped", "failure", "running"])
def test_incomplete_or_non_success_cannot_be_green(evidence, change):
    mod, root, _, jobs = evidence
    if change == "old_head":
        jobs[1][0]["head_sha"] = "b" * 40
    elif change == "old_attempt":
        jobs[1][0]["run_attempt"] = 1
    elif change == "missing":
        jobs[1] = []
    elif change == "duplicate":
        jobs[1] *= 2
    elif change == "running":
        jobs[1][0]["status"] = "in_progress"
    else:
        jobs[1][0]["conclusion"] = change
    assert mod.delivery_evidence(root)["tech"]["state"] != "green"


def test_latest_attempt_failure_overrides_earlier_success(evidence):
    mod, root, runs, jobs = evidence
    runs.append(dict(runs[0], run_attempt=1, conclusion="success"))
    jobs[1][0]["conclusion"] = "failure"
    assert mod.delivery_evidence(root)["tech"]["state"] == "red"


def test_api_error_does_not_erase_independent_release(evidence, monkeypatch):
    mod, root, _, _ = evidence
    api = mod._github
    def fail(root, slug, path, collection=None):
        if path.startswith("actions"):
            raise subprocess.TimeoutExpired("gh", 45)
        return api(root, slug, path, collection)
    monkeypatch.setattr(mod, "_github", fail)
    result = mod.delivery_evidence(root)
    assert result["tech"]["state"] == "unknown"
    assert result["release"]["tag"] == "v1.2.3"


def test_gh_pagination_and_incomplete_page_rejected(tmp_path, monkeypatch):
    mod = load()
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '[{"total_count":2,"jobs":[{"name":"one"}]}]')
    monkeypatch.setattr(mod.subprocess, "run", run)
    with pytest.raises(ValueError, match="incomplete"):
        mod._github(tmp_path, SLUG, "actions/runs/1/jobs", "jobs")
    assert "--paginate" in calls[0] and "--slurp" in calls[0]


def test_expired_window_needs_followup_not_zero_defects():
    result = load().guardrail_windows([{"metrics": {"rework_rate": {
        "status": "observation_window_open", "opened_at": "2026-09-14T13:00:00Z", "window_days": 7}}}],
        now=dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc))
    assert result == {"pending": 1, "expired": 1, "label": "итог не снят"}


def test_actual_readout_and_written_snapshot_keep_cohorts_separate(tmp_path):
    mod = load()
    field = mod.field_readout(KIT)
    assert field["repositories"] == 3 and field["people"] == 1
    assert {r["repo"] for r in field["rows"]} == {"Garden", "Personal Cosmic Book", "dashboard-kit"}
    observations = mod.metric_observations(KIT)
    assert observations["aggregate"]["n"] == 4
    page = tmp_path / "index.html"
    page.write_text("/* SNAPSHOT:BEGIN */\nold\n/* SNAPSHOT:END */")
    assert mod.sync_snapshot(page, {"field": field, "observations": observations}) == 1
    written = page.read_text()
    assert '"repositories": 3' in written and '"n": 4' in written
    assert "итог не снят" in written
