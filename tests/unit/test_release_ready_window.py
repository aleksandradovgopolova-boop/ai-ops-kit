from copy import deepcopy
import json
import os
import subprocess

import pytest
import yaml

from ai_ops_kit.devtools import release_ready_window as window
from pathlib import Path

pytestmark = pytest.mark.unit
HEAD = "a" * 40
START = "2026-11-16T14:16:29Z"


class Client:
    repo = "demo/project"

    def __init__(self):
        self.run = {"id": 7, "run_attempt": 1, "head_sha": HEAD, "created_at": START,
                    "status": "completed", "conclusion": "success"}

    def read_page(self, path):
        assert path == "repos/demo/project/actions/runs/7"
        return deepcopy(self.run)


@pytest.fixture
def report():
    return {"source": {"sha": HEAD}, "target_version": "4.15.0", "published": {"version": "4.14.0"},
            "release_ready": True, "final_release_checks_observed": True,
            "publisher": {"run_id": 7, "attempt": 1, "checkout_sha": HEAD, "digest": "f" * 64}}


def observe(report, client=None, trusted=True):
    return window.receipt(client or Client(), HEAD, "4.15.0", START,
                          read=lambda repo: {"release_plan": report},
                          verify=lambda client, read: read(client.repo)["release_plan"] if trusted else None)


def test_receipt_binds_visible_readiness_without_mutating_input(report):
    original = deepcopy(report)
    out = observe(report)
    assert out == {"version": "4.15.0", "source_sha": HEAD, "pages_run_id": 7, "attempt": 1,
                   "digest": "f" * 64, "release_ready": True}
    assert report == original


@pytest.mark.parametrize(("key", "value"), [
    ("release_ready", False), ("release_ready", 1), ("final_release_checks_observed", False),
    ("source", {"sha": "b" * 40}), ("target_version", "4.16.0"), ("published", {"version": "4.15.0"})])
def test_successful_deploy_alone_never_confirms_ready(report, key, value):
    report[key] = value
    assert observe(report) is None


@pytest.mark.parametrize(("key", "value"), [
    ("created_at", "2026-11-16T14:16:28Z"), ("status", "in_progress"),
    ("conclusion", "cancelled"), ("run_attempt", 2), ("head_sha", "b" * 40)])
def test_stale_unfinished_or_replaced_deployment_fails(report, key, value):
    client = Client()
    client.run[key] = value
    assert observe(report, client) is None


def test_unverified_publisher_fails(report):
    assert observe(report, trusted=False) is None


def test_release_uses_receipt_before_reporting_ready():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
    step = next(s for s in yaml.safe_load(path.read_text())["jobs"]["release"]["steps"] if s.get("id") == "ready_window")
    assert step["continue-on-error"] is True
    assert step["env"]["VERSION"] == "${{ needs.check.outputs.version }}"
    assert step["run"].index("ai_ops_kit.devtools.release_ready_window") < step["run"].index('echo "Пульт опубликован')
    assert "gh run list" not in step["run"]
    assert "не удалось подтвердить на пульте готовность версии $VERSION для $GITHUB_SHA" in step["run"]


@pytest.mark.parametrize("observed", [True, False], ids=["authenticated", "refused"])
def test_only_confirmed_ready_page_exports_receipt(tmp_path, observed):
    path = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["release"]["steps"]
    window = next(step for step in steps if step.get("id") == "ready_window")
    output = tmp_path / "step-output"
    output.touch()
    receipt = json.dumps({"version": "4.16.0", "source_sha": HEAD, "pages_run_id": 7,
                          "attempt": 1, "digest": "b" * 64, "release_ready": True})
    # Локальные подстановки исключают GitHub и переводят часы к концу окна после одной пробы.
    fixture = """
gh() { [[ "$1 $2 $3" == "workflow run status-dashboard.yml" ]]; }
sleep() { SECONDS=895; }
timeout() { printf '%s\\n' "$SAMPLE"; return "$VERIFY_RC"; }
"""
    env = dict(os.environ, GITHUB_REPOSITORY="demo/project", GITHUB_SHA=HEAD, VERSION="4.16.0",
               GITHUB_OUTPUT=str(output), RUNNER_TEMP=str(tmp_path), SAMPLE=receipt,
               VERIFY_RC="0" if observed else "1")
    result = subprocess.run(["bash", "-e", "-c", fixture + window["run"]], env=env,
                            capture_output=True, text=True, timeout=5, check=True)
    archived = tmp_path / "release-ready.json"
    if observed:
        assert archived.read_bytes() == (receipt + "\n").encode()
        assert output.read_text() == "observed=true\n" and receipt in result.stdout
    else:
        assert not archived.exists() and output.read_text() == ""
        assert receipt not in result.stdout


def test_ready_receipt_upload_is_scoped_to_observed_attempt_after_tag():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["release"]["steps"]
    upload = next(s for s in steps if s.get("with", {}).get("path") == "${{ runner.temp }}/release-ready.json")
    tag = next(s for s in steps if "gh release create" in s.get("run", ""))
    assert steps.index(tag) < steps.index(upload)
    assert upload["if"] == "${{ !cancelled() && steps.ready_window.outputs.observed == 'true' }}"
    assert upload["continue-on-error"] is True
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["name"] == "release-ready-${{ github.run_id }}-${{ github.run_attempt }}"
