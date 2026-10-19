"""Durable logical admission: crashes/attempts/processes cannot recreate free slots."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.shared import lifecycle_store, gitio
from ai_ops_kit.shared.budget import Budget, BudgetExceeded
from ai_ops_kit.engine import parallel_live_dispatch as dsp
from ai_ops_kit.lifecycle import active_work as aw
from test_parallel_package_admission import _automatic, _aggregate, _commit
from test_parallel_claim_fencing import _passed

ROOT = Path(__file__).resolve().parents[2]
BINDING = {'workitem_id': 'work', 'base_sha': 'a' * 40, 'inputs': {'plan': 'b' * 64}}


def _bound(path, cap=3, *, create=False):
    budget = Budget(max_model_calls=cap)
    budget.bind_durable(path, BINDING, create=create)
    return budget


def _child(code, *args):
    return subprocess.run([sys.executable, '-c', code, *map(str, args)], cwd=ROOT,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT / 'tests/unit')},
        text=True, capture_output=True, timeout=30)


def test_charge_survives_process_exit_before_callback_without_refund(tmp_path):
    path = tmp_path / 'budget.json'
    _bound(path, cap=1, create=True)
    code = """import json,os,sys
from ai_ops_kit.shared.budget import Budget
b=Budget(max_model_calls=1);b.bind_durable(sys.argv[1],json.loads(sys.argv[2]));b.charge_call();os._exit(9)
"""
    result = _child(code, path, json.dumps(BINDING))
    assert result.returncode == 9, result.stderr
    recovered = _bound(path, cap=1)
    assert recovered.to_dict()['model_calls'] == 1 and recovered.remaining_calls() == 0
    assert recovered.to_dict()['cost'] is None and not recovered.to_dict()['cost_complete']
    with pytest.raises(BudgetExceeded):
        recovered.charge_call()


def test_concurrent_processes_reserve_at_most_shared_cap(tmp_path):
    path = tmp_path / 'budget.json'
    original = _bound(path, create=True)
    code = """import json,sys
from ai_ops_kit.shared.budget import Budget,BudgetExceeded
b=Budget(max_model_calls=3);b.bind_durable(sys.argv[1],json.loads(sys.argv[2]));called=0
for _ in range(3):
 try:b.charge_call()
 except BudgetExceeded:continue
 called+=1
print(called)
"""
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    processes = [subprocess.Popen([sys.executable, '-c', code, str(path), json.dumps(BINDING)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    counts = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        counts.append(int(stdout))
    assert sum(counts) == 3
    assert original.to_dict()['model_calls'] == 3 and original.remaining_calls() == 0


@pytest.mark.parametrize('uncertain', [False, True])
def test_write_failure_never_enters_callback_and_never_refunds_unknown_commit(tmp_path, monkeypatch, uncertain):
    path = tmp_path / 'budget.json'
    budget = _bound(path, cap=1, create=True)
    write, callbacks = lifecycle_store.durable_write_json, []
    def fail(*args, **kwargs):
        if uncertain:
            assert write(*args, **kwargs)['ok']
        return {'ok': False, 'error': 'controlled readback failure'}
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, 'durable_write_json', fail)
        with pytest.raises(BudgetExceeded):
            budget.charge_call()
            callbacks.append('provider')
    assert callbacks == []
    recovered = _bound(path, cap=1)
    assert recovered.to_dict()['model_calls'] == int(uncertain)
    if uncertain:
        with pytest.raises(BudgetExceeded):
            recovered.charge_call()


@pytest.mark.parametrize('damage', ['empty', 'broken', 'negative', 'bool', 'unknown-over-count', 'binding', 'limit', 'nan'])
def test_corrupt_or_different_ledger_never_resets_to_fresh(tmp_path, damage):
    path = tmp_path / 'budget.json'
    _bound(path, create=True).charge_call()
    value = json.loads(path.read_text())
    if damage in ('empty', 'broken'):
        path.write_text('' if damage == 'empty' else '{broken')
    else:
        if damage == 'negative':value['model_calls'] = -1
        elif damage == 'bool':value['model_calls'] = True
        elif damage == 'unknown-over-count':value['unknown_cost_calls'] = 2
        elif damage == 'binding':value['binding']['base_sha'] = 'c' * 40
        elif damage == 'limit':value['limits']['max_model_calls'] = 4
        else:value['known_cost_lower_bound'] = float('nan')
        path.write_text(json.dumps(value))
    before = path.read_bytes()
    with pytest.raises(BudgetExceeded):
        _bound(path, create=True)
    assert path.read_bytes() == before


def test_missing_existing_ledger_is_not_recreated_by_read_or_charge(tmp_path):
    path = tmp_path / 'budget.json'
    budget = _bound(path, create=True)
    budget.charge_call()
    path.unlink()
    for operation in (budget.charge_call, budget.to_dict, budget.remaining_calls, lambda: _bound(path)):
        with pytest.raises(BudgetExceeded):
            operation()
        assert not path.exists()


@pytest.mark.parametrize('link', ['ledger', 'lock', 'directory'])
def test_symlinks_are_refused_without_changing_target(tmp_path, link):
    target = tmp_path / 'target.json'
    _bound(target, create=True).charge_call()
    before = target.read_bytes()
    path = tmp_path / 'budget.json'
    if link == 'ledger':path.symlink_to(target)
    elif link == 'lock':path.with_suffix('.json.lock').symlink_to(target)
    else:
        (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
        path = tmp_path / 'alias/budget.json'
    with pytest.raises(BudgetExceeded):
        _bound(path, create=True)
    assert target.read_bytes() == before


def test_unbound_prior_expenditure_cannot_be_migrated_to_zero(tmp_path):
    budget = Budget(max_model_calls=3)
    budget.charge_call()
    path = tmp_path / 'budget.json'
    with pytest.raises(BudgetExceeded):
        budget.bind_durable(path, BINDING, create=True)
    assert budget.model_calls == 1 and not path.exists()


def _runtime(root, monkeypatch, *, cap=3, partial=False):
    signals, auto = _automatic(root)
    # Saved declared budgets are part of the frozen plan: change them prospectively before admission.
    if cap != 30:
        import yaml
        for pid in ('work', 'aa', 'bb'):
            for name in ('workitem.yaml', 'run-settings.yaml', 'run-plan.yaml'):
                path = root / 'features' / pid / name
                data = yaml.safe_load(path.read_text())
                if 'signals' in data:data['signals']['execution_budget'] = {'max_model_calls': cap}
                if name == 'run-plan.yaml':data['execution_budget'] = {'max_model_calls': cap}
                path.write_text(yaml.safe_dump(data))
        signals['execution_budget'] = {'max_model_calls': cap}
        assert gitio.git(root, 'add', '.')[0] == 0
        assert gitio.git(root, 'commit', '-qm', 'bounded shared budget')[0] == 0
        from ai_ops_kit.cli import ai_ops_cli_commands as cmd
        auto = cmd._automatic_roots(root, 'work', signals, None)
        signals['_auto_package_signals'] = auto.pop('package_signals')
    _aggregate(monkeypatch)
    calls = []
    def callback(*args, **kwargs):
        kwargs['budget'].charge_call()
        calls.append(kwargs['feature'])
        result = _commit(*args, **kwargs)
        if partial and kwargs['feature'] == 'bb':
            result['ready_for_pr'] = False
        return result
    report = dsp.run_parallel_live('write work', signals, root, feature='work', provider='mock', run_fn=callback, **auto)
    assert report['proceed'] is not partial and sorted(calls) == ['aa', 'bb']
    path = aw.shared_registry_path(root).parent / 'budgets' / (hashlib.sha256(b'work').hexdigest() + '.json')
    assert json.loads(path.read_text())['model_calls'] == 2
    return signals, auto, report, path


def test_real_automatic_attempt_in_fresh_process_spends_only_remaining_slot(tmp_path, monkeypatch):
    signals, auto, original, path = _runtime(tmp_path, monkeypatch, partial=True)
    code = """import contextlib,io,json,sys
from pathlib import Path
from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.engine import parallel_live_dispatch as dsp
from test_parallel_package_admission import _aggregate,_commit
from ai_ops_kit.gates import evidence_collector
from ai_ops_kit.shared import gitio
root=Path(sys.argv[1]);signals=json.loads(sys.argv[2]);auto=cmd._automatic_roots(root,'work',signals,None,session_identity=sys.argv[3])
signals['_auto_package_signals']=auto.pop('package_signals');calls=[]
evidence_collector.collect=lambda *a,**k:{'gate_evidence':{'implementation_verification':{'status':'pass'}},'checks':{},'revision':gitio.git(a[1],'rev-parse','HEAD')[1]}
def callback(*args,**kwargs):
 kwargs['budget'].charge_call();calls.append(kwargs['feature']);return _commit(*args,**kwargs)
with contextlib.redirect_stdout(io.StringIO()):
 report=dsp.run_parallel_live('write work',signals,root,feature='work',provider='mock',run_fn=callback,**auto)
print(json.dumps({'calls':calls,'proceed':report['proceed'],'budget':report['budget']}))
"""
    result = _child(code, tmp_path, json.dumps({k: v for k, v in signals.items() if k != '_auto_package_signals'}), auto['admission']['identity'])
    assert result.returncode == 0, result.stderr
    recovered = json.loads(result.stdout)
    assert recovered['calls'] == ['bb'] and recovered['proceed']
    assert recovered['budget']['model_calls'] == 3 and recovered['budget']['remaining_calls'] == 0
    assert recovered['budget']['cost'] is None and not recovered['budget']['cost_complete']
    assert json.loads(path.read_text())['model_calls'] == 3
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == original['base_binding']['base_sha']


@pytest.mark.parametrize('damage', ['missing-ledger', 'legacy-claim'])
def test_new_automatic_attempt_refuses_missing_or_legacy_spend_before_clones(tmp_path, monkeypatch, damage):
    signals, auto, original, path = _runtime(tmp_path, monkeypatch, partial=True)
    if damage == 'missing-ledger':path.unlink()
    else:
        data = aw.load(aw.shared_registry_path(tmp_path));data['active'][0].pop('budget_origin')
        aw.save(aw.shared_registry_path(tmp_path), data)
    fresh = dict(auto, budget=Budget.from_dict(auto['budget'].limits()))
    calls = []
    report = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
                                   run_fn=lambda *a, **k: calls.append('model'), **fresh)
    assert calls == [] and dsp.exit_code(report) == 2 and 'budget' in report['reason']
    if damage == 'missing-ledger':assert not path.exists()


def test_takeover_between_callback_admission_and_charge_refuses_reservation(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path)
    expected, calls = {}, []
    def dispatch(wg, root, base, tasks, sig, callback, **options):
        registry = aw.shared_registry_path(tmp_path)
        assert aw.register(registry, 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'], 'rescue', child_root=tmp_path,
                           takeover=True, takeover_reason='explicit recovery') == 0
        expected[registry] = registry.read_bytes()
        with pytest.raises(BudgetExceeded):
            options['run_options']['budget'].charge_call()
            calls.append('model')
        return _passed(tmp_path)
    report = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock', runner=dispatch,
                                   run_fn=lambda *a, **k: calls.append('model'), **auto)
    assert dsp.exit_code(report) == 2 and calls == []
    assert all(p.read_bytes() == value for p, value in expected.items())
    path = aw.shared_registry_path(tmp_path).parent / 'budgets' / (hashlib.sha256(b'work').hexdigest() + '.json')
    assert json.loads(path.read_text())['model_calls'] == 0


@pytest.mark.parametrize('cap', [2, 4])
def test_changed_limit_cannot_rebind_existing_job_or_refund_spend(tmp_path, cap):
    path = tmp_path / 'budget.json'
    _bound(path, create=True).charge_call()
    before = path.read_bytes()
    with pytest.raises(BudgetExceeded):
        _bound(path, cap=cap, create=True)
    assert path.read_bytes() == before


def test_new_base_binding_does_not_silently_start_fresh_budget(tmp_path, monkeypatch):
    signals, auto, original, path = _runtime(tmp_path, monkeypatch, partial=True)
    (tmp_path / 'new-base.txt').write_text('new base\n')
    assert gitio.git(tmp_path, 'add', 'new-base.txt')[0] == 0
    assert gitio.git(tmp_path, 'commit', '-qm', 'new base')[0] == 0
    from ai_ops_kit.cli import ai_ops_cli_commands as cmd
    fresh = cmd._automatic_roots(tmp_path, 'work', signals, None)
    signals['_auto_package_signals'] = fresh.pop('package_signals')
    before, calls = path.read_bytes(), []
    report = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
                                   run_fn=lambda *a, **k: calls.append('model'), **fresh)
    assert calls == [] and dsp.exit_code(report) == 2 and 'resume' in report['reason']
    assert path.read_bytes() == before


@pytest.mark.parametrize('quote', [0, 0.5])
def test_durable_logical_only_mode_does_not_turn_quote_into_actual_cost(tmp_path, quote):
    path = tmp_path / 'budget.json'
    budget = _bound(path, create=True)
    before = path.read_bytes()
    with pytest.raises(BudgetExceeded):
        budget.charge_call(cost=quote)
    assert path.read_bytes() == before and budget.model_calls == 0
