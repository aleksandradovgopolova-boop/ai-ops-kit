"""#1387: привязка замера покрытия к исходникам — реальные файлы, без запуска тестов."""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.devtools import coverage_binding as cb
from ai_ops_kit.devtools import crap_score as cs

pytestmark = pytest.mark.unit


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "ai_ops_kit").mkdir()
    (tmp_path / "ai_ops_kit" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"meta": {"format": 3, "version": "7.10.0"}, "files": {
        "ai_ops_kit/m.py": {"executed_lines": [1, 2], "missing_lines": [], "excluded_lines": []}}}))
    return tmp_path, report


def snapshot_and_bind(root, report, tests_exit=0, change=None):
    inputs = root / "inputs.json"
    assert cb.main(["snapshot", "--root", str(root), "--out", str(inputs)]) == 0
    if change:
        change(root)
    out = root / "binding.json"
    code = cb.main(["bind", "--root", str(root), "--inputs", str(inputs), "--report", str(report),
                    "--tests-exit", str(tests_exit), "--scope", "fixture", "--out", str(out),
                    "--", "python3", "-m", "pytest"])
    return code, out


def test_binding_is_accepted_by_crap_score(tree):
    root, report = tree
    code, out = snapshot_and_bind(root, report)
    assert code == 0
    assert json.loads(out.read_text())["command"] == ["python3", "-m", "pytest"]
    evidence = cs.load_coverage(root, report, out)
    assert not evidence.stale
    assert cs.analyze(root, evidence, {})["unknown_functions"] == 0


def test_failed_tests_give_a_binding_crap_score_refuses(tree):
    root, report = tree
    code, out = snapshot_and_bind(root, report, tests_exit=1)
    assert code == 0 and json.loads(out.read_text())["outcome"] == "failed"
    with pytest.raises(ValueError):
        cs.load_coverage(root, report, out)


@pytest.mark.parametrize("change", [
    lambda r: (r / "ai_ops_kit" / "m.py").write_text("def f():\n    return 2\n"),
    lambda r: (r / "ai_ops_kit" / "new.py").write_text("X = 1\n"),
])
def test_inputs_changed_during_the_run_write_no_binding(tree, change):
    root, report = tree
    code, out = snapshot_and_bind(root, report, change=change)
    assert code == 2 and not out.exists()
