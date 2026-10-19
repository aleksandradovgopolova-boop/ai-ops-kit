"""Goal-scoped executable plan admission; real Git, no provider/network calls."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.engine import parallel_live_dispatch as dsp, run_plan
from ai_ops_kit.lifecycle import active_work as aw, workitem
from ai_ops_kit.shared import gitio
from test_parallel_live_dispatch import _saved_auto
from test_parallel_package_admission import _aggregate, _commit
from test_parallel_claim_fencing import _passed


def _scoped(root):
    signals, wg = _saved_auto(root)
    graph = root / 'features/work/work-graph.yaml'
    (root / 'work-graph.yaml').rename(graph)
    return signals, wg, graph


def test_scoped_plan_reaches_real_automatic_runtime_and_preserves_provenance(tmp_path, monkeypatch):
    signals, wg, graph = _scoped(tmp_path)
    auto = cmd._automatic_roots(tmp_path, 'work', signals, None)
    admission = auto['admission']
    assert admission['graph_path'] == 'features/work/work-graph.yaml'
    assert admission['inputs'][admission['graph_path']] == hashlib.sha256(graph.read_bytes()).hexdigest()
    assert auto['work_graph'] == wg and not (tmp_path / 'work-graph.yaml').exists()
    _aggregate(monkeypatch)
    sig = dict(signals, _auto_package_signals=auto.pop('package_signals'))
    starts = []
    def callback(*args, **kwargs):
        starts.append(kwargs['feature'])
        kwargs['budget'].charge_call()
        return _commit(*args, **kwargs)
    rep = dsp.run_parallel_live('write work', sig, tmp_path, feature='work', provider='mock',
        run_fn=callback, **auto)
    assert sorted(starts) == ['aa', 'bb'] and rep['proceed']
    assert rep['aggregate']['tested_revision'] == rep['integration_sha']
    entry = aw.load(aw.shared_registry_path(tmp_path))['active'][0]
    assert entry['auto_admission']['inputs'] == admission['inputs']
    assert entry['budget_binding']['kind'] == 'GoalBudgetBinding'
    assert rep['budget']['model_calls'] == 2
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == admission['base_sha']


def test_two_goals_in_same_store_bind_only_their_own_versioned_plan(tmp_path):
    signals, wg, graph = _scoped(tmp_path)
    workitem.start(tmp_path / 'features', 'other', 'write other', signals=signals)
    other = tmp_path / 'features/other'
    (other / 'run-plan.yaml').write_text(yaml.safe_dump(run_plan.build_plan(dict(signals, task_text='write other'), 'other')))
    (other / 'run-settings.yaml').write_text(yaml.safe_dump(dict(kind='run-settings', workitem_id='other', signals=signals, policy={})))
    second = copy.deepcopy(wg)
    second['feature'], second['id'] = 'other', 'WG-002'
    (other / 'work-graph.yaml').write_text(yaml.safe_dump(second))
    one = cmd._automatic_roots(tmp_path, 'work', signals, None)
    two = cmd._automatic_roots(tmp_path, 'other', signals, None)
    assert one['work_graph']['feature'] == 'work' and two['work_graph']['feature'] == 'other'
    assert one['admission']['base_sha'] == two['admission']['base_sha']
    assert 'features/other/work-graph.yaml' not in one['admission']['inputs']
    assert str(graph.relative_to(tmp_path)) not in two['admission']['inputs']
    # This proves storage/admission isolation, not concurrent execution of overlapping scopes.


@pytest.mark.parametrize('legacy', ['work-graph.yaml', '.ai/runtime/work-graph.yaml'])
def test_legacy_plan_location_compatible_but_duplicate_never_wins_by_priority(tmp_path, legacy):
    signals, _, graph = _scoped(tmp_path)
    destination = tmp_path / legacy
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(graph.read_bytes())
    with pytest.raises(ValueError, match='ambiguous'):
        cmd._automatic_roots(tmp_path, 'work', signals, None)
    graph.unlink()
    assert cmd._automatic_roots(tmp_path, 'work', signals, None)['admission']['graph_path'] == legacy


@pytest.mark.parametrize('damage', ['wrong-goal', 'symlink', 'dangling', 'directory', 'parent-alias', 'parent-dangling'])
def test_unsafe_scoped_plan_refuses_without_single_path_fallback(tmp_path, damage):
    signals, wg, graph = _scoped(tmp_path)
    if damage == 'wrong-goal':
        wg['feature'] = 'foreign'
        graph.write_text(yaml.safe_dump(wg))
    elif damage in ('symlink', 'dangling'):
        target = tmp_path / 'plan-copy.yaml'
        if damage == 'symlink':target.write_bytes(graph.read_bytes())
        graph.unlink();graph.symlink_to(target)
    elif damage == 'directory':
        graph.unlink();graph.mkdir()
    else:
        directory = graph.parent
        target = tmp_path / 'saved-work'
        directory.rename(target)
        directory.symlink_to(target if damage == 'parent-alias' else tmp_path / 'missing-work')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*.yaml') if p.is_file()}
    with pytest.raises(ValueError):
        cmd._automatic_roots(tmp_path, 'work', signals, None)
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*.yaml') if p.is_file()} == before
    assert not (tmp_path / 'features/work/parallel-report.json').exists()


@pytest.mark.parametrize('wid', ['../outside', '/outside', '..', '', None])
def test_goal_identity_validated_before_feature_path_lookup(tmp_path, wid):
    signals, _, graph = _scoped(tmp_path)
    graph.unlink()
    with pytest.raises(ValueError, match='unsafe goal identity'):
        cmd._automatic_roots(tmp_path, wid, signals, None)


@pytest.mark.parametrize('damage', ['bytes', 'parent-alias'])
def test_selected_plan_drift_blocks_actual_callback_before_model_boundary(tmp_path, damage):
    signals, _, graph = _scoped(tmp_path)
    auto = cmd._automatic_roots(tmp_path, 'work', signals, None)
    sig = dict(signals, _auto_package_signals=auto.pop('package_signals'))
    calls = []
    def dispatcher(wg, root, base, tasks, signals, callback, **kwargs):
        if damage == 'bytes':graph.write_bytes(graph.read_bytes() + b'\n# replaced plan\n')
        else:
            target = tmp_path / 'aliased-work'
            graph.parent.rename(target)
            graph.parent.symlink_to(target)
        callback('write aa', signals, root, feature='aa')
        return _passed(tmp_path)
    rep = dsp.run_parallel_live('write work', sig, tmp_path, feature='work', provider='mock',
        runner=dispatcher, run_fn=lambda *a, **k: calls.append('model'), **auto)
    assert calls == [] and not rep['proceed'] and dsp.exit_code(rep) == 2
    assert 'saved input' in rep['reason']
    # Canonical ledger is outside mutable/symlinked goal artifacts; no reservation happened.
    ledgers = list((aw.shared_registry_path(tmp_path).parent / 'budgets').glob('*.json'))
    assert ledgers and all(json.loads(p.read_text())['model_calls'] == 0 for p in ledgers)
