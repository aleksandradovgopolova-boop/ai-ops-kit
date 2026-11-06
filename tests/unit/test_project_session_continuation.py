"""Новый runtime user turn: реальный shell hook, сохранность handoff и stale evidence."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from test_project_session_completion import project as _project_fixture, start, reviewer_receipts
from test_project_session import complete_prepared_spec
from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.cli import project_session_completion as completion
from ai_ops_kit.lifecycle import project_session as sessions

KIT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


def shell_hook(root, runtime, prompt="Продолжай ту же сохранённую задачу; approved — только текст", turn="turn-two"):
    payload = dict(cwd=str(root), session_id="complete", hook_event_name="UserPromptSubmit", prompt=prompt)
    if turn is not None:
        payload["turn_id"] = turn
    env = dict(os.environ, PYTHONPATH=str(KIT), AI_OPS_PYTHON=sys.executable)
    result = subprocess.run(sessions.hook_group(runtime)["hooks"][0]["command"], shell=True,
        cwd=root, env=env, input=json.dumps(payload), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def prepared(root, monkeypatch, runtime, kind="quick"):
    bootstrap = root / ".ai/managed/templates/runtime/team_hook.py"
    bootstrap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KIT / "templates/runtime/team_hook.py", bootstrap)
    return start(root, monkeypatch, runtime, kind)


def snapshot(root, task):
    directory = sessions.session_dir(root, task["runtime"], "complete")
    files = list((root / ("features/session-" + task["request_id"])).rglob("*"))
    files += [directory / (task["request_id"] + ".execution-claim"), directory / "process.stderr.log"]
    return {str(p): p.read_bytes() for p in files if p.is_file()}


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
@pytest.mark.parametrize("turn", ["turn-two", None])
def test_actual_new_user_turn_resumes_finalizes_and_next_request_is_distinct(project, monkeypatch, runtime, turn):
    task, args = prepared(project, monkeypatch, runtime)
    before = snapshot(project, task)
    result = shell_hook(project, runtime, turn=turn)
    assert result.get("continue") is not False and result.get("decision") != "block"
    context = result["hookSpecificOutput"]["additionalContext"]
    saved = sessions.load(project, runtime, "complete")
    assert saved["request_id"] == task["request_id"] and saved["prompt"] == task["prompt"]
    assert saved.get("preparation") == task.get("preparation")
    assert saved["execution"] == task["execution"] and saved["status"] == task["status"]
    assert snapshot(project, task) == before  # нет controller/provider, перезаписи claim или плана
    paths = list(saved["input_receipts"])
    assert len(paths) == 1 and paths[0] in context
    receipt_path = project / paths[0]
    receipt = json.loads(receipt_path.read_text())
    assert receipt["identity_scope"] == ("reliable" if turn else "unreliable")
    assert receipt["request_id"] == task["request_id"] and receipt["turn_id"] == turn
    assert "approved" in receipt["prompt"] and receipt_path.stat().st_mode & 0o777 == 0o600
    assert not list(project.rglob("*approval*.yaml"))
    first = receipt_path.read_bytes(), receipt_path.stat().st_mtime_ns
    if turn:
        assert shell_hook(project, runtime, turn=turn) == result
        assert (receipt_path.read_bytes(), receipt_path.stat().st_mtime_ns) == first
    else:
        shell_hook(project, runtime, turn=None)
        assert len(sessions.load(project, runtime, "complete")["input_receipts"]) == 2
    assert cli.main(["run", *args]) == 1
    assert cli.main(["finalize", *args]) == 0
    assert cli.main(["reconcile", *args]) == 0
    assert sessions.verify(project, runtime, "complete")["accepted"]
    # Поздний continuation не превращается в новую задачу после accepted.
    if turn:
        assert shell_hook(project, runtime, turn=turn)["continue"] is False
    next_result = shell_hook(project, runtime, prompt="Следующая настоящая задача", turn="next-request")
    assert next_result.get("continue") is not False
    next_task = sessions.load(project, runtime, "complete")
    assert next_task["request_id"] != task["request_id"] and snapshot(project, task) == before
    if turn:
        assert shell_hook(project, runtime, turn="turn-two")["continue"] is False
    assert sessions.load(project, runtime, "complete") == next_task
    assert sessions.git(project, "ls-files", ".ai/runtime") == ""  # private receipts не входят в Git


@pytest.mark.parametrize("damage", ["unknown", "autonomous", "unprepared", "missing-claim", "claim-content",
                                   "plan", "binding", "empty-files", "symlink-claim"])
def test_invalid_handoff_never_records_input_or_replaces_task(project, monkeypatch, damage):
    task, _ = prepared(project, monkeypatch, "codex")
    directory = sessions.session_dir(project, "codex", "complete")
    claim = directory / (task["request_id"] + ".execution-claim")
    if damage == "unknown":
        task.pop("execution")
    elif damage == "autonomous":
        task["execution"]["mode"] = "autonomous"
    elif damage == "unprepared":
        task["execution"].pop("prepared")
    elif damage == "missing-claim":
        claim.unlink()
    elif damage == "claim-content":
        claim.write_text("unknown outcome")
    elif damage == "symlink-claim":
        claim.unlink()
        other = directory / "other-claim"
        other.write_text("")
        claim.symlink_to(other)
    elif damage == "plan":
        (project / f"features/session-{task['request_id']}/run-plan.yaml").write_text("tampered")
    elif damage == "binding":
        task["binding"]["managed_sha256"] = "0" * 64
    elif damage == "empty-files":
        task["execution"]["files"] = {}
    sessions.write(directory / (task["request_id"] + ".json"), task)
    before = snapshot(project, task)
    assert shell_hook(project, "codex")["continue"] is False
    assert sessions.load(project, "codex", "complete") == task
    assert snapshot(project, task) == before and not list(directory.glob("*.inputs"))


def test_conflicting_late_and_malformed_events_do_not_rewrite_receipts(project, monkeypatch):
    task, _ = prepared(project, monkeypatch, "codex")
    assert shell_hook(project, "codex").get("continue") is not False
    saved = sessions.load(project, "codex", "complete")
    receipt = project / next(iter(saved["input_receipts"]))
    before = receipt.read_bytes(), receipt.stat().st_mtime_ns
    for turn, prompt in [("turn-two", "conflicting input"), ("", "malformed"), (5, "wrong type"),
                         ("turn-one", task["prompt"])]:
        assert shell_hook(project, "codex", prompt, turn)["continue"] is False
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
    assert shell_hook(project, "codex", turn="turn-three").get("continue") is not False
    assert shell_hook(project, "codex", turn="turn-two")["continue"] is False
    assert len(sessions.load(project, "codex", "complete")["input_receipts"]) == 2


@pytest.mark.parametrize("damage", ["edit", "delete", "add"])
def test_input_receipt_tamper_fails_closed(project, monkeypatch, damage):
    task, args = prepared(project, monkeypatch, "codex")
    shell_hook(project, "codex")
    task = sessions.load(project, "codex", "complete")
    receipt = project / next(iter(task["input_receipts"]))
    if damage == "edit":
        receipt.write_text("{}")
    elif damage == "delete":
        receipt.unlink()
    else:
        (receipt.parent / "foreign.json").write_text("{}")
    assert shell_hook(project, "codex", turn="turn-three")["continue"] is False
    assert cli.main(["finalize", *args]) == 2
    assert sessions.load(project, "codex", "complete")["status"] != "accepted"


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_blocked_known_handoff_allows_input_and_invalidates_old_independent_review(project, monkeypatch, runtime):
    task, args = prepared(project, monkeypatch, runtime, "research")
    assert cli.main(["finalize", *args]) == 1
    _, digests = reviewer_receipts(project, task, runtime)
    task = sessions.load(project, runtime, "complete")
    task["status"] = "blocked"
    directory = sessions.session_dir(project, runtime, "complete")
    sessions.write(directory / (task["request_id"] + ".json"), task)
    assert shell_hook(project, runtime).get("continue") is not False
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(digests)]) == 1
    assert not sessions.verify(project, runtime, "complete")["accepted"]
    _, fresh = reviewer_receipts(project, sessions.load(project, runtime, "complete"), runtime)
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(fresh)]) == 0


def test_input_between_worker_and_reconcile_invalidates_finished_report(project, monkeypatch):
    task, args = prepared(project, monkeypatch, "codex")
    actual = sessions.run_process
    def delayed_reconcile(*a, **kw):
        result = actual(*a, **kw)
        assert shell_hook(project, "codex").get("continue") is not False
        return result
    monkeypatch.setattr(sessions, "run_process", delayed_reconcile)
    assert cli.main(["finalize", *args]) == 2
    assert cli.main(["reconcile", *args]) == 2
    assert not sessions.verify(project, "codex", "complete")["accepted"]
    monkeypatch.setattr(sessions, "run_process", actual)
    assert cli.main(["finalize", *args]) == 0


def test_input_during_real_check_invalidates_worker_scope(project, monkeypatch):
    task, args = prepared(project, monkeypatch, "claude-code")
    verify = project / "verify.py"
    payload = dict(cwd=str(project), session_id="complete", hook_event_name="UserPromptSubmit",
                   turn_id="during-verification", prompt="Уточнение во время проверки")
    verify.write_text(verify.read_text() + '\nimport subprocess, sys, os, json\n'
        + "marker = Path('.ai/runtime/input-during-check')\n"
        + 'if not marker.exists():\n'
        + '    marker.write_text("once")\n'
        + f'    env = dict(os.environ, PYTHONPATH={str(KIT)!r})\n'
        + f'    p = subprocess.run([sys.executable, "-m", "ai_ops_kit.cli.project_session", "hook", "--runtime", "claude-code"], input={json.dumps(payload)!r}, text=True, capture_output=True, env=env, check=True)\n'
        + '    assert json.loads(p.stdout).get("continue") is not False\n')
    sessions.git(project, "add", "verify.py")
    sessions.git(project, "commit", "-qm", "actual check with concurrent input fixture")
    assert cli.main(["finalize", *args]) == 1
    saved = sessions.load(project, "claude-code", "complete")
    assert saved["verification"]["phase"] == "failed" and saved["input_receipts"]
    assert not sessions.verify(project, "claude-code", "complete")["accepted"]
    assert cli.main(["reconcile", *args]) == 2
    assert cli.main(["finalize", *args]) == 0
    assert sessions.verify(project, "claude-code", "complete")["accepted"]


def test_runtime_payload_must_be_ignored_before_recording(project, monkeypatch):
    task, _ = prepared(project, monkeypatch, "codex")
    (project / ".gitignore").write_text("__pycache__/\n")
    assert shell_hook(project, "codex")["continue"] is False
    assert sessions.load(project, "codex", "complete") == task
    assert not list(sessions.session_dir(project, "codex", "complete").glob("*.inputs"))


def test_original_event_replay_before_input_remains_idempotent(project, monkeypatch):
    task, _ = prepared(project, monkeypatch, "codex")
    before = snapshot(project, task)
    assert shell_hook(project, "codex", task["prompt"], "turn-one").get("continue") is not False
    assert sessions.load(project, "codex", "complete") == task and snapshot(project, task) == before


def test_tracked_private_input_invalidates_verification(project, monkeypatch):
    task, args = prepared(project, monkeypatch, "codex")
    shell_hook(project, "codex")
    saved = sessions.load(project, "codex", "complete")
    path = next(iter(saved["input_receipts"]))
    sessions.git(project, "add", "-f", path)
    sessions.git(project, "commit", "-qm", "unsafe fixture: tracked private input")
    assert cli.main(["finalize", *args]) == 2
    assert sessions.load(project, "codex", "complete")["status"] != "accepted"


def test_partial_receipt_write_is_preserved_and_never_admitted(project, monkeypatch):
    task, _ = prepared(project, monkeypatch, "codex")
    directory = sessions.session_dir(project, "codex", "complete")
    original_write = sessions.write
    def interrupted(path, value):
        if path == directory / (task["request_id"] + ".json"):
            raise OSError("fixture fsync/store failure after immutable receipt")
        return original_write(path, value)
    monkeypatch.setattr(sessions, "write", interrupted)
    payload = dict(cwd=str(project), session_id="complete", hook_event_name="UserPromptSubmit",
                   turn_id="turn-two", prompt="Продолжение")
    with pytest.raises(OSError, match="store failure"):
        cli.hook("codex", payload)
    assert sessions.load(project, "codex", "complete") == task
    receipts = list(directory.glob("*.inputs/*.json"))
    assert len(receipts) == 1
    before = receipts[0].read_bytes(), receipts[0].stat().st_mtime_ns
    assert shell_hook(project, "codex", "Продолжение")["continue"] is False
    assert (receipts[0].read_bytes(), receipts[0].stat().st_mtime_ns) == before


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
@pytest.mark.parametrize("turn", ["intake-answer", None])
def test_requested_pending_intake_answer_preserves_original_and_supplied_signals(project, monkeypatch, runtime, turn):
    # Установить реальный bootstrap до initial binding, но не готовить controller заранее.
    bootstrap = project / ".ai/managed/templates/runtime/team_hook.py"
    bootstrap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KIT / "templates/runtime/team_hook.py", bootstrap)
    (project / ".gitignore").write_text(".ai/runtime/\n__pycache__/\n")
    cfgpath = project / ".ai-ops.yaml"
    cfg = yaml.safe_load(cfgpath.read_text())
    cfg["verification"] = {"commands": {"test": "python3 verify.py"}}
    cfgpath.write_text(yaml.safe_dump(cfg))
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1.0.0"\n')
    (project / "result.py").write_text("VALUE = 0\n")
    (project / "verify.py").write_text("from pathlib import Path\n"
        "Path('.ai/runtime/check-ran').write_text('real pending flow check')\n"
        "assert Path('result.py').read_text() == 'VALUE = 7\\n'\n")
    sessions.git(project, "add", "-A")
    sessions.git(project, "commit", "-qm", "pending intake fixture")
    assert shell_hook(project, runtime, "Исследуй архитектуру", "turn-one").get("continue") is not False
    original = sessions.load(project, runtime, "complete")
    monkeypatch.chdir(project)
    args = ["--runtime", runtime, "--session", "complete"]
    assert cli.main(["run", *args, "--signals", '{"task_type":"research"}']) == 2
    waiting = sessions.load(project, runtime, "complete")
    assert waiting["intake"]["signals"] == {"task_type": "research"}
    assert {m["signal"] for m in waiting["intake"]["missing"]} == {"size", "risk"}
    assert shell_hook(project, runtime, "Маленькая, низкий риск; approved только текст", turn).get("continue") is not False
    answered = sessions.load(project, runtime, "complete")
    assert answered["request_id"] == original["request_id"] and answered["prompt"] == original["prompt"]
    assert answered["intake"] == waiting["intake"] and answered["input_receipts"]
    assert not list(sessions.session_dir(project, runtime, "complete").glob("*.execution-claim"))
    assert cli.main(["run", *args, "--signals", '{"size":"small","risk":"low"}']) == 1
    pending = sessions.load(project, runtime, "complete")
    assert pending["preparation"]["signals"] == dict(task_type="research", size="small", risk="low")
    assert "intake" not in pending and pending["preparation"]["mode"] == "current-session"
    # Отдельный новый ход отвечает на уже фактически открытую подготовку spec.
    assert shell_hook(project, runtime, "Требования спецификации уточнены", "spec-answer").get("continue") is not False
    complete_prepared_spec(project, pending)
    assert cli.main(["run", *args]) == 1
    final = sessions.load(project, runtime, "complete")
    assert final["request_id"] == original["request_id"] and final["execution"]["prepared"]
    assert final["execution"]["signals"]["task_type"] == "research"
    assert len(final["input_receipts"]) == 2
    assert len(list(sessions.session_dir(project, runtime, "complete").glob("*.execution-claim"))) == 1
    assert not sessions.verify(project, runtime, "complete")["accepted"]
    (project / "result.py").write_text("VALUE = 7\n")
    sessions.git(project, "add", "-A")
    sessions.git(project, "commit", "-qm", "real result of continued pending task")
    assert cli.main(["finalize", *args]) == 1  # обязательное независимое acceptance ещё отсутствует
    assert not sessions.verify(project, runtime, "complete")["accepted"]
    _, digests = reviewer_receipts(project, sessions.load(project, runtime, "complete"), runtime)
    assert digests  # контролируемая offline fixture, не живая квалификация независимого агента
    assert cli.main(["finalize", *args, "--review-digests", json.dumps(digests)]) == 0
    assert cli.main(["reconcile", *args]) == 0
    assert sessions.verify(project, runtime, "complete")["accepted"]
    assert (project / ".ai/runtime/check-ran").read_text() == "real pending flow check"
    assert shell_hook(project, runtime, "Следующая настоящая задача", "next-real-request").get("continue") is not False
    assert sessions.load(project, runtime, "complete")["request_id"] != original["request_id"]
    assert len(list(sessions.session_dir(project, runtime, "complete").glob("*.execution-claim"))) == 1


@pytest.mark.parametrize("mode", ["autonomous", "missing-fact", "tampered-missing"])
def test_unconfirmed_pending_intake_marker_cannot_accept_continuation(project, monkeypatch, mode):
    task, _ = prepared(project, monkeypatch, "codex")
    directory = sessions.session_dir(project, "codex", "complete")
    (directory / (task["request_id"] + ".execution-claim")).unlink()
    task.pop("execution")
    task["status"] = "pending"
    # Remove controller files: a pending request must have no old execution report.
    shutil.rmtree(project / f"features/session-{task['request_id']}")
    from ai_ops_kit.engine import pipeline_helpers
    missing = pipeline_helpers.missing_intake_signals({"task_type": "research"})
    task["intake"] = dict(mode="autonomous" if mode == "autonomous" else "current-session",
                          signals={"task_type": "research"}, missing=missing)
    if mode == "missing-fact":
        task["intake"].pop("missing")
    elif mode == "tampered-missing":
        task["intake"]["missing"] = []
    task["binding"] = sessions.binding(project, "session-" + task["request_id"])
    sessions.write(directory / (task["request_id"] + ".json"), task)
    assert shell_hook(project, "codex")["continue"] is False
    assert sessions.load(project, "codex", "complete") == task
    assert not list(directory.glob("*.inputs"))


def test_ordered_input_history_is_bound_and_verified_after_acceptance(project, monkeypatch):
    task, args = prepared(project, monkeypatch, "codex")
    for turn in ("answer-a", "answer-b", "answer-c"):
        assert shell_hook(project, "codex", turn=turn).get("continue") is not False
    saved = sessions.load(project, "codex", "complete")
    current = sessions.binding(project, "session-" + task["request_id"])
    original_scope = completion.scope(saved, current)
    reordered = json.loads(json.dumps(saved))
    reordered["input_events"][:2] = list(reversed(reordered["input_events"][:2]))
    assert completion.scope(reordered, current)["inputs_sha256"] != original_scope["inputs_sha256"]
    assert cli.main(["finalize", *args]) == 0
    accepted = sessions.load(project, "codex", "complete")
    assert accepted["execution"]["input_events"] == saved["input_events"]
    accepted["input_events"][:2] = list(reversed(accepted["input_events"][:2]))
    path = sessions.session_dir(project, "codex", "complete") / (task["request_id"] + ".json")
    sessions.write(path, accepted)
    with pytest.raises(ValueError, match="порядок"):
        sessions.verify(project, "codex", "complete")


def test_claim_preserves_input_that_arrived_after_outer_task_snapshot(project, monkeypatch):
    task, _ = prepared(project, monkeypatch, "codex", "research")
    directory = sessions.session_dir(project, "codex", "complete")
    # Вернуться к валидному known pending spec без исполнения, затем взять stale snapshot.
    (directory / (task["request_id"] + ".execution-claim")).unlink()
    task.pop("execution")
    task["status"] = "pending"
    task["preparation"]["ready"] = False
    (project / f"features/session-{task['request_id']}/run-report.json").unlink()
    task["binding"] = sessions.binding(project, "session-" + task["request_id"])
    sessions.write(directory / (task["request_id"] + ".json"), task)
    snapshot_task = json.loads(json.dumps(task))
    assert shell_hook(project, "codex").get("continue") is not False
    current = sessions.load(project, "codex", "complete")
    claimed = sessions.claim_execution(project, "codex", "complete", snapshot_task,
                                       {"mode": "current-session"})
    assert claimed["input_receipts"] == current["input_receipts"]
    assert claimed["input_events"] == current["input_events"]
    assert claimed["input_latest"] == current["input_latest"]
    assert sessions.load(project, "codex", "complete") == claimed
