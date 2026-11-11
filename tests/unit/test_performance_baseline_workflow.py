"""Ручной CI wrapper: fixture-проверки wiring, не performance/Actions evidence."""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import bench_performance as bench
from ai_ops_kit.devtools import host_resource_cli as gate

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/performance-baseline.yml'


def workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def pair_code():
    run = next(s['run'] for s in workflow()['jobs']['bounded-pair']['steps']
               if s.get('name') == 'Одна штатная lease на base и repeat')
    return run.split("python3 - <<'PY'\n", 1)[1].split('\nPY', 1)[0]


def test_workflow_is_manual_read_only_and_actions_are_pinned():
    config = workflow()
    assert set(config['on']) == {'workflow_dispatch'}
    assert config['permissions'] == {'contents': 'read'}
    assert config['concurrency']['cancel-in-progress'] == 'false'
    for step in config['jobs']['bounded-pair']['steps']:
        if 'uses' in step:
            assert len(step['uses'].split('@')[1]) == 40
    assert 'source_sha' in config['on']['workflow_dispatch']['inputs']


def test_run_blocks_parse_as_bash_and_embedded_python():
    blocks = []
    for step in workflow()['jobs']['bounded-pair']['steps']:
        run = step.get('run', '')
        if run:
            subprocess.run(['bash', '-n'], input=run, text=True, check=True)
        if "python3 - <<'PY'\n" in run:
            code = run.split("python3 - <<'PY'\n", 1)[1].split('\nPY', 1)[0]
            ast.parse(code)
            blocks.append(code)
    assert len(blocks) == 2


def run_fixture(tmp_path, monkeypatch, case):
    """Исполняет настоящий inline wrapper, заменяя только runner/benchmark эффекты."""
    out = tmp_path / 'output'
    original_read = Path.read_text
    swaps = iter(['pswpin 0\npswpout 0\n',
                  'pswpin 1\npswpout 0\n' if case == 'swap' else 'pswpin 0\npswpout 0\n'])
    boots = iter(['boot-a', 'boot-b' if case == 'reboot' else 'boot-a'])
    source_calls = []
    calls = []

    def read(path, *args, **kwargs):
        if str(path) == '/proc/vmstat':
            return next(swaps)
        if str(path) == '/proc/sys/kernel/random/boot_id':
            return next(boots)
        return original_read(path, *args, **kwargs)

    def git(argv, **kwargs):
        if argv[1:] == ['rev-parse', 'HEAD']:
            source_calls.append(True)
            return ('b' if (case == 'source_changed' and len(source_calls) > 1 or case == 'wrong_source') else 'a') * 40
        assert argv[1:] == ['status', '--porcelain']
        return ' M source.py' if case == 'dirty' else ''

    def execute(args):
        calls.append(args)
        target = Path(args[args.index('--output') + 1])
        target.write_text('executed')
        if '--baseline' in args and case == 'base_changed':
            Path(args[args.index('--baseline') + 1]).write_text('mutated')
        return 7 if case == 'base_exit' or case == 'repeat_exit' and '--baseline' in args else 0

    monkeypatch.setenv('OUT', str(out))
    monkeypatch.setenv('SOURCE_SHA', 'a' * 40)
    monkeypatch.setenv('GITHUB_ACTIONS', 'false' if case == 'not_actions' else 'true')
    monkeypatch.setattr(Path, 'read_text', read)
    monkeypatch.setattr(subprocess, 'check_output', git)
    monkeypatch.setattr(gate, 'inherited_slot', lambda: None if case == 'lease_lost' else 123)
    monkeypatch.setattr(bench, 'run_suite', None if case == 'missing_harness' else lambda: None, raising=False)
    monkeypatch.setattr(bench, 'main', execute)
    # Main ещё без harness/suite; проверяем зависимость явно и отдельно от runner effects.
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda p: case != 'missing_suite' if str(p).endswith('/suite.json') else original_is_file(p))
    with pytest.raises(SystemExit) as exc:
        exec(compile(pair_code(), str(WORKFLOW), 'exec'), {})  # noqa: S102 — собственный checked-in workflow под fixture mocks
    return out, calls, exc.value.code


def test_pair_really_writes_outputs_before_candidate_guard(tmp_path, monkeypatch):
    out, calls, code = run_fixture(tmp_path, monkeypatch, 'positive')
    assert len(calls) == 2
    assert (out / 'base.json').read_text() == (out / 'repeat.json').read_text() == 'executed'
    data = json.loads((out / 'window.json').read_text())
    assert code == 0 and data['qualification'] == 'CANDIDATE'
    assert data['base_sha256_before_repeat'] == data['base_sha256_after_repeat']
    assert '--regression-threshold' in calls[1] and calls[1][-3:] == ['1.2', '--output', str(out / 'repeat.json')]


@pytest.mark.parametrize('case', ['swap', 'reboot', 'source_changed', 'base_changed', 'base_exit', 'repeat_exit'])
def test_pair_rejects_invalid_window_after_actual_fixture_effect(tmp_path, monkeypatch, case):
    out, calls, code = run_fixture(tmp_path, monkeypatch, case)
    assert calls and (out / 'base.json').is_file()
    data = json.loads((out / 'window.json').read_text())
    if case == 'base_changed':
        assert (out / 'base.json').read_text() == 'mutated'
        assert data['base_sha256_before_repeat'] != data['base_sha256_after_repeat']
    if case == 'swap':
        assert data['after']['pswpin'] > data['before']['pswpin']
    assert code == 2
    assert data['qualification'] == 'REJECTED'


@pytest.mark.parametrize('case', ['dirty', 'lease_lost', 'not_actions', 'missing_harness', 'missing_suite', 'wrong_source'])
def test_pair_refuses_before_any_benchmark_effect(tmp_path, monkeypatch, case):
    out, calls, code = run_fixture(tmp_path, monkeypatch, case)
    assert code != 0 and not calls
    assert not (out / 'base.json').exists() and not (out / 'repeat.json').exists()


@pytest.mark.parametrize('sha', ['main', 'a' * 39, 'a' * 40 + '; command'])
def test_input_guard_refuses_non_full_sha(monkeypatch, sha):
    run = workflow()['jobs']['bounded-pair']['steps'][0]['run']
    code = run.split("python3 - <<'PY'\n", 1)[1].split('\nPY', 1)[0]
    monkeypatch.setenv('SOURCE_SHA', sha)
    with pytest.raises(SystemExit):
        exec(compile(code, str(WORKFLOW), 'exec'), {})  # noqa: S102 — собственный checked-in guard


def test_real_gate_reports_no_lease_without_inherited_lock(tmp_path):
    """Workflow отказывает при потере lease; настоящая функция без унаследованного fd отвечает «нет».

    Остальные сценарии подменяют `inherited_slot`. Здесь зовётся настоящая: одной переменной окружения
    недостаточно, и fd чужого файла не засчитывается за блокировку.
    """
    lock = tmp_path / 'slot.lock'
    lock.write_text('')
    assert gate.inherited_slot(lock, environment={}) is None
    other = tmp_path / 'other'
    other.write_text('')
    with other.open() as handle:
        assert gate.inherited_slot(lock, environment={'AI_OPS_HOST_SLOT_FD': str(handle.fileno())}) is None
    with lock.open() as handle:
        assert gate.inherited_slot(lock, environment={'AI_OPS_HOST_SLOT_FD': str(handle.fileno())}) == handle.fileno()
