"""Реальные controller/review requests; fixture reviewer не является живой квалификацией."""
import json

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_agents as agents
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
