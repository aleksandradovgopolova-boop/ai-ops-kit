"""Реальные controller/review requests; fixture reviewer не является живой квалификацией."""
import json
from pathlib import Path

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_completion as agents
from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session_completion import project as _project_fixture, start, reviewer_receipts


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


def pending_review(project, monkeypatch, capsys):
    task, args = start(project, monkeypatch, "codex", "research")
    capsys.readouterr()
    assert cli.main(["finalize", *args]) == 1
    output = json.loads(capsys.readouterr().out)
    return task, args, output


@pytest.fixture
def pending_specialist(project, monkeypatch):
    def absent(_scope):
        raise FileNotFoundError("no host evidence")
    monkeypatch.setattr(agents.review_verdict, "load_model_receipt", absent)
    start(project, monkeypatch, "codex", "research", ai_component=True)
    return agents.finalize(project, "codex", "complete", {})


def test_saved_model_job_keeps_ordinary_jobs_actionable(project, pending_specialist):
    report = project / pending_specialist["verification"]["report"]
    saved = json.loads(report.read_bytes())["agent_handoff"]
    assert saved["next_action"] == "collect_existing_model_evidence_or_human_review"
    assert "receipt_status" not in saved["model_jobs"][0]
    action = agents.response(project, pending_specialist)["host_actions"]
    assert action["jobs"] == saved["jobs"] and any(j["gate"] == "acceptance" for j in action["jobs"])
    assert action["status"] == "awaiting_dispatch" and action["next_action"] == "dispatch_review_jobs"
    job, = action["model_jobs"]
    assert (job["status"], job["receipt_status"], job["verdict_present"]) == ("awaiting_external_evidence", "missing", False)
    assert job["owner"] == "trusted-host-operator" and action["human_jobs"] == saved["human_jobs"]
    assert json.loads(report.read_bytes())["agent_handoff"] == saved


def test_unchanged_waiting_finalize_preserves_attempt_and_files(project, pending_specialist, monkeypatch):
    folder = sessions.session_dir(project, "codex", "complete")
    def snapshot():
        return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    before = snapshot()
    monkeypatch.setattr(sessions, "run_process", lambda *a, **kw: pytest.fail("second worker started"))
    result = agents.finalize(project, "codex", "complete", {})
    assert result["verification"] == pending_specialist["verification"] and result["status"] == "running"
    assert result.get("verification_history") == pending_specialist.get("verification_history")
    assert snapshot() == before


def test_new_ordinary_digest_triggers_full_check_while_host_is_missing(project, pending_specialist):
    result = agents.finalize(project, "codex", "complete", {"acceptance": "0" * 64})
    assert result["verification"]["attempt"] != pending_specialist["verification"]["attempt"]
    assert result["status"] == "running" and not result["execution"].get("verification_ready")


@pytest.mark.parametrize("gate", ["acceptance", "ai_red_team"])
def test_digest_delivered_before_rejected_file_wakes_once_per_verified_change(project, pending_specialist, gate):
    action = agents.response(project, pending_specialist)["host_actions"]
    job = next(j for j in action["jobs"] + action["human_jobs"] if j["gate"] == gate)
    path = project / job["verdict"]
    # Совпадение байтов запускает проверку, а неполный JSON остаётся отклонённым.
    new_bytes = b'{"kind":"incomplete-local-observation"}'
    digests = {gate: sessions.digest(new_bytes)}
    def finish():
        return agents.finalize(project, "codex", "complete", digests)
    first = finish()
    assert not path.exists() and finish()["verification"] == first["verification"]
    path.write_bytes(b"older bytes")
    assert finish()["verification"] == first["verification"]
    path.write_bytes(new_bytes)
    checked = finish()
    assert checked["verification"]["attempt"] != first["verification"]["attempt"]
    assert checked["status"] == "running" and finish()["verification"] == checked["verification"]
    assert path.read_bytes() == new_bytes


def test_delivered_ordinary_verdict_advances_other_jobs_while_specialist_waits(project, pending_specialist):
    _, receipts = reviewer_receipts(project, pending_specialist, "codex", skip={"ai_red_team"})
    job = next(j for j in agents.response(project, pending_specialist)["host_actions"]["jobs"] if j["gate"] == "acceptance")
    path = project / job["verdict"]
    payload = path.read_bytes()
    path.unlink()
    digest = {"acceptance": receipts["acceptance"]}
    first = agents.finalize(project, "codex", "complete", digest)
    assert agents.finalize(project, "codex", "complete", digest)["verification"] == first["verification"]
    path.write_bytes(payload)
    resumed = agents.finalize(project, "codex", "complete", digest)
    action = agents.response(project, resumed)["host_actions"]
    assert "acceptance" not in [j["gate"] for j in action["jobs"]]
    assert action["model_jobs"] and resumed["status"] == "running"


def test_retry_probe_leaves_large_and_nonregular_verdicts_to_their_native_limits(tmp_path):
    resume = agents.resume_checks
    path = tmp_path / "local.json"
    path.mkdir()
    assert resume._candidate(tmp_path, path, "0" * 64, True) is False
    path.rmdir()
    path.write_bytes(b" " * 262145)
    assert resume._candidate(tmp_path, path, "0" * 64, True) is False
    assert resume._candidate(tmp_path, path, "0" * 64, False) is None


def test_specialist_only_wait_names_external_owner_even_with_local_verdict(project, pending_specialist):
    saved = json.loads((project / pending_specialist["verification"]["report"]).read_text())["agent_handoff"]
    job, = saved["model_jobs"]
    action = agents.review_jobs(project, pending_specialist, saved["scope"], [project / job["request"]])
    path = project / job["verdict"]
    path.write_bytes(b"unverified qualification marker")
    waiting = agents.resume_checks.specialist_route(project, action)
    assert waiting["jobs"] == [] and waiting["next_action"] == "await_external_evidence"
    assert waiting["model_jobs"][0]["verdict_present"] and waiting["model_jobs"][0]["receipt_status"] == "missing"
    assert waiting["model_jobs"][0]["owner"] == "trusted-host-operator"
    assert path.read_bytes() == b"unverified qualification marker"


def test_new_revision_restarts_verification_when_host_is_missing(project, pending_specialist):
    (project / "followup.md").write_text("Updated research observation.\n")
    sessions.git(project, "add", "followup.md")
    sessions.git(project, "commit", "-qm", "update observation")
    result = agents.finalize(project, "codex", "complete", {})
    assert result["verification"]["attempt"] != pending_specialist["verification"]["attempt"]
    assert result["verification"]["binding"]["head"] == sessions.git(project, "rev-parse", "HEAD")


def test_changed_specialist_request_cannot_reuse_wait(project, pending_specialist):
    original = agents.response(project, pending_specialist)["host_actions"]["model_jobs"][0]
    path = project / original["request"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="запрос агенту изменён"):
        agents.response(project, pending_specialist)
    result = agents.finalize(project, "codex", "complete", {})
    assert result["verification"]["attempt"] != pending_specialist["verification"]["attempt"]
    assert "запрос агенту изменён" in result["verification"]["recheck_reason"]
    assert result["status"] == "running"


def test_native_job_reaches_existing_acceptance_without_nested_provider(project, monkeypatch, capsys):
    from ai_ops_kit.providers import codex_native
    task, args, output = pending_review(project, monkeypatch, capsys)
    handoff = output["host_actions"]
    assert handoff["status"] == "awaiting_dispatch" and handoff["jobs"]
    job = next(j for j in handoff["jobs"] if j["gate"] == "acceptance")
    request = project / job["request"]
    assert request.is_file() and sessions.digest(request.read_bytes()) == job["request_sha256"]
    assert job["context"] == "fresh" and job["review_mode"] == "read-only"
    assert job["status"] == "awaiting_dispatch" and not (project / job["verdict"]).exists()
    assert job["result_contract"].endswith("ai_ops_kit/checks/acceptance_result.py")
    assert job["contract_sha256"] == sessions.digest(Path(job["result_contract"]).read_bytes())
    assert "kind=acceptance-result" in job["prompt"] and "met/unmet/undetermined" in job["prompt"]
    evidence = next(j for j in handoff["jobs"] if j["gate"] == "evidence")
    assert evidence["result_contract"].endswith("schemas/reviewer-result.schema.json")
    assert "kind=reviewer-result" in evidence["prompt"]
    assert str(request) in job["prompt"] and task["binding"]["head"] in job["prompt"]
    assert handoff["resume"]["digest_source"] == "independent-agent-result"
    def unexpected_provider(_root):
        pytest.fail("host review must not start nested Codex")
    monkeypatch.setattr(codex_native, "readiness", unexpected_provider)
    _, digests = reviewer_receipts(project, task, "codex")
    assert (project / job["verdict"]).is_file()
    assert cli.main([*handoff["resume"]["argv"][3:], "--review-digests", json.dumps(digests)]) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["status"] == "accepted" and "host_actions" not in accepted
    assert (project / ".ai/runtime/check-ran").read_text() == "real check"
    assert sessions.verify(project, "codex", "complete")["accepted"]


def test_resume_reuses_same_jobs_without_writing_or_claiming_dispatch(project, monkeypatch, capsys):
    _, args, output = pending_review(project, monkeypatch, capsys)
    state = sessions.load(project, "codex", "complete")
    before = {p: p.read_bytes() for p in (project / ".ai/runtime").rglob("*") if p.is_file()}
    assert cli.main(["run", *args]) == 1
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["host_actions"] == output["host_actions"]
    assert sessions.load(project, "codex", "complete") == state
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("damage", ["revision", "artifact", "input"])
def test_changed_inputs_do_not_dispatch_old_review(project, monkeypatch, capsys, damage):
    _, args, output = pending_review(project, monkeypatch, capsys)
    task = sessions.load(project, "codex", "complete")
    if damage == "revision":
        (project / "new-result.txt").write_text("changed")
        sessions.git(project, "add", "new-result.txt")
        sessions.git(project, "commit", "-qm", "changed result")
        assert sessions.git(project, "rev-parse", "HEAD") != output["host_actions"]["scope"]["reviewed_revision"]
    elif damage == "artifact":
        (project / "features" / ("session-" + task["request_id"]) / "new-review-artifact.md").write_text("changed")
        assert (project / "features" / ("session-" + task["request_id"]) / "new-review-artifact.md").is_file()
    else:
        task["input_events"] = ["new-input"]
        assert task["input_events"]
    result = agents.response(project, task)
    assert result["host_actions"]["status"] == "refresh_review"
    assert result["host_actions"]["jobs"] == []
    assert not sessions.verify(project, "codex", "complete")["accepted"]


@pytest.mark.parametrize("target", ["request", "report"])
def test_tampered_handoff_is_rejected(project, monkeypatch, capsys, target):
    _, _, output = pending_review(project, monkeypatch, capsys)
    task = sessions.load(project, "codex", "complete")
    path = project / (output["host_actions"]["jobs"][0]["request"] if target == "request" else task["verification"]["report"])
    old = path.read_bytes()
    path.write_bytes(old + b" ")
    assert path.read_bytes() != old
    with pytest.raises(ValueError, match="изменён"):
        agents.response(project, task)
    assert not sessions.verify(project, "codex", "complete")["accepted"]


@pytest.mark.parametrize("target", ["outside", "product", "directory"])
def test_resume_rejects_redirected_verdict(project, monkeypatch, capsys, tmp_path, target):
    _, _, output = pending_review(project, monkeypatch, capsys)
    task = sessions.load(project, "codex", "complete")
    verdict = project / output["host_actions"]["jobs"][0]["verdict"]
    outside = tmp_path / "outside-verdict.json" if target == "outside" else project / "result.py"
    if target == "outside":
        outside.write_text("untouched")
    before = outside.read_bytes()
    if target == "directory":
        import shutil
        old = verdict.parent
        new = old.with_name("redirected")
        shutil.move(old, new)
        old.symlink_to(new, target_is_directory=True)
        assert old.is_symlink()
    else:
        verdict.symlink_to(outside)
        assert verdict.is_symlink()
    with pytest.raises(ValueError):
        agents.response(project, task)
    assert outside.read_bytes() == before


def test_known_failed_verification_can_be_fixed_without_reconcile_loop(project, monkeypatch, capsys):
    task, args = start(project, monkeypatch, "codex", "research")
    capsys.readouterr()
    cache = project / ".ai" / ("reevaluate-evidence-session-" + task["request_id"] + ".json")
    cache.write_text("{}")
    sessions.git(project, "add", str(cache))
    sessions.git(project, "commit", "-qm", "stale evaluation cache")
    assert cli.main(["finalize", *args]) == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["verification"]["phase"] == "failed"
    assert failed["host_actions"]["status"] == "resolve_checks"
    assert failed["host_actions"]["next_action"] == "finalize"
    cache.unlink()
    sessions.git(project, "add", str(cache))
    sessions.git(project, "commit", "-qm", "remove stale cache")
    assert cli.main([failed["host_actions"]["next_action"], *args]) == 1
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["verification"]["phase"] == "finished"
    assert repaired["host_actions"]["status"] == "awaiting_dispatch"
    assert len(list(sessions.session_dir(project, "codex", "complete").glob("*.execution-claim"))) == 1
