"""RESEARCH через установившиеся CLI-пути, Git и сохранённый controller handoff."""
import json

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.lifecycle import active_work, project_session as sessions
from test_project_session import complete_prepared_spec, project as project_fixture


@pytest.fixture
def research(tmp_path, monkeypatch, capsys):
    root = project_fixture.__wrapped__(tmp_path, monkeypatch)
    (root / ".gitignore").write_text(".ai/runtime/\n__pycache__/\n")
    sessions.git(root, "add", ".gitignore")
    sessions.git(root, "commit", "-qm", "test environment")
    task = sessions.begin(root, "codex", "research", "Проверь вывод по коду", "turn-one")
    monkeypatch.chdir(root)
    args = ["--runtime", "codex", "--session", "research"]
    assert cli.main(["run", *args, "--signals", json.dumps({"task_type": "research", "risk": "low", "size": "small"})]) == 1
    complete_prepared_spec(root, task)
    capsys.readouterr()
    assert cli.main(["run", *args]) == 1
    task = json.loads(capsys.readouterr().out)
    assert task["execution"]["prepared"] and task["preparation"]["workflow"] == "RESEARCH"
    return root, task, args


def test_research_handoff_preserves_output_paths_after_resume(research, capsys):
    root, task, args = research
    plan = task["host_actions"]["after_plan"]
    fid = "session-" + task["request_id"]
    expected = {k: f"features/{fid}/{k}.md" for k in ("proposal", "verification")}
    assert plan["research_outputs"] == expected
    assert plan["next_action"] == "finalize" and plan["required_before_final_answer"] is True
    assert cli.main(["run", *args]) == 1
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["request_id"] == task["request_id"] and resumed["host_actions"]["after_plan"] == plan
    assert all(not (root / p).exists() for p in expected.values())


@pytest.mark.parametrize("case", ["own", "external", "adjacent", "link"])
def test_dirty_research_returns_scoped_recovery_without_mutation(research, capsys, case):
    root, task, args = research
    outputs = task["host_actions"]["after_plan"]["research_outputs"]
    proposal = root / outputs["proposal"]
    evidence = root / outputs["verification"]
    if case == "link":
        proposal.symlink_to(root / "AGENTS.md")
    else:
        proposal.write_text("Вывод и источник — AGENTS.md, строка 1.\n")
    foreign = None
    if case in ("external", "adjacent"):
        directory = root if case == "external" else proposal.parent
        foreign = directory / "чужой файл\nс переносом.md"
        foreign.write_text("other writer")
        if case == "external":
            sessions.git(root, "add", "--", str(foreign))
    head = sessions.git(root, "rev-parse", "HEAD")
    session_dir = sessions.session_dir(root, "codex", "research")
    claim = session_dir / (task["request_id"] + ".execution-claim")
    registry = active_work.shared_registry_path(root)
    files = [claim, registry, root / ".git/index", session_dir / (task["request_id"] + ".json"),
             *(proposal.parent).iterdir()]
    if foreign:
        files.append(foreign)
    before = {p: p.read_bytes() for p in files}
    assert cli.main(["finalize", *args]) == 2
    error = json.loads(capsys.readouterr().out)
    assert error["accepted"] is False and error["status"] == "blocked"
    recovery = error["recovery"]
    assert recovery["request_id"] == task["request_id"] and recovery["current_revision"] == head
    ours = set(task["execution"]["files"]) | {task["preparation"]["spec"]}
    if case != "link":
        ours.add(outputs["proposal"])
    assert set(recovery["task_paths"]) == ours
    expected_other = ([outputs["proposal"]] if case == "link" else
                      [str(foreign.relative_to(root))] if foreign else [])
    assert recovery["other_paths"] == expected_other
    assert recovery["status"] == ("other_changes" if expected_other else "uncommitted_research")
    assert outputs["verification"] in recovery["missing_outputs"] and not evidence.exists()
    assert {p: p.read_bytes() for p in files} == before and sessions.git(root, "rev-parse", "HEAD") == head
    assert not list(session_dir.glob("*.verification-*.json"))
    assert sessions.load(root, "codex", "research")["status"] != "accepted"


def test_research_checkpoint_refuses_changed_controller_artifact(research, capsys):
    root, task, args = research
    path = root / task["host_actions"]["plan"]
    path.write_text(path.read_text() + "# replaced\n")
    assert cli.main(["finalize", *args]) == 2
    out = capsys.readouterr()
    assert not out.out and "подготовленный артефакт изменён" in out.err
    assert sessions.load(root, "codex", "research")["execution"]["prepared"] is True


def test_checkpointed_research_requests_independent_review(research, capsys):
    root, task, args = research
    outputs = task["host_actions"]["after_plan"]["research_outputs"]
    (root / outputs["proposal"]).write_text("Вывод: инструкции проекта в AGENTS.md. Источник: AGENTS.md:1.\n")
    (root / outputs["verification"]).write_text("Проверено наличие AGENTS.md в дереве HEAD через git ls-tree.\n")
    assert cli.main(["finalize", *args]) == 2
    recovery = json.loads(capsys.readouterr().out)["recovery"]
    assert recovery["status"] == "uncommitted_research" and recovery["missing_outputs"] == []
    sessions.git(root, "add", "--", *recovery["task_paths"])
    sessions.git(root, "commit", "-qm", "record fixture research")
    assert cli.main(["finalize", *args]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["request_id"] == task["request_id"] and result["status"] != "accepted"
    handoff = result["host_actions"]
    assert handoff["status"] == "awaiting_dispatch" and handoff["jobs"]
    assert handoff["scope"]["base_revision"] == recovery["base_revision"]
    assert handoff["scope"]["reviewed_revision"] == sessions.git(root, "rev-parse", "HEAD")
