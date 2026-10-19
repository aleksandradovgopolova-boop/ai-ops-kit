"""Настоящий CLI subprocess: профиль, отказ и отсутствие эффектов plan-only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

KIT = Path(__file__).resolve().parents[2]


@pytest.fixture
def child(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit',
                    '--allow-empty', '-qm', 'fixture'], check=True)
    risk = tmp_path / '.github/workflows/check.yml'
    risk.parent.mkdir(parents=True)
    risk.write_text('name: risk\n')
    script = tmp_path / 'scripts/check-full.sh'
    script.parent.mkdir()
    script.write_text('printf "%s\\n" "$@" > selected-profile.txt\nexit "${FIXTURE_EXIT:-0}"\n')
    return tmp_path


def cli(child, intent, *extra, exit_code=0):
    return subprocess.run([sys.executable, '-m', 'ai_ops_kit.devtools.impact_check_cli',
                           '--root', str(child), '--intent', intent, *extra],
                          cwd=KIT, text=True, capture_output=True, timeout=20,
                          env={**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null',
                               'FIXTURE_EXIT': str(exit_code), 'PYTHONDONTWRITEBYTECODE': '1'})


@pytest.mark.parametrize('intent', ['draft', 'ready_for_review', 'merge_candidate'])
def test_ordinary_full_fallback_executes_existing_pr_profile(child, intent):
    result = cli(child, intent)
    actual = (child / 'selected-profile.txt').read_text().splitlines()
    assert actual == ['--pr']  # Real script effect precedes the policy assertion.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['full_command'] is True
    assert json.loads(result.stdout)['full_profile'] == 'pr-current-python'
    assert json.loads(result.stdout)['full_argv'] == ['bash', 'scripts/check-full.sh', '--pr']


def test_release_full_fallback_keeps_default_nightly_profile(child):
    result = cli(child, 'release_candidate')
    assert (child / 'selected-profile.txt').is_file()
    assert (child / 'selected-profile.txt').read_text().strip() == ''
    assert result.returncode == 0
    assert json.loads(result.stdout)['full_profile'] == 'full-current-python'
    assert json.loads(result.stdout)['full_argv'] == ['bash', 'scripts/check-full.sh']


def test_failed_full_fallback_propagates_exit_code(child):
    result = cli(child, 'draft', exit_code=7)
    assert (child / 'selected-profile.txt').read_text().strip() == '--pr'
    assert result.returncode == 7


def test_plan_only_does_not_execute_full_profile(child):
    result = cli(child, 'merge_candidate', '--plan-only')
    assert result.returncode == 0
    assert json.loads(result.stdout)['full_command'] is True
    assert json.loads(result.stdout)['full_profile'] == 'pr-current-python'
    assert json.loads(result.stdout)['full_argv'] == ['bash', 'scripts/check-full.sh', '--pr']
    assert not (child / 'selected-profile.txt').exists()
