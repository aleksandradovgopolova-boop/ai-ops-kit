"""Поставка: реальные lock/process и наблюдения; внешняя платформа — fixture adapter."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.gates.deploy_readiness import confirmation
from ai_ops_kit.delivery import record_delivery as rd
from ai_ops_kit.gates import deploy_readiness
from ai_ops_kit.shared import lifecycle_store as vr

pytestmark = pytest.mark.unit
FIXTURE = Path(__file__).parents[1] / "fixtures/delivery_reuse/verified_release.json"


@pytest.fixture
def record():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.fixture
def delivery(repo, record):
    calls = []
    def deploy():
        calls.append("deploy")
        (repo / ".ai/runtime/published").write_text(record["expected"]["version"])
        return 0
    kwargs = {"owner": record["owner"], "expected": record["expected"],
              "recovery": record["recovery"], "checks": lambda: copy.deepcopy(record["checks"]),
              "preflight": lambda: [{"surface": "agent", "status": "PASS", "code": 200}],
              "deploy": deploy, "observe_runtime": lambda: copy.deepcopy(record["runtime"]),
              "observe_public": lambda: copy.deepcopy(record["public"])}
    return kwargs, calls


def test_valid_fixture_is_confirmed(record):
    assert confirmation(record)[0] == "PASS"


@pytest.mark.parametrize("field", ["version", "sha", "artifact_digest", "environment"])
def test_public_identity_mismatch_is_fail_even_exit_zero(record, field):
    record["public"][field] = "wrong"
    assert record["deploy_exit_code"] == 0
    assert confirmation(record)[0] == "FAIL"


@pytest.mark.parametrize("status", ["FAIL", "SKIP", "BLOCKED", "NOT_RUN"])
def test_mandatory_scenario_non_pass_excludes_success(record, status):
    record["public"]["status"] = status
    assert confirmation(record)[0] == ("FAIL" if status == "FAIL" else "BLOCKED")


@pytest.mark.parametrize("field", ["checks", "runtime", "public", "recovery", "owner", "observed_at", "expected"])
def test_missing_release_proof_is_blocked(record, field):
    del record[field]
    assert confirmation(record)[0] == "BLOCKED"


def test_empty_deploy_json_is_not_verified(repo):
    (repo / "deploy.sh").write_text("exit 0")
    (repo / "rollback.sh").write_text("exit 0")
    path = repo / ".ai/runtime/deploy/old.json"
    vr.atomic_json(path, {"environment": "production"})
    result = deploy_readiness.assess(repo)
    assert result["deploy_maturity"] == "runnable"
    assert result["deploy_records"] and not result["confirmed_deploy_records"]


def test_deploy_occurs_once_and_records_full_identity(repo, delivery):
    kwargs, calls = delivery
    first = rd.deliver(repo, **kwargs)
    assert (repo / ".ai/runtime/published").read_text() == first["expected"]["version"]
    assert first["status"] == "PASS" and len(calls) == 1
    second = rd.deliver(repo, **kwargs)
    assert second["status"] == "PASS" and second["action"] == "reconcile"
    assert len(calls) == 1
    saved = json.loads(Path(second["path"]).read_text())
    assert saved["owner"] and saved["recovery"]["automatic_rollback"] is False
    assert saved["runtime"] == saved["public"] | {"source": "runtime:fixture"}


def test_exit_zero_with_public_failure_is_recorded_as_failure(repo, delivery):
    kwargs, calls = delivery
    kwargs["observe_public"] = lambda: {"status": "FAIL", "source": "public:scenario"}
    result = rd.deliver(repo, **kwargs)
    assert len(calls) == 1 and result["deploy_exit_code"] == 0
    assert result["status"] == "FAIL"
    assert json.loads(Path(result["path"]).read_text())["status"] == "FAIL"


def test_unknown_outcome_reconciles_before_any_retry(repo, delivery):
    kwargs, calls = delivery
    def timeout_after_side_effect():
        calls.append("published-before-timeout")
        (repo / ".ai/runtime/published").write_text("observed")
        raise TimeoutError("outcome unknown")
    kwargs["deploy"] = timeout_after_side_effect
    first = rd.deliver(repo, **kwargs)
    assert (repo / ".ai/runtime/published").exists() and first["status"] == "BLOCKED"
    second = rd.deliver(repo, **kwargs)
    assert second["action"] == "reconcile" and second["status"] == "PASS"
    assert calls == ["published-before-timeout"]


def test_other_owner_cannot_take_pending_release(repo, delivery):
    kwargs, calls = delivery
    kwargs["observe_public"] = lambda: {"status": "BLOCKED"}
    rd.deliver(repo, **kwargs)
    with pytest.raises(rd.ReleaseBlocked, match="владельцу"):
        rd.deliver(repo, **{**kwargs, "owner": "other-owner"})
    assert len(calls) == 1


def test_failed_early_preflight_does_not_publish(repo, delivery):
    kwargs, calls = delivery
    kwargs["preflight"] = lambda: [{"surface": "connector", "status": "BLOCKED", "code": 404}]
    with pytest.raises(rd.ReleaseBlocked, match="поверхности"):
        rd.deliver(repo, **kwargs)
    assert calls == [] and not (repo / ".ai/runtime/published").exists()


def test_missing_check_evidence_does_not_publish(repo, delivery):
    kwargs, calls = delivery
    kwargs["checks"] = lambda: [{"name": "static", "status": "PASS"}]
    with pytest.raises(rd.ReleaseBlocked, match="PASS"):
        rd.deliver(repo, **kwargs)
    assert calls == []


def test_access_surfaces_are_independent_and_404_is_not_diagnosed():
    operations = [{"surface": s, "operation": "read-release"} for s in
                  ("connector", "user_terminal", "agent")]
    def probe(surface, operation):
        return {"status": "BLOCKED" if surface == "connector" else "PASS",
                "code": 404 if surface == "connector" else 200,
                "error": "token=do-not-store", "diagnosis": "organisation settings"}
    result = rd.access_preflight(operations, probe)
    assert result[0]["status"] == "BLOCKED" and result[1]["status"] == "PASS"
    assert result[0]["code"] == 404
    assert "diagnosis" not in json.dumps(result) and "do-not-store" not in json.dumps(result)


def _holder(repo):
    script = ("import sys,time; from ai_ops_kit.delivery.record_delivery import environment_lock; "
              "\nwith environment_lock(sys.argv[1], 'fixture'):\n print('locked',flush=True); time.sleep(30)")
    proc = subprocess.Popen([sys.executable, "-u", "-c", script, str(repo)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_concurrent_deploy_cannot_remove_active_foreign_lock(repo, delivery):
    proc = _holder(repo)
    try:
        lock = next((repo / ".ai/runtime/deploy-locks").glob("*.lock"))
        inode = lock.stat().st_ino
        for _ in range(2):
            with pytest.raises(rd.ReleaseBlocked, match="другой deploy"):
                rd.deliver(repo, **delivery[0])
        assert lock.exists() and lock.stat().st_ino == inode
        assert delivery[1] == []
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_lock_recovers_after_holder_process_is_killed(repo):
    proc = _holder(repo)
    lock = next((repo / ".ai/runtime/deploy-locks").glob("*.lock"))
    inode = lock.stat().st_ino
    proc.kill()
    proc.wait(timeout=5)
    with rd.environment_lock(repo, "fixture"):
        assert lock.stat().st_ino == inode  # Восстановление без unlink/TTL-чужого-lock.


def test_worktrees_share_environment_lock(repo, delivery):
    (repo / "source").write_text("v1")
    subprocess.run(["git", "-C", str(repo), "add", "source"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=fixture", "-c", "user.email=f@f",
                    "commit", "-qm", "fixture"], check=True)
    other = repo.parent / (repo.name + "-worktree")
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(other)],
                   check=True, capture_output=True)
    try:
        with rd.environment_lock(repo, "fixture"):
            with pytest.raises(rd.ReleaseBlocked):
                with rd.environment_lock(other, "fixture"):
                    pytest.fail("второй worktree получил действующий чужой lock")
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(other)], check=True)


def test_docs_ready_event_does_not_repeat_already_required_build():
    import yaml
    root = Path(__file__).parents[2]
    # BaseLoader сохраняет ключ on без YAML 1.1 преобразования в True.
    docs = yaml.load((root / ".github/workflows/docs.yml").read_text(), Loader=yaml.BaseLoader)
    quality = yaml.load((root / ".github/workflows/package-quality.yml").read_text(), Loader=yaml.BaseLoader)
    assert "ready_for_review" not in docs["on"]["pull_request"]["types"]
    assert "opened" in docs["on"]["pull_request"]["types"]
    assert "ready_for_review" in quality["on"]["pull_request"]["types"]


@pytest.mark.parametrize("damage", ["{", "[]", "{}"])
def test_corrupted_previous_intent_does_not_repeat_deploy(repo, delivery, damage):
    kwargs, calls = delivery
    result = rd.deliver(repo, **kwargs)
    Path(result["path"]).write_text(damage)
    with pytest.raises(rd.ReleaseBlocked, match="повреждена"):
        rd.deliver(repo, **kwargs)
    assert len(calls) == 1


def test_credential_sources_are_not_persisted(repo, delivery):
    kwargs, calls = delivery
    public = kwargs["observe_public"]()
    public["source"] = "https://private-token@example.test/status?key=secret-value#token"
    kwargs["observe_public"] = lambda: public
    checks = kwargs["checks"]()
    checks[0]["source"] = "https://user:private-password@example.test/ci?secret=private-query"
    checks[0]["headers"] = {"Authorization": "private-raw-header"}
    checks[0]["output_tail"] = "private-raw-output"
    kwargs["checks"] = lambda: checks
    result = rd.deliver(repo, **kwargs)
    text = Path(result["path"]).read_text()
    assert result["status"] == "PASS"
    assert "private-" not in text and "secret-value" not in text
    assert "https://example.test/status" in text


def test_required_ci_cannot_be_satisfied_by_local_pass(repo, delivery):
    path = repo / "quality/required-contexts.yaml"
    path.parent.mkdir()
    path.write_text("contexts: [required-ci]\n")
    kwargs, calls = delivery
    with pytest.raises(rd.ReleaseBlocked, match="CI"):
        rd.deliver(repo, **kwargs)
    assert calls == []
    checks = kwargs["checks"]()
    checks[0].update(kind="ci", sha=kwargs["expected"]["sha"])
    kwargs["checks"] = lambda: checks
    assert rd.deliver(repo, **kwargs)["status"] == "PASS"


@pytest.mark.parametrize("status", ["SKIP", "NOT_RUN", "BLOCKED"])
def test_required_ci_skip_is_not_success(record, status):
    record["required_ci"] = ["required-ci"]
    record["checks"][0].update(kind="ci", sha=record["expected"]["sha"], status=status)
    assert confirmation(record)[0] == "BLOCKED"
