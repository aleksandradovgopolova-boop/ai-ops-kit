"""Own process died after durable completed report but before claim finalization."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.delivery import pr_open
from ai_ops_kit.engine import parallel_live_dispatch as dsp, execution_pipeline
from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.shared import gitio
from test_parallel_package_admission import _aggregate, _commit

ROOT = Path(__file__).resolve().parents[2]
SESSION = 'session:controlled-checkpoint-recovery'
CHILD = """import os,sys
from pathlib import Path
from ai_ops_kit.engine import parallel_live_dispatch as dsp
from ai_ops_kit.shared import gitio
from ai_ops_kit.gates import evidence_collector
from test_parallel_package_admission import _automatic,_commit
root=Path(sys.argv[1]);signals,auto=_automatic(root);auto['admission']['identity']=sys.argv[2]
assert gitio.git(root,'remote','add','origin','https://github.com/example/child.git')[0]==0
evidence_collector.collect=lambda *a,**k:{'gate_evidence':{'implementation_verification':{'status':'pass'}},'checks':{},'revision':gitio.git(a[1],'rev-parse','HEAD')[1]}
def package(*args,**kwargs):
 kwargs['budget'].charge_call();rep=_commit(*args,**kwargs)
 if sys.argv[3]=='partial' and kwargs['feature']=='bb':rep['ready_for_pr']=False
 return rep
def crash(*args,**kwargs):os._exit(9)
dsp._finish_automatic_claim=crash
dsp.run_parallel_live('write work',signals,root,feature='work',provider='mock',run_fn=package,**auto)
"""


def _orphan(root, *, partial=True):
    child = subprocess.Popen([sys.executable, '-c', CHILD, str(root), SESSION, 'partial' if partial else 'ready'],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null', 'PYTHONDONTWRITEBYTECODE': '1',
             'PYTHONPATH': str(ROOT / 'tests/unit')})
    try:
        stdout, stderr = child.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        child.kill();stdout, stderr = child.communicate(timeout=15)
        pytest.fail(f'own controlled child timed out: {stdout[-500:]} {stderr[-500:]}')
    assert child.returncode == 9, (stdout, stderr)
    claim = aw.load(aw.shared_registry_path(root))['active'][0]
    report = json.loads((root / 'features/work/parallel-report.json').read_text())
    assert claim['status'] == 'in-progress' and claim['owner_pid'] == child.pid
    assert aw._pid_is_dead(child.pid), 'actual own child has exited and been reaped'
    assert report['automatic_attempt']['id'] == claim['auto_admission']['attempt_id']
    assert report['package_artifacts']['status'] == 'preserved' and report['budget']['model_calls'] == 2
    assert gitio.git(root, 'rev-parse', 'HEAD')[1] == report['base_binding']['base_sha']
    return report, copy.deepcopy(claim)


def _retry(root, monkeypatch, starts):
    signals = yaml.safe_load((root / 'features/work/run-settings.yaml').read_text())['signals']
    auto = cmd._automatic_roots(root, 'work', signals, None, session_identity=SESSION)
    signals['_auto_package_signals'] = auto.pop('package_signals')
    _aggregate(monkeypatch)
    def package(*args, **options):
        options['budget'].charge_call();starts.append(options['feature']);return _commit(*args, **options)
    return dsp.run_parallel_live('write work', signals, root, feature='work', provider='mock', run_fn=package, **auto)


def test_real_exit_after_completed_checkpoint_resumes_only_failed_package_without_budget_reset(tmp_path, monkeypatch):
    original, old = _orphan(tmp_path)
    calls = []
    result = _retry(tmp_path, monkeypatch, calls)
    assert result['proceed'] and calls == ['bb']
    assert result['package_results']['aa']['sha'] == original['package_results']['aa']['sha']
    assert result['budget']['model_calls'] == 3 and result['budget']['remaining_calls'] == 27
    assert result['budget']['cost'] is None
    assert result['automatic_attempt']['id'] != old['auto_admission']['attempt_id']
    assert result['owner_recovery'] == {'attempt_id': old['auto_admission']['attempt_id'],
        'owner_pid': old['owner_pid'], 'reason': 'completed-checkpoint-owner-process-gone'}
    registry = aw.shared_registry_path(tmp_path)
    current = aw.load(registry)['active'][0]
    assert current['status'] == 'done' and current['owner_pid'] == os.getpid()
    before = registry.read_bytes()
    assert aw.finish_cmd(registry, 'work', child_root=tmp_path, expected_admission=old['auto_admission']) == 1
    assert registry.read_bytes() == before, 'late old completion cannot change recovered generation'


def test_ready_orphan_delivery_only_uses_existing_controller_without_new_package_calls(tmp_path, monkeypatch):
    original, old = _orphan(tmp_path, partial=False)
    posts = []
    def post(clone, branch, **options):
        sha = gitio.git(clone, 'rev-parse', 'HEAD')[1];posts.append(sha)
        return {'status': 'opened', 'head_sha': sha, 'number': 7, 'url': 'https://github.com/example/child/pull/7'}
    monkeypatch.setattr(pr_open, 'open_draft_pr', post)
    monkeypatch.setattr(execution_pipeline, '_reverify_against_current_target', lambda *a: {'stale': False})
    monkeypatch.setattr(dsp, 'run_parallel_live', lambda *a, **k: pytest.fail('entered package path'))
    result = dsp.resume_parallel_delivery(tmp_path, 'work', session=SESSION, execute=True, open_pr=True)
    assert dsp.exit_code(result) == 0 and posts == [original['integration_sha']]
    assert result['delivery_retry']['new_package_calls'] == result['delivery_retry']['new_model_calls'] == 0
    assert result['budget'] == original['budget'] and result['delivery']['sha_verified']
    assert result['owner_recovery']['owner_pid'] == old['owner_pid']
    assert result['delivery_retry']['attempt_id'] != old['auto_admission']['attempt_id']


@pytest.mark.parametrize('damage', ['live-pid', 'missing-pid', 'bool-pid', 'string-pid', 'permission-unknown',
    'foreign-machine', 'foreign-session', 'generation', 'report-missing', 'report-corrupt', 'unknown-result'])
def test_active_orphan_without_complete_own_dead_process_proof_never_retries(tmp_path, monkeypatch, damage):
    original, old = _orphan(tmp_path)
    registry = aw.shared_registry_path(tmp_path)
    data = aw.load(registry);entry = data['active'][0]
    report = tmp_path / 'features/work/parallel-report.json'
    if damage == 'live-pid':
        entry['owner_pid'] = os.getpid();entry['started_at'] = '2000-01-01T00:00:00+00:00'
    elif damage == 'missing-pid':entry.pop('owner_pid')
    elif damage == 'bool-pid':entry['owner_pid'] = True
    elif damage == 'string-pid':entry['owner_pid'] = str(old['owner_pid'])
    elif damage == 'permission-unknown':monkeypatch.setattr(aw, '_pid_is_dead', lambda pid: False)
    elif damage == 'foreign-machine':entry['machine'] = 'another-machine'
    elif damage == 'foreign-session':entry['owner_session'] = 'session:someone-else'
    elif damage == 'generation':entry['auto_admission']['attempt_id'] = 'newer-generation'
    elif damage == 'report-missing':report.unlink()
    elif damage == 'report-corrupt':report.write_text('{broken')
    else:
        original['package_results']['bb']['status'] = 'error';report.write_text(json.dumps(original))
    aw.save(registry, data)
    before = registry.read_bytes()
    budget_path = registry.parent / 'budgets'
    budget = {str(p): p.read_bytes() for p in budget_path.glob('*.json')}
    calls = []
    result = _retry(tmp_path, monkeypatch, calls)
    assert not result['proceed'] and dsp.exit_code(result) == 2 and calls == []
    assert registry.read_bytes() == before
    assert all(Path(p).read_bytes() == raw for p, raw in budget.items())


def test_dead_ready_preflight_is_read_only_and_does_not_mint_generation(tmp_path):
    _, _ = _orphan(tmp_path, partial=False)
    registry = aw.shared_registry_path(tmp_path);before = registry.read_bytes()
    result = dsp.resume_parallel_delivery(tmp_path, 'work', session=SESSION)
    assert result['resume']['can_resume'] and not result['resume']['resumed']
    assert registry.read_bytes() == before
