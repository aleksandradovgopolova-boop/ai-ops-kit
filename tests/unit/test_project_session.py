"""FS/Git/процессные пробы протокола; fixture-процесс НЕ живая приёмка коллег."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli.project_session import hook
from ai_ops_kit.lifecycle import project_session as sessions


def test_cli_incomplete_intake_can_be_corrected_without_consuming_attempt(project, monkeypatch, capsys):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    task = sessions.begin(project, "codex", "recover", "исследуй архитектуру")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "recover", "--signals"]
    assert cli.main(args + ['{"task_type":"research","risk":"medium"}']) == 2
    assert "size" in capsys.readouterr().err
    assert sessions.load(project, "codex", "recover")["status"] == "pending"
    assert not list(sessions.session_dir(project, "codex", "recover").glob("*.execution-claim"))
    assert not (project / ".ai/runtime/process-observed").exists()
    assert cli.main(args + ['{"task_type":"research","risk":"medium","size":"large"}']) == 0
    assert (project / ".ai/runtime/process-observed").read_text() == task["prompt"]
    assert sessions.load(project, "codex", "recover")["request_id"] == task["request_id"]
    assert sessions.verify(project, "codex", "recover")["accepted"]


@pytest.mark.parametrize("padding", ["", "x" * 5000], ids=["short", "bounded-tail"])
def test_missing_run_report_preserves_actual_process_diagnostic(project, padding):
    (project / "ai-ops").write_text("#!/bin/sh\nmkdir -p .ai/runtime\n"
                                    "touch .ai/runtime/process-observed\n"
                                    f"echo '{padding}runtime unavailable: explicit failure' >&2\nexit 2\n")
    sessions.git(project, "add", "ai-ops")
    sessions.git(project, "commit", "-qm", "failing process fixture")
    sessions.begin(project, "codex", "diagnostic", "research")
    task = sessions.execute(project, "codex", "diagnostic", {"task_type": "research"})
    assert (project / ".ai/runtime/process-observed").exists()
    assert task["status"] == "blocked"
    assert "runtime unavailable: explicit failure" in task["blocker"]
    assert "exit=2" in task["blocker"]
    assert "No such file" not in task["blocker"]
    assert len(task["blocker"].split("отчёт не создан: ", 1)[1]) <= 4096
    assert not sessions.verify(project, "codex", "diagnostic")["accepted"]
    with pytest.raises(ValueError, match="запуск уже учтён"):
        sessions.execute(project, "codex", "diagnostic", {"task_type": "research"})


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "fixture"),
                 ("config", "user.email", "fixture@example.test")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump({"parent": {"installed_version": "4.11.4"},
                                                     "standard": {"team_session": "required"}}))
    policy = root / ".ai/managed" / sessions.POLICY
    policy.parent.mkdir(parents=True)
    policy.write_text("fixture policy")
    (root / ".ai/managed/VERSION").write_text("4.11.4")
    (root / "ai-ops").write_text("#!/bin/sh\nexit 2\n")
    (root / "ai-ops").chmod(0o755)
    for name in ("AGENTS.md", "CLAUDE.md"):
        (root / name).write_text(sessions.instruction_block())
    for runtime, relative in sessions.RUNTIMES.items():
        p = root / relative
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"hooks": {e: [sessions.hook_group(runtime)] for e in sessions.EVENTS}}))
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def fixture_producer(root, mode="success"):
    """Отдельный процесс создаёт контрактные файлы. Нет вызовов модели/аккаунта."""
    source = f'''#!{sys.executable}
import json, sys, subprocess
from pathlib import Path
import yaml
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from ai_ops_kit.shared import lifecycle_store
args = sys.argv[1:]
fid = args[args.index('--feature')+1]
runtime = args[args.index('--runtime')+1]
d = Path('features') / fid
d.mkdir(parents=True)
(d / 'run-report.json').write_text(json.dumps(dict(kind='execution-pipeline', ready_for_pr=True,
    provider={'mock' if mode == 'mock' else 'controlled-fixture'!r}, runtime=runtime,
    workitem_id=fid, child_root=str(Path.cwd()),
    commit=dict(sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))))
(d / 'workitem.yaml').write_text(yaml.safe_dump(dict(task=args[1],workflow='RESEARCH')))
(d / 'run-plan.yaml').write_text(yaml.safe_dump(dict(workitem_id=fid,base_workflow='RESEARCH')))
lifecycle_store.journal_append(d / 'lifecycle-journal.jsonl',dict(kind='run_end',workitem_id=fid,ready_for_pr=True))
Path('.ai/runtime/process-observed').write_text(args[1])
sys.exit({1 if mode == 'error' else 0})
'''
    (root / "ai-ops").write_text(source)
    sessions.git(root, "add", "-A")
    sessions.git(root, "commit", "-qm", "controlled producer")


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_prompt_is_saved_before_any_execution(project, runtime):
    prompt = "Проведи ресерч агентной архитектуры $(touch should-not-exist)"
    task = sessions.begin(project / ".ai", runtime, "independent-profile", prompt, "turn-1")
    assert task["status"] == "pending"
    assert sessions.load(project, runtime, "independent-profile")["prompt"] == prompt
    assert not sessions.verify(project, runtime, "independent-profile")["accepted"]
    assert not (project / "should-not-exist").exists()


def test_process_and_artifacts_are_created_before_acceptance(project):
    fixture_producer(project)
    sessions.begin(project, "codex", "a", "исследуй архитектуру")
    task = sessions.execute(project, "codex", "a", {"task_type": "research"})
    assert (project / ".ai/runtime/process-observed").read_text() == "исследуй архитектуру"
    assert (project / f"features/session-{task['request_id']}/run-report.json").is_file()
    assert task["status"] == "accepted"
    assert sessions.verify(project, "codex", "a")["accepted"]
    assert hook("codex", {"cwd": str(project), "session_id": "a", "hook_event_name": "Stop"}) == {}


@pytest.mark.parametrize("mode", ("mock", "error"))
def test_mock_or_failed_process_is_not_accepted(project, mode):
    fixture_producer(project, mode)
    sessions.begin(project, "codex", "a", "research task")
    task = sessions.execute(project, "codex", "a", {"task_type": "research"})
    assert (project / ".ai/runtime/process-observed").is_file()  # запуск действительно произошёл
    assert task["status"] == "blocked"
    assert not sessions.verify(project, "codex", "a")["accepted"]


def test_old_report_cannot_replace_observed_execution(project):
    task = sessions.begin(project, "codex", "a", "task")
    old = project / f"features/session-{task['request_id']}/run-report.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"ready_for_pr": true}')
    assert old.is_file()
    with pytest.raises(ValueError, match="до запуска"):
        sessions.execute(project, "codex", "a", {})
    assert not (project / ".ai/runtime/process-observed").exists()


@pytest.mark.parametrize("change", ("branch", "policy", "config", "head", "integration"))
def test_changed_checkout_does_not_reuse_binding(project, change):
    sessions.begin(project, "codex", "a", "task")
    if change == "branch":
        sessions.git(project, "checkout", "-qb", "other")
        assert sessions.git(project, "branch", "--show-current") == "other"
    elif change == "head":
        sessions.git(project, "commit", "--allow-empty", "-qm", "new head")
    else:
        p = project / {"policy": ".ai/managed/" + sessions.POLICY,
                       "config": ".ai-ops.yaml", "integration": ".codex/hooks.json"}[change]
        p.write_text(p.read_text() + ("\n# change" if change == "config" else "changed"))
    with pytest.raises(ValueError):
        sessions.verify(project, "codex", "a")


def test_missing_entry_preserves_request_with_specific_blocker(project):
    (project / "ai-ops").unlink()
    task = sessions.begin(project, "claude-code", "a", "important request")
    assert task["status"] == "blocked"
    assert "точка входа" in task["blocker"]
    assert sessions.load(project, "claude-code", "a")["prompt"] == "important request"


def test_missing_or_foreign_session_is_rejected(project):
    sessions.begin(project, "codex", "a", "task")
    with pytest.raises(FileNotFoundError):
        sessions.verify(project, "codex", "b")
    task = sessions.load(project, "codex", "a")
    task["session_id"] = "b"
    path = sessions.session_dir(project, "codex", "a") / f"{task['request_id']}.json"
    sessions.write(path, task)
    with pytest.raises(ValueError, match="другой"):
        sessions.load(project, "codex", "a")


def test_artifact_mutation_invalidates_prior_acceptance(project):
    fixture_producer(project)
    sessions.begin(project, "codex", "a", "task")
    task = sessions.execute(project, "codex", "a", {})
    assert task["status"] == "accepted"
    report = project / f"features/session-{task['request_id']}/run-report.json"
    report.write_text(report.read_text() + " ")
    with pytest.raises(ValueError, match="артефакт изменён"):
        sessions.verify(project, "codex", "a")


def test_symlink_outside_project_is_rejected(project, tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("outside")
    policy = project / ".ai/managed" / sessions.POLICY
    policy.unlink()
    policy.symlink_to(outside)
    task = sessions.begin(project, "codex", "a", "task")
    assert task["status"] == "blocked"
    assert "выходит за проект" in task["blocker"]
    assert outside.read_text() == "outside"


def test_resume_keeps_original_task_and_stop_detects_skip(project):
    sessions.begin(project, "codex", "a", "original")
    payload = {"cwd": str(project), "session_id": "a", "hook_event_name": "SessionStart", "source": "compact"}
    assert "Сохранённая задача" in hook("codex", payload)["hookSpecificOutput"]["additionalContext"]
    payload["hook_event_name"] = "Stop"
    assert hook("codex", payload)["continue"] is False
    payload["stop_hook_active"] = True
    assert "не подтвердил" in hook("codex", payload)["systemMessage"]
    assert sessions.load(project, "codex", "a")["prompt"] == "original"


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
@pytest.mark.parametrize("case", ["pending", "binding-drift", "missing-task", "malformed-config"])
def test_stop_refuses_without_creating_a_model_continuation(project, runtime, case, monkeypatch, capsys):
    from ai_ops_kit.cli import project_session as cli
    task = sessions.begin(project, runtime, "bounded-stop", "original research")
    if case == "binding-drift":
        (project / "unrelated.txt").write_text("new source")
    elif case == "missing-task":
        (sessions.session_dir(project, runtime, "bounded-stop") / f"{task['request_id']}.json").unlink()
    elif case == "malformed-config":
        (project / ".ai-ops.yaml").write_text("standard: [broken")
    import io
    payload = {"cwd": str(project), "session_id": "bounded-stop", "hook_event_name": "Stop"}
    for active in [False, True, False]:
        payload["stop_hook_active"] = active
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
        assert cli.main(["--runtime", runtime]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["continue"] is False
        assert "decision" not in result
        assert "не подтвердил" in result["stopReason"]
    assert len(list(sessions.session_dir(project, runtime, "bounded-stop").glob("*.json"))) <= 2


@pytest.mark.parametrize("raw", [b'{"hook_event_name":"Stop"', b'[]', b'x' * 262145],
                         ids=["truncated-json", "wrong-shape", "oversized"])
def test_invalid_hook_payload_cannot_request_a_paid_continuation(raw, monkeypatch, capsys):
    import io
    from ai_ops_kit.cli import project_session as cli
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    assert cli.main(["--runtime", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["continue"] is False
    assert "decision" not in result
    assert "не считается принятой" in result["stopReason"]


def test_disabled_hooks_are_diagnosed(project):
    path = project / ".claude/settings.json"
    doc = json.loads(path.read_text())
    doc["disableAllHooks"] = True
    path.write_text(json.dumps(doc))
    assert any("отключены" in p for p in sessions.configuration_problems(project))


def test_source_changed_without_commit_invalidates_acceptance(project):
    (project / "product.py").write_text("original")
    fixture_producer(project)
    sessions.begin(project, "codex", "a", "task")
    assert sessions.execute(project, "codex", "a", {})["status"] == "accepted"
    (project / "product.py").write_text("different")
    assert (project / "product.py").read_text() == "different"
    with pytest.raises(ValueError, match="изменились"):
        sessions.verify(project, "codex", "a")


def test_existing_execution_claim_prevents_second_process(project):
    fixture_producer(project)
    task = sessions.begin(project, "codex", "a", "task")
    claim = sessions.session_dir(project, "codex", "a") / (task["request_id"] + ".execution-claim")
    claim.touch()
    with pytest.raises(ValueError, match="уже закреплена"):
        sessions.execute(project, "codex", "a", {})
    assert not (project / ".ai/runtime/process-observed").exists()


def test_dirty_result_is_rejected_before_receipt(project):
    fixture_producer(project)
    # Имитация конкурентной правки до завершения наблюдаемого процесса.
    # binding ещё совпадает на входе, правку делает сам отдельный процесс.
    script = project / "ai-ops"
    source = script.read_text().replace("sys.exit(0)", "Path('unchecked.txt').write_text('unchecked')\nsys.exit(0)")
    script.write_text(source)
    sessions.git(project, "add", "ai-ops")
    sessions.git(project, "commit", "-qm", "controlled concurrent mutation")
    sessions.begin(project, "codex", "a", "task")
    result = sessions.execute(project, "codex", "a", {})
    assert (project / "unchecked.txt").read_text() == "unchecked"
    assert result["status"] == "blocked"
    assert "рабочая копия изменена" in result["blocker"]


def test_source_digest_preserves_filename_whitespace(project):
    path = project / " source with spaces.txt "
    path.write_text("before")
    before = sessions.source_digest(project)
    path.write_text("after")
    assert path.read_text() == "after"
    assert sessions.source_digest(project) != before
