"""Workflow гейта скорости и памяти (#1409): fixture-проверки проводки, не Actions-замеры.

Логика сравнения и чистоты окна живёт в `ai_ops_kit.devtools.perf_gate` и проверена в
`tests/unit/test_perf_gate.py`. Здесь — то, что видно только в YAML: когда запускается, что
зовёт, откуда берёт базу и что не прячет красный результат.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import host_resource_cli as gate

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/performance-baseline.yml'
EVIDENCE = 'qualification/evidence/performance-baseline-1409'


def workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def steps():
    return workflow()['jobs']['paired-gate']['steps']


def step(name):
    return next(s for s in steps() if s.get('name') == name)


def test_runs_manually_and_nightly_but_never_on_pull_requests():
    config = workflow()
    assert set(config['on']) == {'workflow_dispatch', 'schedule'}
    assert config['on']['schedule'][0]['cron'].split()[2:] == ['*', '*', '*']
    assert set(config['on']['workflow_dispatch']['inputs']) == {'candidate_sha', 'base_sha'}
    assert all(i['required'] == 'false' for i in config['on']['workflow_dispatch']['inputs'].values())


def test_read_only_serialized_and_actions_are_pinned():
    config = workflow()
    assert config['permissions'] == {'contents': 'read'}
    assert config['concurrency']['cancel-in-progress'] == 'false'
    for item in steps():
        if 'uses' in item:
            assert len(item['uses'].split('@')[1]) == 40
        assert item.get('continue-on-error') in (None, 'false')


def test_run_blocks_parse_as_bash():
    for item in steps():
        if item.get('run'):
            subprocess.run(['bash', '-n'], input=item['run'], text=True, check=True)


def test_gate_step_runs_the_pair_under_one_lease_and_keeps_red_red():
    run = step('База и кандидат на одной машине под одной lease')['run']
    assert 'ai_ops_kit.devtools.host_resource_cli' in run and 'ai_ops_kit.devtools.perf_gate pair' in run
    assert '--threshold 1.2' in run and '|| true' not in run
    assert '$EVIDENCE/suite.json' in run and '$EVIDENCE/accepted-memory-baseline.json' in run
    assert workflow()['jobs']['paired-gate']['env']['EVIDENCE'] == EVIDENCE
    assert (ROOT / EVIDENCE / 'suite.json').is_file()
    assert (ROOT / EVIDENCE / 'accepted-memory-baseline.json').is_file()


def test_receipts_are_kept_even_when_the_gate_fails():
    upload = next(s for s in steps() if 'upload-artifact' in s.get('uses', ''))
    assert upload['if'] == 'always()'
    assert upload['with']['path'] == '${{ runner.temp }}/performance-gate'


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


@pytest.fixture
def tagged_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 't@example.invalid')
    git(repo, 'config', 'user.name', 't')
    for index in range(3):
        (repo / 'f.txt').write_text(str(index))
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', f'c{index}')
        if index == 1:
            git(repo, 'tag', 'v1.0.0')
    return repo


def pick(repo, tmp_path, candidate='', base='', head=None):
    output = tmp_path / 'github-output'
    output.write_text('')
    env = {**os.environ, 'INPUT_CANDIDATE': candidate, 'INPUT_BASE': base,
           'GITHUB_SHA': head or git(repo, 'rev-parse', 'HEAD'), 'GITHUB_OUTPUT': str(output)}
    result = subprocess.run(['bash', '-c', step('Выбрать базу и кандидата')['run']], cwd=repo, env=env,
                            text=True, capture_output=True)
    return result.returncode, dict(line.split('=', 1) for line in output.read_text().splitlines())


def test_nightly_base_is_the_latest_release_reachable_from_the_candidate(tagged_repo, tmp_path):
    code, picked = pick(tagged_repo, tmp_path)
    assert code == 0
    assert picked['candidate'] == git(tagged_repo, 'rev-parse', 'HEAD')
    assert picked['base'] == git(tagged_repo, 'rev-list', '-n', '1', 'v1.0.0')


def test_candidate_on_a_release_tag_is_compared_with_the_previous_release(tagged_repo, tmp_path):
    git(tagged_repo, 'tag', 'v1.1.0')
    code, picked = pick(tagged_repo, tmp_path)
    assert code == 0 and picked['base'] == git(tagged_repo, 'rev-list', '-n', '1', 'v1.0.0')


def test_base_equal_to_candidate_is_refused(tagged_repo, tmp_path):
    code, picked = pick(tagged_repo, tmp_path, base=git(tagged_repo, 'rev-parse', 'HEAD'))
    assert code != 0 and 'base' not in picked


def test_explicit_base_is_used_as_given(tagged_repo, tmp_path):
    first = git(tagged_repo, 'rev-list', '--max-parents=0', 'HEAD')
    code, picked = pick(tagged_repo, tmp_path, base=first)
    assert code == 0 and picked['base'] == first


@pytest.mark.parametrize('bad', ['main', 'a' * 39, 'a' * 40 + '; command', 'f' * 40])
def test_non_full_or_unknown_sha_is_refused(tagged_repo, tmp_path, bad):
    code, picked = pick(tagged_repo, tmp_path, base=bad)
    assert code != 0 and 'base' not in picked


def test_checkout_must_be_on_the_candidate(tagged_repo, tmp_path):
    previous = git(tagged_repo, 'rev-parse', 'HEAD~1')
    code, picked = pick(tagged_repo, tmp_path, candidate=previous)
    assert code != 0 and picked == {}


def test_real_gate_reports_no_lease_without_inherited_lock(tmp_path):
    """Без унаследованного fd настоящей блокировки пара не стартует: переменной окружения мало."""
    lock = tmp_path / 'slot.lock'
    lock.write_text('')
    assert gate.inherited_slot(lock, environment={}) is None
    other = tmp_path / 'other'
    other.write_text('')
    with other.open() as handle:
        assert gate.inherited_slot(lock, environment={'AI_OPS_HOST_SLOT_FD': str(handle.fileno())}) is None
    with lock.open() as handle:
        assert gate.inherited_slot(lock, environment={'AI_OPS_HOST_SLOT_FD': str(handle.fileno())}) == handle.fileno()
