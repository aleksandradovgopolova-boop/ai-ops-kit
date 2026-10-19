"""Новый callback старой automatic попытки не начинается после передачи владения."""
from __future__ import annotations

import copy
import threading

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.engine import parallel_live_dispatch as dsp, run_plan
from ai_ops_kit.lifecycle import active_work as aw, workitem
from ai_ops_kit.shared import gitio
from test_parallel_live_dispatch import _saved_auto
from test_parallel_claim_fencing import _owned_bytes, _passed


def _automatic(root, *, third=False):
    signals, wg = _saved_auto(root)
    if third:
        wg['packages'].append({'id': 'cc', 'write_scope': ['cc.txt'], 'depends_on': []})
        wg['integration_order'].append('cc')
        (root / 'work-graph.yaml').write_text(yaml.safe_dump(wg))
        workitem.start(root / 'features', 'cc', 'write cc', signals=signals)
        d = root / 'features/cc'
        (d / 'run-plan.yaml').write_text(yaml.safe_dump(run_plan.build_plan({**signals, 'task_text': 'write cc'}, 'cc')))
        (d / 'run-settings.yaml').write_text(yaml.safe_dump({'kind': 'run-settings', 'workitem_id': 'cc',
                                                           'signals': signals, 'policy': {}}))
        assert gitio.git(root, 'add', '.')[0] == 0
        assert gitio.git(root, 'commit', '-qm', 'third root')[0] == 0
    auto = cmd._automatic_roots(root, 'work', signals, None)
    return dict(signals, _auto_package_signals=auto.pop('package_signals')), auto


def _commit(task, signals, root, **options):
    pid = options['feature']
    assert gitio.git(root, 'checkout', '-q', '-B', f'ai-ops/{pid}')[0] == 0
    (root / f'{pid}.txt').write_text(f'actual package {pid}\n')
    assert gitio.git(root, 'add', f'{pid}.txt')[0] == 0
    assert gitio.git(root, 'commit', '-qm', pid)[0] == 0
    return {'ready_for_pr': True, 'commit': {'sha': gitio.git(root, 'rev-parse', 'HEAD')[1]}}


def _aggregate(monkeypatch):
    from ai_ops_kit.gates import evidence_collector
    monkeypatch.setattr(evidence_collector, 'collect', lambda *a, **k: {
        'gate_evidence': {'implementation_verification': {'status': 'pass'}}, 'checks': {},
        'revision': gitio.git(a[1], 'rev-parse', 'HEAD')[1]})


@pytest.mark.parametrize('damage', ['takeover', 'same-session-generation', 'missing', 'corrupt', 'closed', 'input-drift'])
def test_claim_or_frozen_input_change_blocks_next_package_callback(tmp_path, damage):
    signals, auto = _automatic(tmp_path)
    registry = aw.shared_registry_path(tmp_path)
    starts, expected = [], {}

    def dispatch(wg, child_root, base_sha, task_map, sig, callback, **kw):
        old = copy.deepcopy(aw.load(registry)['active'][0])
        if damage == 'takeover':
            assert aw.register(registry, 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'], 'rescue',
                               child_root=tmp_path, takeover=True, takeover_reason='explicit recovery') == 0
        elif damage == 'same-session-generation':
            assert aw.finish_cmd(registry, 'work', child_root=tmp_path) == 0
            admission = dict(old['auto_admission'], attempt_id='replacement-generation')
            assert aw.register(registry, 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'], old['owner_session'],
                               child_root=tmp_path, admission=admission) == 0
        elif damage == 'missing':
            registry.unlink()
        elif damage == 'corrupt':
            registry.write_text('active: [invalid yaml')
        elif damage == 'closed':
            assert aw.finish_cmd(registry, 'work', status='blocked', child_root=tmp_path) == 0
        else:
            p = tmp_path / 'features/aa/run-settings.yaml'
            before = p.read_bytes()
            p.write_bytes(before + b'\n# changed while waiting\n')
            assert p.read_bytes() != before
        (tmp_path / 'features/work/parallel-report.json').write_text('{"holder":"must-survive"}\n')
        expected.update(_owned_bytes(tmp_path))
        callback('write aa', sig, tmp_path, feature='aa')
        return _passed(tmp_path)

    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
                                   runner=dispatch, run_fn=lambda *a, **k: starts.append(k['feature']), **auto)
    assert starts == [], 'stale callback must never enter the package run/model boundary'
    assert result['proceed'] is False and dsp.exit_code(result) == 2
    expected_reason = 'повреждён' if damage == 'corrupt' else ('saved input' if damage == 'input-drift' else 'claim')
    assert expected_reason in result['reason']
    # Input drift retains ownership, so the existing finally legitimately closes its own claim.
    if damage != 'input-drift':
        assert _owned_bytes(tmp_path) == expected


def test_live_queued_package_after_takeover_never_enters_run_fn(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path, third=True)
    _aggregate(monkeypatch)
    registry = aw.shared_registry_path(tmp_path)
    bb_entered, replacement_ready = threading.Event(), threading.Event()
    starts, completed, expected, deliveries = [], [], {}, []

    def run(task, sig, root, **options):
        pid = options['feature']
        starts.append(pid)
        if pid == 'aa':
            assert bb_entered.wait(10), 'both initial callbacks must actually enter before takeover'
            assert aw.register(registry, 'work', 'ai-ops/work', ['aa.txt', 'bb.txt', 'cc.txt'], 'rescue',
                               child_root=tmp_path, takeover=True, takeover_reason='explicit recovery') == 0
            (tmp_path / 'features/work/parallel-report.json').write_text('{"holder":"rescue"}\n')
            expected.update(_owned_bytes(tmp_path))
            replacement_ready.set()
        elif pid == 'bb':
            bb_entered.set()
            assert replacement_ready.wait(10)
        rep = _commit(task, sig, root, **options)
        completed.append(pid)
        return rep

    monkeypatch.setattr(dsp, '_deliver_parallel', lambda *a, **k: deliveries.append(a))
    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
                                   run_fn=run, open_pr=True, **auto)
    assert sorted(starts) == ['aa', 'bb'], 'third callback is still queued when takeover occurs'
    assert sorted(completed) == ['aa', 'bb'], 'already admitted effects may finish; never pretend cancelled'
    assert result['package_results']['cc']['status'] == 'error'
    assert 'claim' in result['package_results']['cc']['error']
    assert result['package_results']['aa']['sha'] and result['package_results']['bb']['sha']
    assert result['proceed'] is False and deliveries == []
    assert _owned_bytes(tmp_path) == expected


def test_unchanged_automatic_attempt_runs_real_packages_and_finishes(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path)
    _aggregate(monkeypatch)
    starts = []

    def run(*args, **options):
        starts.append(options['feature'])
        return _commit(*args, **options)

    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
                                   run_fn=run, **auto)
    assert sorted(starts) == ['aa', 'bb']
    assert result['proceed'] is True and result['aggregate']['all_pass']
    assert all(r['sha'] for r in result['package_results'].values())
    assert aw.load(aw.shared_registry_path(tmp_path))['active'][0]['status'] == 'done'
