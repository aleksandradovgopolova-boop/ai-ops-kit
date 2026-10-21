"""Draft-проверка учитывает ранний коммит задачи и не принимает неизвестный diff за skip."""
import shlex
import subprocess
import sys

import pytest

from ai_ops_kit.engine import pipeline_setup, tool_broker
from ai_ops_kit.gates import evidence_collector


@pytest.fixture
def history(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "executed.log"

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (root / "src/value.py").write_text("value = 1\n")
    for name, imports, check in [("direct", "from src.value import value\n", "value == 1"),
                                 ("unrelated", "", "True")]:
        (root / f"tests/test_{name}.py").write_text(
            imports + f"def test_{name}():\n"
            f"    with open({str(log)!r}, 'a') as stream: stream.write({name!r} + '\\n')\n"
            f"    assert {check}\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (root / "src/value.py").write_text("value = 2\n")
    git("add", ".")
    git("commit", "-qm", "early code change")
    (root / "README.md").write_text("Late documentation\n")
    git("add", ".")
    git("commit", "-qm", "late prose")
    return root, log, base, git("rev-parse", "HEAD")


def collect_through_pipeline(history, base, monkeypatch):
    root, _, _, head = history
    profile = {"stacks": [{"language": "python", "commands": {
        "test": shlex.join([sys.executable, "-m", "pytest", "tests", "-q"])}}]}
    real_collect, observed = evidence_collector.collect, {}

    class Collected(Exception):
        pass

    def capture(*args, **kwargs):
        observed.update(real_collect(*args, **kwargs))
        raise Collected()  # Остальные стадии не относятся к выбору и исполнению тестов.

    monkeypatch.setattr(evidence_collector, "collect", capture)
    with pytest.raises(Collected):
        pipeline_setup._assemble_evidence(profile, root,
            tool_broker.Policy(level="execution", child_root=str(root)), root, "fixture", {}, {}, {},
            commit=True, is_git=True, committed_sha=head, base_sha=base, authored_ev={},
            allow_missing_tests=False, calibrated_enforcement=False, ui_evidence=None,
            review=False, reviewer_proposer=None, budget=None, strict_judge_qualified=True,
            security_reviewer_proposer=None, reevaluate_only=False, verification_intent="draft")
    return observed


def test_early_commit_is_really_checked_despite_late_prose(history, monkeypatch):
    result = collect_through_pipeline(history, history[2], monkeypatch)
    assert history[1].read_text().splitlines() == ["direct"]
    assert result["checks"]["test"]["status"] == "fail"
    assert result["verification"]["changed_files"] == ["README.md", "src/value.py"]
    assert result["verification"]["tier"] == "affected"


@pytest.mark.parametrize("base", [None, "missing-ref"])
def test_unknown_range_executes_full_suite_instead_of_skipping(history, monkeypatch, base):
    result = collect_through_pipeline(history, base, monkeypatch)
    assert set(history[1].read_text().splitlines()) == {"direct", "unrelated"}
    assert result["checks"]["test"]["status"] == "fail"
    assert result["verification"] is None
