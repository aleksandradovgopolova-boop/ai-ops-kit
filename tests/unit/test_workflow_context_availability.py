"""Workflow, который GitHub не может разобрать, не запускается вовсе (#1409).

`${{ runner.temp }}` в `env` уровня job сделал ручной замер производительности невозможным:
GitHub отвергал файл целиком и на каждый push показывал красный «прогон» за 0 с. Детектор —
`ai_ops_kit/devtools/workflow_contexts.py`; здесь он прогоняется по настоящим workflow кита и
шаблонам, которые едут в проекты, и по файлам с той самой ошибкой.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.devtools import workflow_contexts as wc

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", wc.default_paths(ROOT), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_kit_and_template_workflows_use_available_contexts(path):
    assert wc.check_files([path]) == {}


def test_detector_catches_the_real_regression(tmp_path):
    """Fail-closed: ровно та форма, что сломала performance-baseline.yml, — находка и код 1."""
    broken = tmp_path / "broken.yml"
    broken.write_text(
        "on: {workflow_dispatch: {}}\n"
        "jobs:\n  pair:\n    runs-on: ${{ vars.R || 'ubuntu-latest' }}\n"
        "    if: github.event_name == 'push' && steps.a.outputs.ok\n"
        "    env:\n      OUT: ${{ runner.temp }}/x\n      SHA: ${{ inputs.sha }}\n"
        "    steps: [{run: 'true'}]\n")
    assert wc.check_files([broken]) == {str(broken): ["jobs.pair.env: runner", "jobs.pair.if: steps"]}
    result = subprocess.run([sys.executable, "-m", "ai_ops_kit.devtools.workflow_contexts", str(broken)],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1 and "GitHub отвергнет файл целиком" in result.stdout


def test_step_level_runner_and_quoted_literals_are_not_findings(tmp_path):
    ok = tmp_path / "ok.yml"
    ok.write_text(
        "env: {A: '${{ github.sha }}'}\n"
        "jobs:\n  j:\n    runs-on: ${{ vars.R || 'runner.temp' }}\n"
        "    if: ${{ needs.full-gate.result == 'success' }}\n"
        "    steps: [{env: {OUT: '${{ runner.temp }}'}, run: 'true'}]\n")
    assert wc.check_files([ok]) == {}


def test_unreadable_yaml_is_a_finding_not_silence(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("jobs: [unclosed\n")
    found = wc.check_files([bad])
    assert list(found) == [str(bad)] and found[str(bad)][0].startswith("не читается:")


def test_the_measurement_workflow_itself_is_now_valid():
    """Сам performance-baseline.yml: OUT в env шага, а не job (иначе dispatch невозможен)."""
    assert wc.check_files([ROOT / ".github/workflows/performance-baseline.yml"]) == {}
