"""FS/Git/процессные пробы протокола; fixture-процесс НЕ живая приёмка коллег."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli.project_session import hook
from ai_ops_kit.lifecycle import project_session as sessions


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_research_preparation_resumes_same_request_without_repeating_signals(project, monkeypatch, runtime):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    prompt = "Проверь готовое исследование; не меняй продукт"
    task = sessions.begin(project, runtime, "resume-preparation", prompt)
    monkeypatch.chdir(project)
    args = ["run", "--runtime", runtime, "--session", "resume-preparation"]
    assert cli.main(args + ["--signals", '{"task_type":"research","size":"small","risk":"low"}']) == 1
    feature = "session-" + task["request_id"]
    spec_path = project / "features" / feature / "spec.yaml"
    spec = yaml.safe_load(spec_path.read_text())
    assert spec["level"] == 1  # RESEARCH, а не молчаливое понижение lowercase в QUICK
    assert spec["sections"] and all(s["status"] == "missing" for s in spec["sections"].values())
    pending = sessions.load(project, runtime, "resume-preparation")
    assert pending["request_id"] == task["request_id"] and pending["status"] == "pending"
    assert not (project / ".ai/runtime/process-observed").exists()
    assert not list(sessions.session_dir(project, runtime, "resume-preparation").glob("*.execution-claim"))
    assert not (project / "features" / feature / "run-report.json").exists()
    context = hook(runtime, {"cwd": str(project), "session_id": "resume-preparation", "hook_event_name": "SessionStart"})
    assert f"features/{feature}/spec.yaml" in context["hookSpecificOutput"]["additionalContext"]
    complete_prepared_spec(project, task)
    from ai_ops_kit.gates import preflight, spec_levels
    from ai_ops_kit.cli.ai_ops_cli import resolve_flags
    signals = pending["preparation"]["signals"]
    assert resolve_flags(signals)["author"] is False  # preset не изменён ради теста
    truth = preflight.assess(signals, project, feature, spec_cov=spec_levels.assess_from_artifacts(
        dict(signals, task_type="RESEARCH"), project, feature))
    assert truth["checks"]["spec"]["ok"]  # тот самый production spec-first blocker снят
    assert cli.main(args) == 0  # имитация resume: новый вызов CLI, signals уже на диске
    assert (project / ".ai/runtime/process-observed").read_text() == prompt
    assert sessions.load(project, runtime, "resume-preparation")["request_id"] == task["request_id"]
    assert sessions.verify(project, runtime, "resume-preparation")["accepted"]


@pytest.mark.parametrize("bad", ["missing", "broken", "empty", "declined-without-note"])
def test_incomplete_preparation_never_consumes_execution(project, monkeypatch, bad):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    task = sessions.begin(project, "codex", "bad-spec", "Исследуй архитектуру")
    path = project / "features" / ("session-" + task["request_id"]) / "spec.yaml"
    if bad != "missing":
        path.parent.mkdir(parents=True)
        path.write_text("bad: [" if bad == "broken" else yaml.safe_dump({"sections": {
            "goal": {"status": "declined" if bad == "declined-without-note" else "complete", "content": "", "note": None}}}))
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "bad-spec", "--signals",
            '{"task_type":"research","size":"small","risk":"low"}']
    assert cli.main(args) == 1
    assert path.is_file()
    if bad == "broken":
        assert path.read_text() == "bad: ["  # не перетирать чужой повреждённый документ
    assert sessions.load(project, "codex", "bad-spec")["status"] == "pending"
    assert not sessions.verify(project, "codex", "bad-spec")["accepted"]
    assert not (project / ".ai/runtime/process-observed").exists()
    assert not list(sessions.session_dir(project, "codex", "bad-spec").glob("*.execution-claim"))


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
    assert cli.main(args + ['{"task_type":"research","risk":"medium","size":"large"}']) == 1
    complete_prepared_spec(project, task)
    assert cli.main(args[:-1]) == 0
    assert (project / ".ai/runtime/process-observed").read_text() == task["prompt"]
    assert sessions.load(project, "codex", "recover")["request_id"] == task["request_id"]
    assert sessions.verify(project, "codex", "recover")["accepted"]


def complete_prepared_spec(root, task):
    path = root / "features" / ("session-" + task["request_id"]) / "spec.yaml"
    doc = yaml.safe_load(path.read_text())
    for section in doc["sections"].values():
        section.update(status="complete", content="Только контроль существующего исследования по коду, без изменения продукта.")
    path.write_text(yaml.safe_dump(doc, allow_unicode=True))


@pytest.mark.parametrize("case", ["empty-content", "numeric-content", "foreign-spec", "needs-human",
                                 "foreign-report", "claim", "source-drift", "symlink"])
def test_prepared_session_cannot_bypass_guards(project, monkeypatch, case):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    task = sessions.begin(project, "codex", "guards", "Проверь исследование")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "guards"]
    assert cli.main(args + ["--signals", '{"task_type":"research","size":"small","risk":"low"}']) == 1
    complete_prepared_spec(project, task)
    feature = project / "features" / ("session-" + task["request_id"])
    spec_path = feature / "spec.yaml"
    spec = yaml.safe_load(spec_path.read_text())
    if case == "empty-content":
        for section in spec["sections"].values():
            section["content"] = ""
    elif case == "numeric-content":
        spec["sections"]["goal"]["content"] = 123
    elif case == "foreign-spec":
        spec["workitem_id"] = "another-task"
    elif case == "needs-human":
        spec["sections"]["goal"]["status"] = "needs_human"
    spec_path.write_text(yaml.safe_dump(spec))
    expected = 1
    if case == "foreign-report":
        (feature / "run-report.json").write_text('{"ready_for_pr":true}')
        assert (feature / "run-report.json").is_file()
        expected = 2
    elif case == "claim":
        claim = sessions.session_dir(project, "codex", "guards") / (task["request_id"] + ".execution-claim")
        claim.write_text("already started")
        assert claim.is_file()
        expected = 2
    elif case == "source-drift":
        (project / "unexpected-result.md").write_text("real source change")
        assert sessions.binding(project, "session-" + task["request_id"]) != task["binding"]
        expected = 2
    elif case == "symlink":
        outside = project.parent / "outside-spec.yaml"
        outside.write_bytes(spec_path.read_bytes())
        spec_path.unlink()
        spec_path.symlink_to(outside)
        assert spec_path.is_symlink()
        expected = 2
    before = spec_path.read_bytes()
    assert cli.main(args) == expected
    assert spec_path.read_bytes() == before
    assert not (project / ".ai/runtime/process-observed").exists()
    assert sessions.load(project, "codex", "guards")["status"] == "pending"


def test_quick_task_without_spec_keeps_existing_light_path(project, monkeypatch):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    task = sessions.begin(project, "codex", "quick", "Исправь опечатку")
    monkeypatch.chdir(project)
    assert cli.main(["run", "--runtime", "codex", "--session", "quick", "--signals",
                     '{"task_type":"QUICK","size":"small","risk":"low"}']) == 0
    assert (project / ".ai/runtime/process-observed").read_text() == task["prompt"]
    assert not (project / "features" / ("session-" + task["request_id"]) / "spec.yaml").exists()


def test_actual_blocked_report_diagnostic_is_preserved_and_cannot_be_retried(project):
    script = f'''#!{sys.executable}
import json,sys
from pathlib import Path
args=sys.argv[1:]
folder=Path('features')/args[args.index('--feature')+1]
folder.mkdir(parents=True)
Path('.ai/runtime').mkdir(parents=True,exist_ok=True)
Path('.ai/runtime/process-observed').write_text('real preflight process ran')
(folder/'run-report.json').write_text(json.dumps(dict(kind='execution-pipeline',ready_for_pr=False,
    overall_status='blocked-preflight',error='spec-first: explicit missing prerequisite')))
sys.exit(1)
'''
    (project / "ai-ops").write_text(script)
    sessions.git(project, "add", "ai-ops")
    sessions.git(project, "commit", "-qm", "blocked report producer")
    sessions.begin(project, "codex", "preflight-error", "research")
    result = sessions.execute(project, "codex", "preflight-error", {"task_type": "research"})
    assert (project / ".ai/runtime/process-observed").read_text() == "real preflight process ran"
    assert result["status"] == "blocked"
    assert "spec-first: explicit missing prerequisite" in result["blocker"]
    with pytest.raises(ValueError, match="запуск уже учтён"):
        sessions.execute(project, "codex", "preflight-error", {"task_type": "research"})
    assert not sessions.verify(project, "codex", "preflight-error")["accepted"]


def test_parallel_resumes_cannot_mutate_preparation_or_execute_twice(project, monkeypatch):
    from ai_ops_kit.cli import project_session as cli
    from ai_ops_kit.shared import lifecycle_store
    fixture_producer(project)
    task = sessions.begin(project, "codex", "concurrent-resume", "Проверь исследование")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "concurrent-resume"]
    assert cli.main(args + ["--signals", '{"task_type":"research","size":"small","risk":"low"}']) == 1
    complete_prepared_spec(project, task)
    spec = project / "features" / ("session-" + task["request_id"]) / "spec.yaml"
    before = spec.read_bytes()
    children = []
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    lock = sessions.session_dir(project, "codex", "concurrent-resume") / "preparation"
    try:
        with lifecycle_store._journal_lock(lock, required=True):
            for i in range(2):
                code = (f"from pathlib import Path; Path('.ai/runtime/entered-{i}').touch(); "
                        f"from ai_ops_kit.cli.project_session import main; raise SystemExit(main({args!r}))")
                children.append(subprocess.Popen([sys.executable, "-c", code], cwd=project, env=env,
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 10
            while not all((project / f".ai/runtime/entered-{i}").exists() for i in range(2)) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert all((project / f".ai/runtime/entered-{i}").exists() for i in range(2))
            assert all(p.poll() is None for p in children)
            assert spec.read_bytes() == before
            assert not (project / ".ai/runtime/process-observed").exists()
        for child in children:
            child.communicate(timeout=30)
        assert sorted(p.returncode for p in children) == [0, 2]
        calls = (project / ".ai/runtime/process-calls.jsonl").read_text().splitlines()
        assert len(calls) == 1
        assert sessions.verify(project, "codex", "concurrent-resume")["accepted"]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


def test_new_prompt_during_preparation_cannot_execute_with_old_signals(project, monkeypatch):
    from ai_ops_kit.cli import project_session as cli
    fixture_producer(project)
    task = sessions.begin(project, "codex", "replaced", "Исследуй первый вопрос")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", "codex", "--session", "replaced"]
    assert cli.main(args + ["--signals", '{"task_type":"research","size":"small","risk":"low"}']) == 1
    complete_prepared_spec(project, task)
    original = cli.prepare
    def replace_after_preparation(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result is None
        new_task = sessions.begin(project, "codex", "replaced", "Совсем другой запрос")
        assert new_task["request_id"] != task["request_id"]
        return result
    monkeypatch.setattr(cli, "prepare", replace_after_preparation)
    assert cli.main(args) == 2
    assert not (project / ".ai/runtime/process-observed").exists()
    assert sessions.load(project, "codex", "replaced")["prompt"] == "Совсем другой запрос"
    assert not list(sessions.session_dir(project, "codex", "replaced").glob("*.execution-claim"))


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
workflow = (json.loads(args[args.index('--signals')+1]).get('task_type') or 'RESEARCH').upper()
d = Path('features') / fid
d.mkdir(parents=True, exist_ok=True)
(d / 'run-report.json').write_text(json.dumps(dict(kind='execution-pipeline', ready_for_pr=True,
    provider={'mock' if mode == 'mock' else 'controlled-fixture'!r}, runtime=runtime,
    workitem_id=fid, child_root=str(Path.cwd()),
    commit=dict(sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))))
(d / 'workitem.yaml').write_text(yaml.safe_dump(dict(task=args[1],workflow=workflow)))
(d / 'run-plan.yaml').write_text(yaml.safe_dump(dict(workitem_id=fid,base_workflow=workflow)))
lifecycle_store.journal_append(d / 'lifecycle-journal.jsonl',dict(kind='run_end',workitem_id=fid,ready_for_pr=True))
Path('.ai/runtime/process-observed').write_text(args[1])
with Path('.ai/runtime/process-calls.jsonl').open('a') as calls:
    calls.write(json.dumps(dict(feature=fid,runtime=runtime))+'\\n')
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


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_pinned_detached_checkout_binds_and_rejects_a_different_head(project, runtime):
    fixture_producer(project)
    revision = sessions.git(project, "rev-parse", "HEAD")
    sessions.git(project, "checkout", "--detach", revision)
    task = sessions.begin(project, runtime, "pinned", "исследуй архитектуру")
    assert task["status"] == "pending"
    assert task["binding"]["head"] == revision
    assert task["binding"]["branch"] == "HEAD"
    context = hook(runtime, {"cwd": str(project), "session_id": "pinned", "hook_event_name": "SessionStart"})
    assert "Сохранённая задача" in context["hookSpecificOutput"]["additionalContext"]
    result = sessions.execute(project, runtime, "pinned", {"task_type": "research"})
    assert (project / ".ai/runtime/process-observed").read_text() == task["prompt"]
    assert result["status"] == "accepted"
    assert sessions.verify(project, runtime, "pinned")["accepted"]
    sessions.git(project, "commit", "--allow-empty", "-qm", "different detached head")
    assert sessions.git(project, "rev-parse", "HEAD") != revision
    with pytest.raises(ValueError, match="прежнее подтверждение"):
        sessions.verify(project, runtime, "pinned")


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
