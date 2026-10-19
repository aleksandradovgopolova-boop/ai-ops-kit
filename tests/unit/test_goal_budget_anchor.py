"""One durable counter binds original goal; execution snapshots remain separately frozen."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.engine import parallel_live_dispatch as dsp
from ai_ops_kit.lifecycle import active_work as aw, work_claims as claims
from ai_ops_kit.shared.budget import Budget, BudgetExceeded
from test_budget_reservations import _runtime
from test_parallel_package_admission import _automatic, _commit


def _claim(root):
    _, auto = _automatic(root)
    admission = dict(auto['admission'], attempt_id='initial-goal')
    _register(root, admission)
    return admission


def _register(root, admission):
    assert aw.register(aw.shared_registry_path(root), 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'],
        admission['identity'], child_root=root, admission=admission) == 0


def _bind(root, admission, budget=None):
    budget = budget or Budget(max_model_calls=30)
    path = claims.bind_attempt_budget(root, 'work', admission, budget,
                                     lambda: dsp._retry_guard(root, 'work', admission))
    return budget, path


def _next(root, admission, *, inputs=None):
    assert aw.finish_cmd(aw.shared_registry_path(root), 'work', child_root=root,
                         expected_admission=admission) == 0
    new = dict(admission, attempt_id='next-goal-generation', inputs=inputs or copy.deepcopy(admission['inputs']))
    _register(root, new)
    return new


def test_new_runtime_uses_goal_anchor_and_partial_retry_preserves_counter(tmp_path, monkeypatch):
    signals, auto, original, path = _runtime(tmp_path, monkeypatch, partial=True)
    record = json.loads(path.read_text());binding = record['binding']
    assert binding['kind'] == 'GoalBudgetBinding' and record['model_calls'] == 2
    expected = {'.ai-ops.yaml', *[f'features/work/{n}.yaml' for n in ('workitem', 'run-plan', 'run-settings')]}
    assert set(binding['inputs']) == expected and 'work-graph.yaml' not in binding['inputs']
    calls = []
    def callback(*args, **options):
        options['budget'].charge_call();calls.append(options['feature']);return _commit(*args, **options)
    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
        run_fn=callback, **dict(auto, budget=Budget.from_dict(auto['budget'].limits())))
    assert result['proceed'] and calls == ['bb'] and result['budget']['model_calls'] == 3
    assert json.loads(path.read_text())['binding'] == binding
    assert aw.load(aw.shared_registry_path(tmp_path))['active'][0]['budget_binding'] == binding
    assert original['budget']['model_calls'] == 2


def test_adding_generated_frozen_inputs_at_admission_boundary_cannot_reset_spend(tmp_path):
    admission = _claim(tmp_path)
    budget, path = _bind(tmp_path, admission);budget.charge_call()
    binding = json.loads(path.read_text())['binding']
    generated = tmp_path / 'features/new-package/generated-plan.yaml'
    generated.parent.mkdir();generated.write_text('schema_version: 1\nkind: controlled-generated-plan\n')
    inputs = dict(admission['inputs'], **{str(generated.relative_to(tmp_path)): hashlib.sha256(generated.read_bytes()).hexdigest()})
    new = _next(tmp_path, admission, inputs=inputs)
    assert aw.load(aw.shared_registry_path(tmp_path))['active'][0]['budget_binding'] == binding
    rebound, _ = _bind(tmp_path, new)
    assert rebound.model_calls == 1 and rebound.remaining_calls() == 29
    rebound.charge_call()
    assert json.loads(path.read_text())['model_calls'] == 2 and json.loads(path.read_text())['binding'] == binding


@pytest.mark.parametrize('name', ['.ai-ops.yaml', 'features/work/workitem.yaml',
    'features/work/run-plan.yaml', 'features/work/run-settings.yaml'])
def test_original_goal_or_constraints_drift_cannot_become_a_fresh_budget(tmp_path, name):
    admission = _claim(tmp_path);budget, path = _bind(tmp_path, admission);budget.charge_call()
    changed = tmp_path / name;changed.write_bytes(changed.read_bytes() + b'\n# changed original constraint\n')
    inputs = dict(admission['inputs']);inputs[name] = hashlib.sha256(changed.read_bytes()).hexdigest()
    new = _next(tmp_path, admission, inputs=inputs)
    before = path.read_bytes()
    with pytest.raises(BudgetExceeded, match='original goal/constraints'):
        _bind(tmp_path, new)
    assert path.read_bytes() == before


@pytest.mark.parametrize('damage', ['missing', 'empty', 'bool-version', 'wrong-hash', 'extra'])
def test_missing_or_corrupt_anchor_metadata_never_migrates_or_refunds_ledger(tmp_path, damage):
    admission = _claim(tmp_path);budget, path = _bind(tmp_path, admission);budget.charge_call()
    registry = aw.shared_registry_path(tmp_path);data = aw.load(registry);entry = data['active'][0]
    if damage == 'missing':entry.pop('budget_binding')
    elif damage == 'empty':entry['budget_binding'] = {}
    elif damage == 'bool-version':entry['budget_binding']['schema_version'] = True
    elif damage == 'wrong-hash':entry['budget_binding']['inputs']['.ai-ops.yaml'] = '0' * 64
    else:entry['budget_binding']['extra'] = 'unsupported'
    aw.save(registry, data);before = path.read_bytes()
    with pytest.raises(BudgetExceeded):_bind(tmp_path, admission)
    assert path.read_bytes() == before


@pytest.mark.parametrize('spent,origin', [(0, 'fresh'), (1, 'durable')])
def test_existing_legacy_full_snapshot_ledger_keeps_exact_binding_without_migration(tmp_path, spent, origin):
    admission = _claim(tmp_path)
    path = aw.shared_registry_path(tmp_path).parent / 'budgets' / (hashlib.sha256(b'work').hexdigest() + '.json')
    legacy = {'workitem_id': 'work', 'base_sha': admission['base_sha'], 'inputs': admission['inputs']}
    old = Budget(max_model_calls=30)
    old.bind_durable(path, legacy, create=True, guard=lambda: dsp._retry_guard(tmp_path, 'work', admission))
    for _ in range(spent):old.charge_call()
    registry = aw.shared_registry_path(tmp_path);data = aw.load(registry)
    data['active'][0]['budget_origin'] = origin;data['active'][0].pop('budget_binding', None);aw.save(registry, data)
    before = path.read_bytes();rebound, _ = _bind(tmp_path, admission)
    assert rebound.model_calls == spent and path.read_bytes() == before
    assert aw.load(registry)['active'][0].get('budget_binding') is None


def test_durable_anchor_without_ledger_is_not_recreated(tmp_path):
    admission = _claim(tmp_path);budget, path = _bind(tmp_path, admission);budget.charge_call();path.unlink()
    with pytest.raises(BudgetExceeded, match='missing'):_bind(tmp_path, admission)
    assert not path.exists()


@pytest.mark.parametrize('uncertain', [False, True])
def test_anchor_pin_failure_never_reaches_ledger_or_callback(tmp_path, monkeypatch, uncertain):
    admission = _claim(tmp_path);registry = aw.shared_registry_path(tmp_path)
    save = aw.save
    def fail(path, data):
        if data['active'][0].get('budget_binding'):
            if uncertain:save(path, data)
            raise aw.ActiveWorkCorrupt('controlled anchor metadata write not confirmed')
        return save(path, data)
    with monkeypatch.context() as patch:
        patch.setattr(aw, 'save', fail)
        with pytest.raises(aw.ActiveWorkCorrupt):_bind(tmp_path, admission)
    assert not list((registry.parent / 'budgets').glob('*.json'))
    # No reservation/callback could run; retrying the pin adopts persisted metadata if needed.
    rebound, path = _bind(tmp_path, admission)
    assert rebound.model_calls == 0 and json.loads(path.read_text())['model_calls'] == 0


def test_stable_goal_anchor_does_not_weaken_full_runtime_execution_snapshot(tmp_path, monkeypatch):
    signals, auto, original, path = _runtime(tmp_path, monkeypatch, partial=True)
    changed = tmp_path / 'features/aa/run-settings.yaml';changed.write_text(changed.read_text() + '\n# new generated snapshot\n')
    fresh = cmd._automatic_roots(tmp_path, 'work', signals, None, session_identity=auto['admission']['identity'])
    signals['_auto_package_signals'] = fresh.pop('package_signals')
    calls, before = [], path.read_bytes()
    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
        run_fn=lambda *a, **k: calls.append('model'), **fresh)
    assert not result['proceed'] and dsp.exit_code(result) == 2 and calls == []
    assert path.read_bytes() == before and original['budget']['model_calls'] == 2
