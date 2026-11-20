from copy import deepcopy

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
