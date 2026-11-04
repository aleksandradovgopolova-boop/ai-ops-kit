"""Полный native-путь через реальные controller, проверки и offline reviewer-артефакты."""
import json
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from test_project_session import project as _project_fixture, complete_prepared_spec
from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_completion as completion
from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.engine import reviewer_handoff


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


def start(project, monkeypatch, runtime, task_type="quick"):
    (project / ".gitignore").write_text(".ai/runtime/\n__pycache__/\n.pytest_cache/\n")
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1.0.0"\n')
    cfg = yaml.safe_load((project / ".ai-ops.yaml").read_text())
    cfg["verification"] = {"commands": {"test": "python3 verify.py"}}
    (project / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg))
    (project / "result.py").write_text("VALUE = 0\n")
    (project / "verify.py").write_text("from pathlib import Path\n"
        "Path('.ai/runtime/check-ran').write_text('real check')\n"
        "assert Path('result.py').read_text() == 'VALUE = 7\\n'\n")
    sessions.git(project, "add", "-A")
    sessions.git(project, "commit", "-qm", "test environment")
    task = sessions.begin(project, runtime, "complete", "Проверь результат", "turn-one")
    monkeypatch.chdir(project)
    args = ["--runtime", runtime, "--session", "complete"]
    assert cli.main(["run", *args, "--signals", json.dumps(dict(task_type=task_type, size="small", risk="low"))]) == 1
    if task_type == "research":
        complete_prepared_spec(project, task)
        assert cli.main(["run", *args]) == 1
    (project / "result.py").write_text("VALUE = 7\n")
    sessions.git(project, "add", "-A")
    sessions.git(project, "commit", "-qm", "first part of result")
    (project / "followup.md").write_text("second commit\n")
    sessions.git(project, "add", "followup.md")
    sessions.git(project, "commit", "-qm", "second part of result")
    return sessions.load(project, runtime, "complete"), args


def reviewer_receipts(project, task, runtime):
    """Контролируемый независимый fixture; не доказательство живого review."""
    handoff = sessions.session_dir(project, runtime, "complete") / (task["request_id"] + ".reviews")
    digests = {}
    for request_path in (handoff / ".ai/reviewer-requests").glob("*.request.json"):
        request = json.loads(request_path.read_text())
        gid = request["gate"]
        verdict = {k: request[k] for k in completion.scope(task, sessions.binding(project, "session-" + task["request_id"]))}
        verdict.update(schema_version=1, reviewer="independent-fixture")
        if gid == "acceptance":
            verdict.update(kind="acceptance-result", criteria=[
                {"id": c["id"], "status": "met", "quote": "VALUE = 7", "source": "result.py"}
                for c in request["criteria"]])
        else:
            verdict.update(kind="reviewer-result", gate=gid, status="pass", checks=[
                {"id": key, "status": "pass", "evidence": [{"file": "result.py", "lines": "1"}]}
                for key in request["required_evidence"] or ["logic"]])
        path = reviewer_handoff.verdict_path(handoff, gid)
        path.write_text(json.dumps(verdict))
        digests[gid] = sessions.digest(path.read_bytes())
    return handoff, digests


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_native_finish_runs_checks_accepts_then_handles_next_prompt(project, monkeypatch, runtime):
    task, args = start(project, monkeypatch, runtime)
    assert cli.main(["finalize", *args]) == 0
    assert (project / ".ai/runtime/check-ran").read_text() == "real check"
    saved = sessions.load(project, runtime, "complete")
    assert saved["status"] == "accepted" and saved["request_id"] == task["request_id"]
    assert sessions.verify(project, runtime, "complete")["accepted"]
    envelope = json.loads((project / saved["verification"]["report"]).read_text())
    assert envelope["pipeline"]["loop"]["stopped"] == "reevaluate-only"
    assert envelope["pipeline"]["loop"]["steps"] == 0
    assert envelope["pipeline"]["gates"]["blocked"] is False
    assert cli.hook(runtime, {"cwd": str(project), "session_id": "complete", "hook_event_name": "Stop"}) == {}
    assert cli.main(["finalize", *args]) == 0  # повтор не запускает проверки заново
    after = sessions.load(project, runtime, "complete")
    assert after["verification"]["attempt"] == saved["verification"]["attempt"]
    new = sessions.begin(project, runtime, "complete", "следующая настоящая задача", "turn-two")
    assert new["request_id"] != task["request_id"]
    assert (sessions.session_dir(project, runtime, "complete") / (task["request_id"] + ".execution-claim")).exists()


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_research_requires_independent_scoped_acceptance_before_finish(project, monkeypatch, runtime):
    task, args = start(project, monkeypatch, runtime, "research")
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, runtime, "complete")
    assert saved["status"] == "running"
    handoff = sessions.session_dir(project, runtime, "complete") / (task["request_id"] + ".reviews")
    request = json.loads(reviewer_handoff.request_path(handoff, "acceptance").read_text())
    assert "result.py" in request["changed_files"] and "followup.md" in request["changed_files"]
    handoff, digests = reviewer_receipts(project, task, runtime)
    path = reviewer_handoff.verdict_path(handoff, "acceptance")
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(digests)]) == 0
    assert sessions.verify(project, runtime, "complete")["accepted"]
    report = json.loads((project / sessions.load(project, runtime, "complete")["verification"]["report"]).read_text())
    assert report["pipeline"]["acceptance_criteria"]["verified"] is True
    path.write_text("tampered verdict")
    with pytest.raises(ValueError, match="артефакт изменён"):
        sessions.verify(project, runtime, "complete")


@pytest.mark.parametrize("damage", ["self", "stale", "wrong-task", "bad-hash", "malformed", "fake-quote"])
def test_invalid_independent_evidence_never_accepts_or_consumes_claim(project, monkeypatch, damage):
    task, args = start(project, monkeypatch, "codex", "research")
    assert cli.main(["finalize", *args]) == 1
    handoff, digests = reviewer_receipts(project, task, "codex")
    path = reviewer_handoff.verdict_path(handoff, "acceptance")
    verdict = json.loads(path.read_text())
    if damage == "self":
        verdict["reviewer"] = "codex:complete"
    elif damage == "stale":
        verdict["reviewed_revision"] = task["binding"]["head"]
    elif damage == "wrong-task":
        verdict["workitem_id"] = "another-task"
    elif damage == "fake-quote":
        verdict["criteria"][0]["quote"] = "THIS NEVER EXISTED"
    path.write_text("[broken" if damage == "malformed" else json.dumps(verdict))
    if damage != "bad-hash":
        digests["acceptance"] = sessions.digest(path.read_bytes())
    else:
        digests["acceptance"] = "0" * 64
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(digests)]) == 1
    saved = sessions.load(project, "codex", "complete")
    assert saved["status"] != "accepted"
    assert not sessions.verify(project, "codex", "complete")["accepted"]
    assert (sessions.session_dir(project, "codex", "complete") / (task["request_id"] + ".execution-claim")).exists()
    if damage != "fake-quote":
        assert reviewer_handoff.request_path(handoff, "acceptance").is_file()


def test_known_failed_check_can_be_fixed_and_reverified_without_new_execution(project, monkeypatch):
    task, args = start(project, monkeypatch, "claude-code")
    (project / "result.py").write_text("VALUE = 8\n")
    sessions.git(project, "add", "result.py")
    sessions.git(project, "commit", "-qm", "bad result")
    assert cli.main(["finalize", *args]) == 1
    assert (project / ".ai/runtime/check-ran").exists()
    failed = sessions.load(project, "claude-code", "complete")
    assert failed["verification"]["phase"] == "finished"
    (project / "result.py").write_text("VALUE = 7\n")
    sessions.git(project, "add", "result.py")
    sessions.git(project, "commit", "-qm", "repair result")
    assert cli.main(["finalize", *args]) == 0
    saved = sessions.load(project, "claude-code", "complete")
    assert saved["request_id"] == task["request_id"]
    assert saved["verification_history"][0]["attempt"] == failed["verification"]["attempt"]
    assert len(list(sessions.session_dir(project, "claude-code", "complete").glob("*.execution-claim"))) == 1


def test_reconcile_recovers_durable_success_after_supervisor_interruption(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    actual = sessions.run_process
    def interrupted(*a, **kw):
        actual(*a, **kw)  # проверки реально исполнились и записали durable checksum
        raise subprocess.TimeoutExpired(a[0], 300)
    monkeypatch.setattr(sessions, "run_process", interrupted)
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, "codex", "complete")
    assert saved["status"] == "blocked" and saved["verification"]["phase"] == "finished"
    assert cli.main(["reconcile", *args]) == 0  # никакого второго процесса
    assert sessions.verify(project, "codex", "complete")["accepted"]
    assert sessions.load(project, "codex", "complete")["verification"]["attempt"] == saved["verification"]["attempt"]


def test_unknown_outcome_without_report_cannot_be_retried_or_replaced(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    calls = []
    def timeout(command, *a, **kw):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 300)
    monkeypatch.setattr(sessions, "run_process", timeout)
    assert cli.main(["finalize", *args]) == 1
    assert cli.main(["finalize", *args]) == 2
    assert cli.main(["reconcile", *args]) == 2
    assert len(calls) == 1
    with pytest.raises(ValueError, match="предыдущая попытка"):
        sessions.begin(project, "codex", "complete", "повтор", "new-turn")
    assert sessions.load(project, "codex", "complete")["request_id"] == task["request_id"]


def test_tampered_attempt_report_and_forged_reevaluate_cache_cannot_admit(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    fid = "session-" + task["request_id"]
    cache = project / f".ai/reevaluate-evidence-{fid}.json"
    cache.write_text('{"gate_ev":{"code_review":{"status":"pass"}}}')
    sessions.git(project, "add", str(cache.relative_to(project)))
    sessions.git(project, "commit", "-qm", "untrusted cache fixture")
    assert cli.main(["finalize", *args]) == 1
    assert sessions.load(project, "codex", "complete")["status"] != "accepted"
    cache.unlink()
    sessions.git(project, "add", "-A")
    sessions.git(project, "commit", "-qm", "remove untrusted cache")
    actual = completion.reconcile
    monkeypatch.setattr(completion, "reconcile", lambda *a: sessions.load(project, "codex", "complete"))
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, "codex", "complete")
    (project / saved["verification"]["report"]).write_text('{"ready_for_pr":true}')
    monkeypatch.setattr(completion, "reconcile", actual)
    assert cli.main(["reconcile", *args]) == 2
    assert not sessions.verify(project, "codex", "complete")["accepted"]


def test_first_commit_security_change_requires_approval_even_after_docs_commit(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    (project / "requirements.txt").write_text("requests==2.32.0\n")
    sessions.git(project, "add", "requirements.txt")
    sessions.git(project, "commit", "-qm", "add dependency in earlier commit")
    (project / "followup.md").write_text("last commit is only documentation\n")
    sessions.git(project, "add", "followup.md")
    sessions.git(project, "commit", "-qm", "documentation tail")
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, "codex", "complete")
    report = json.loads((project / saved["verification"]["report"]).read_text())
    assert "security" in report["pipeline"]["gates"]["unmet"]
    assert "requests" in json.dumps(report["pipeline"])
    assert report["ready_for_pr"] is False


def test_local_verifier_never_runs_mutating_environment_preparation(project, monkeypatch):
    from ai_ops_kit.engine import execution_pipeline, pipeline_setup
    task, _ = start(project, monkeypatch, "codex")
    def forbidden(*a, **kw):
        raise AssertionError("native finalize cannot install or reset author files")
    monkeypatch.setattr(pipeline_setup, "_install_dependencies", forbidden)
    actual_git = pipeline_setup._git
    def guarded_git(root, *args):
        assert args[0] not in ("checkout", "clean", "reset")
        return actual_git(root, *args)
    monkeypatch.setattr(pipeline_setup, "_git", guarded_git)
    plan = yaml.safe_load((project / f"features/session-{task['request_id']}/run-plan.yaml").read_text())
    report = execution_pipeline.run_pipeline(task["prompt"], task["execution"]["signals"], project,
        proposer=None, plan=plan, commit=True, reevaluate_only=True, install_deps=False,
        base_revision=task["binding"]["head"])
    assert report["ready_for_pr"] is True


def test_generated_task_namespace_does_not_hide_real_authentication_or_secrets():
    from ai_ops_kit.security import security_pack
    namespace = "features/session-" + "a" * 32 + "/"
    pack = security_pack.run_pack(files_content={namespace + "run-plan.yaml": "kind: run-plan"})
    assert "authentication" not in pack["needs_review"]
    pack = security_pack.run_pack(files_content={namespace + "session.py": "def login(): pass"})
    assert "authentication" in pack["needs_review"]
    pack = security_pack.run_pack(files_content={namespace + "run-plan.yaml": "api_key: " + "AKIA" + "A" * 16})
    assert "secrets" in pack["blocking"]


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_metadata_only_final_commit_does_not_require_auth_approval(project, monkeypatch, runtime):
    task, args = start(project, monkeypatch, runtime)
    metadata = project / f"features/session-{task['request_id']}/trace.yaml"
    metadata.write_text("kind: execution-note\n")
    sessions.git(project, "add", str(metadata.relative_to(project)))
    sessions.git(project, "commit", "-qm", "metadata-only tail")
    assert sessions.git(project, "diff", "--name-only", "HEAD^") == str(metadata.relative_to(project))
    assert cli.main(["finalize", *args]) == 0
    assert sessions.verify(project, runtime, "complete")["accepted"]
    assert (project / ".ai/runtime/check-ran").read_text() == "real check"


def test_separate_human_approval_scan_uses_entire_pinned_range(project, monkeypatch):
    from ai_ops_kit.engine import pipeline_readiness
    from ai_ops_kit.security import security_pack
    task, _ = start(project, monkeypatch, "codex")
    (project / "session.py").write_text("VALUE = 1\n")
    sessions.git(project, "add", "session.py")
    sessions.git(project, "commit", "-qm", "real auth path in earlier commit")
    (project / "followup.md").write_text("docs tail\n")
    sessions.git(project, "add", "followup.md")
    sessions.git(project, "commit", "-qm", "docs tail")
    assert sessions.git(project, "diff", "--name-only", "HEAD^") == "followup.md"
    # Даже чистый pack/reviewer не заменяет обязательное человеческое одобрение.
    monkeypatch.setattr(security_pack, "run_pack", lambda *a, **kw:
        dict(overall="clear", applicable_domains=[], blocking=[], needs_review=[], advisory=[]))
    evidence, _, _ = pipeline_readiness._evaluate_security(project, project,
        "session-" + task["request_id"], sessions.git(project, "rev-parse", "HEAD"), True, {}, {},
        review=False, strict_judge_qualified=False, security_reviewer_proposer=None,
        reviewer_proposer=None, budget=None, base_revision=task["binding"]["head"])
    assert evidence["security"]["status"] == "fail"
    assert "authentication" in evidence["security"]["human_approval_uncovered"]


def test_task_namespace_keeps_real_auth_path_and_local_approval_trust_barrier(project, monkeypatch):
    from ai_ops_kit.engine import pipeline_evidence
    from ai_ops_kit.gates import approvals
    namespace = "features/session-" + "a" * 32 + "/"
    monkeypatch.setattr(approvals, "load_approvals", lambda *a: [{"approval": "authentication"}])
    monkeypatch.setattr(approvals, "_record_valid", lambda *a, **kw: True)
    monkeypatch.setattr(approvals, "covers_paths", lambda *a: True)
    assert pipeline_evidence._human_approval_domains_uncovered(project, "task",
        [namespace + "run-plan.yaml"], diff_root=project) == []
    assert "authentication" in pipeline_evidence._human_approval_domains_uncovered(project, "task",
        [namespace + "session.py"], diff_root=project)


@pytest.mark.parametrize("error", ["exception", "none"])
def test_separate_security_diff_read_error_fails_closed(project, monkeypatch, error):
    from ai_ops_kit.engine import pipeline_readiness
    from ai_ops_kit.security import security_pack, security_scan
    monkeypatch.setattr(security_pack, "run_pack", lambda *a, **kw:
        dict(overall="clear", applicable_domains=[], blocking=[], needs_review=[], advisory=[]))
    def unavailable(*a, **kw):
        if error == "exception":
            raise OSError("cannot read diff")
        return None  # настоящий контракт security_scan при ошибке Git/timeout
    monkeypatch.setattr(security_scan, "_git_changed_files", unavailable)
    evidence, _, _ = pipeline_readiness._evaluate_security(project, project, "task",
        sessions.git(project, "rev-parse", "HEAD"), True, {}, {}, review=False,
        strict_judge_qualified=False, security_reviewer_proposer=None,
        reviewer_proposer=None, budget=None)
    assert evidence["security"]["status"] == "fail"
    assert "security diff" in evidence["security"]["blockers"][0]


def test_ignored_spec_change_invalidates_trusted_independent_review(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex", "research")
    fid = "session-" + task["request_id"]
    sessions.git(project, "rm", "-r", "--cached", f"features/{fid}")
    (project / ".gitignore").write_text((project / ".gitignore").read_text() + "features/\n")
    sessions.git(project, "add", ".gitignore")
    sessions.git(project, "commit", "-qm", "ignored lifecycle artifacts fixture")
    assert cli.main(["finalize", *args]) == 1
    _, digests = reviewer_receipts(project, task, "codex")
    before = sessions.binding(project, fid)
    original_scope = completion.scope(task, before)
    path = project / f"features/{fid}/spec.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["sections"]["acceptance_criteria"]["content"] = "A different acceptance obligation"
    path.write_text(yaml.safe_dump(spec))
    after = sessions.binding(project, fid)
    assert after == before  # ignored lifecycle inputs не видны обычному source digest
    assert completion.scope(task, after)["artifacts_sha256"] != original_scope["artifacts_sha256"]
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(digests)]) == 1
    assert not sessions.verify(project, "codex", "complete")["accepted"]


def test_shared_registry_lock_is_bounded_by_supervised_verifier(project, monkeypatch):
    from ai_ops_kit.lifecycle import active_work
    from ai_ops_kit.lifecycle.work_claims import _locked
    task, args = start(project, monkeypatch, "codex")
    actual = sessions.run_process
    monkeypatch.setattr(sessions, "run_process", lambda command, root, directory, **kw:
                        actual(command, root, directory, timeout=2))
    started = time.monotonic()
    with _locked(active_work.shared_registry_path(project)):
        assert cli.main(["finalize", *args]) == 1
    assert time.monotonic() - started < 6
    assert (project / ".ai/runtime/check-ran").exists()  # проверка дошла до terminal bookkeeping
    saved = sessions.load(project, "codex", "complete")
    assert saved["status"] == "blocked" and saved["verification"]["phase"] == "running"
    assert cli.main(["reconcile", *args]) == 2
    assert (sessions.session_dir(project, "codex", "complete") / (task["request_id"] + ".execution-claim")).exists()


def test_ui_collection_sees_earlier_commit_and_never_installs_dependencies(project, monkeypatch):
    from ai_ops_kit.engine import execution_pipeline
    from ai_ops_kit.ui import ui_readiness, ui_evidence_collect
    task, _ = start(project, monkeypatch, "codex")
    (project / "Button.tsx").write_text("export const Button = () => null;\n")
    sessions.git(project, "add", "Button.tsx")
    sessions.git(project, "commit", "-qm", "UI in earlier commit")
    (project / "followup.md").write_text("docs tail\n")
    sessions.git(project, "add", "followup.md")
    sessions.git(project, "commit", "-qm", "docs tail")
    observed, calls = [], []
    original = ui_readiness.should_run_ui_evidence
    def observe(changed, signals):
        observed.extend(changed)
        return original(changed, signals)
    monkeypatch.setattr(ui_readiness, "should_run_ui_evidence", observe)
    monkeypatch.setattr(ui_evidence_collect, "collect", lambda *a, **kw: calls.append(kw))
    plan = yaml.safe_load((project / f"features/session-{task['request_id']}/run-plan.yaml").read_text())
    execution_pipeline.run_pipeline(task["prompt"], task["execution"]["signals"], project,
        proposer=None, plan=plan, commit=True, reevaluate_only=True, install_deps=False,
        calibrated_enforcement=True, base_revision=task["binding"]["head"],
        review_handoff_root=project / ".ai/runtime/handoff")
    assert "Button.tsx" in observed and calls == [{"install_deps": False}]


@pytest.mark.parametrize("foreign", [False, True])
def test_reconcile_recovers_controller_handoff_without_reexecuting(project, monkeypatch, foreign):
    task, args = start(project, monkeypatch, "codex")
    saved = sessions.load(project, "codex", "complete")
    saved["execution"].pop("prepared")
    saved["execution"].pop("files")
    saved["status"] = "blocked"
    path = sessions.session_dir(project, "codex", "complete") / (task["request_id"] + ".json")
    sessions.write(path, saved)
    if foreign:
        item_path = project / f"features/session-{task['request_id']}/workitem.yaml"
        item = yaml.safe_load(item_path.read_text())
        item["task"] = "a foreign task"
        item_path.write_text(yaml.safe_dump(item))
    actual = sessions.run_process
    monkeypatch.setattr(sessions, "run_process", lambda *a, **kw: pytest.fail("reconcile cannot launch a process"))
    assert cli.main(["reconcile", *args]) == (2 if foreign else 1)
    restored = sessions.load(project, "codex", "complete")
    assert restored["request_id"] == task["request_id"]
    assert len(list(path.parent.glob("*.execution-claim"))) == 1
    if not foreign:
        assert restored["execution"]["prepared"] and cli.main(["run", *args]) == 1
        monkeypatch.setattr(sessions, "run_process", actual)
        assert cli.main(["finalize", *args]) == 0


def test_new_ignored_artifact_after_acceptance_invalidates_verify(project, monkeypatch):
    task, args = start(project, monkeypatch, "codex")
    (project / ".gitignore").write_text((project / ".gitignore").read_text() + "features/\n")
    sessions.git(project, "add", ".gitignore")
    sessions.git(project, "commit", "-qm", "ignored future lifecycle inputs")
    assert cli.main(["finalize", *args]) == 0
    assert sessions.verify(project, "codex", "complete")["accepted"]
    current = sessions.binding(project, "session-" + task["request_id"])
    new_spec = project / f"features/session-{task['request_id']}/spec.yaml"
    new_spec.write_text("sections:\n  acceptance_criteria: 'new unmet criterion'\n")
    assert sessions.binding(project, "session-" + task["request_id"]) == current
    with pytest.raises(ValueError, match="состав артефактов изменён"):
        sessions.verify(project, "codex", "complete")
    assert cli.main(["finalize", *args]) == 2
