"""Partial terminal automatic retry: real retained Git commits, no paid/native provider calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp, parallel_live as live
from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.shared import gitio
from ai_ops_kit.shared.budget import Budget
from test_budget_reservations import _runtime
from test_parallel_package_admission import _commit


def _retry(root, signals, auto, callback):
    return dsp.run_parallel_live('write work', signals, root, feature='work', provider='mock',
        run_fn=callback, **dict(auto, budget=Budget.from_dict(auto['budget'].limits())))


def _evidence(root, report):
    path = root / 'features/work/parallel-report.json'
    receipt = Path(report['package_artifacts']['receipt'])
    return path, receipt, json.loads(receipt.read_text())


def test_resume_reuses_actual_deleted_clone_commit_and_only_retries_failed_package(tmp_path, monkeypatch):
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True)
    sha = original['package_results']['aa']['sha']
    assert gitio.git(tmp_path, 'show', f'{sha}:aa.txt')[1] == 'actual package aa'
    assert not Path(original['package_results']['aa']['clone']).exists(), 'prove source clone was deleted'
    assert not original['proceed'] and original['package_results']['bb']['status'] == 'fail'
    starts = []
    def callback(*args, **options):
        options['budget'].charge_call()
        starts.append(options['feature'])
        return _commit(*args, **options)
    result = _retry(tmp_path, signals, auto, callback)
    assert starts == ['bb'] and result['proceed']
    assert result['package_results']['aa']['sha'] == sha
    assert result['package_results']['aa']['reused_from'] == original['package_artifacts']['receipt']
    assert result['package_resume'] == {'reused_packages': ['aa'], 'executed_packages': ['bb']}
    assert next(r for r in result['trace'] if r['pkg'] == 'aa')['mode'] == 'reused-checkpoint'
    assert result['aggregate']['tested_revision'] == result['integration_sha']
    clone = Path(result['integration_source']['integration_clone'])
    assert gitio.git(clone, 'show', 'HEAD:aa.txt')[1] == 'actual package aa'
    assert gitio.git(clone, 'show', 'HEAD:bb.txt')[1] == 'actual package bb'
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == original['base_binding']['base_sha']
    assert result['budget']['model_calls'] == json.loads(ledger.read_text())['model_calls'] == 3
    assert result['budget']['remaining_calls'] == 0 and result['budget']['cost'] is None


def test_repeated_failed_retry_retains_pass_and_accumulates_durable_budget(tmp_path, monkeypatch):
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True, cap=4)
    starts = []
    def callback(*args, **options):
        options['budget'].charge_call(); starts.append(options['feature'])
        rep = _commit(*args, **options)
        if len(starts) == 1:rep['ready_for_pr'] = False
        return rep
    first = _retry(tmp_path, signals, auto, callback)
    assert not first['proceed'] and first['budget']['model_calls'] == 3
    second = _retry(tmp_path, signals, auto, callback)
    assert second['proceed'] and starts == ['bb', 'bb']
    assert second['package_results']['aa']['sha'] == original['package_results']['aa']['sha']
    assert json.loads(ledger.read_text())['model_calls'] == 4


@pytest.mark.parametrize('damage', ['receipt-missing', 'receipt-corrupt', 'receipt-duplicate', 'report-corrupt',
    'ref-missing', 'ref-changed', 'ref-symbolic', 'gate-mismatch', 'unknown-error', 'unknown-status',
    'owner', 'generation', 'active', 'base', 'input', 'ledger-missing', 'conflicting-work', 'outbox', 'receipt-list', 'malformed-gate', 'invalid-sha'])
def test_resume_damage_never_runs_new_callbacks_or_resets_budget(tmp_path, monkeypatch, damage):
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True)
    report, receipt, data = _evidence(tmp_path, original)
    registry = aw.shared_registry_path(tmp_path)
    claim = aw.load(registry)
    ref = next(p['retained_ref'] for p in data['packages'] if p['package_id'] == 'aa')
    if damage == 'receipt-missing':receipt.unlink()
    elif damage == 'receipt-corrupt':receipt.write_text('{bad')
    elif damage == 'receipt-list':receipt.write_text('[]')
    elif damage == 'malformed-gate':
        original['package_results']['bb']['gate_report'] = 'unknown'
        report.write_text(json.dumps(original))
    elif damage == 'invalid-sha':
        original['package_results']['bb']['sha'] = 'invalid'
        report.write_text(json.dumps(original))
    elif damage == 'receipt-duplicate':
        data['packages'].append(data['packages'][0]);receipt.write_text(json.dumps(data))
    elif damage == 'report-corrupt':report.write_text('{bad')
    elif damage == 'ref-missing':assert gitio.git(tmp_path, 'update-ref', '-d', ref)[0] == 0
    elif damage == 'ref-changed':assert gitio.git(tmp_path, 'update-ref', ref, 'HEAD')[0] == 0
    elif damage == 'ref-symbolic':assert gitio.git(tmp_path, 'symbolic-ref', ref, 'refs/heads/main')[0] == 0
    elif damage == 'gate-mismatch':
        original['package_results']['aa']['gate_report']['tested_revision'] = '0' * 40
        report.write_text(json.dumps(original))
    elif damage.startswith('unknown-'):
        status = 'error' if damage == 'unknown-error' else 'unknown'
        original['package_results']['bb']['status'] = status
        next(p for p in data['packages'] if p['package_id'] == 'bb')['status'] = status
        receipt.write_text(json.dumps(data));report.write_text(json.dumps(original))
    elif damage in ('owner', 'generation', 'active'):
        entry = claim['active'][0]
        if damage == 'owner':entry['owner_session'] = 'other-session'
        elif damage == 'generation':entry['auto_admission']['attempt_id'] = 'replacement'
        else:entry['status'] = 'in-progress'
        aw.save(registry, claim)
    elif damage == 'base':
        (tmp_path / 'unrelated.txt').write_text('new base')
        assert gitio.git(tmp_path, 'add', 'unrelated.txt')[0] == 0
        assert gitio.git(tmp_path, 'commit', '-qm', 'move base')[0] == 0
    elif damage == 'input':
        path = tmp_path / 'features/aa/run-settings.yaml';path.write_text(path.read_text() + '\n# drift\n')
    elif damage == 'ledger-missing':ledger.unlink()
    elif damage == 'conflicting-work':
        assert aw.register(registry, 'other', 'ai-ops/other', ['aa.txt'], 'other', child_root=tmp_path) == 0
    else:
        outbox = tmp_path / 'features/work/delivery-outbox';outbox.mkdir()
        (outbox / 'unresolved.intent.yaml').write_text('kind: DeliveryIntent\n')
    before = ledger.read_bytes() if ledger.exists() else None
    starts = []
    result = _retry(tmp_path, signals, auto, lambda *a, **k: starts.append(k['feature']))
    assert not result['proceed'] and dsp.exit_code(result) == 2 and starts == []
    assert ledger.read_bytes() == before if before is not None else not ledger.exists()


def test_claim_barrier_rechecks_report_bytes_before_new_generation(tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import work_claims
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True)
    report, _, _ = _evidence(tmp_path, original)
    registry = aw.shared_registry_path(tmp_path)
    before = registry.read_bytes()
    retry = work_claims.retry_package_claim
    def race(*args, **kwargs):
        report.write_bytes(report.read_bytes() + b'\n')
        return retry(*args, **kwargs)
    monkeypatch.setattr(work_claims, 'retry_package_claim', race)
    starts = []
    result = _retry(tmp_path, signals, auto, lambda *a, **k: starts.append('provider'))
    assert not result['proceed'] and starts == [] and 'changed' in result['reason']
    assert registry.read_bytes() == before and json.loads(ledger.read_text())['model_calls'] == 2


def test_takeover_before_new_callback_never_spends_remaining_slot(tmp_path, monkeypatch):
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True)
    restore = live._restore_package_checkpoint
    # Gate before dispatch's first actual new callback, independent of thread scheduling.
    called, expected = [], {}
    def dispatch(wg, root, base, tasks, sig, callback, **options):
        registry = aw.shared_registry_path(tmp_path)
        assert aw.register(registry, 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'], 'rescue', child_root=tmp_path,
                           takeover=True, takeover_reason='explicit recovery') == 0
        expected['claim'] = registry.read_bytes()
        callback('write bb', sig, tmp_path, feature='bb', budget=options['run_options']['budget'])
    monkeypatch.setattr(live, 'run_live_concurrent', dispatch)
    result = _retry(tmp_path, signals, auto, lambda *a, **k: called.append('provider'))
    assert not result['proceed'] and called == []
    assert aw.shared_registry_path(tmp_path).read_bytes() == expected['claim']
    assert json.loads(ledger.read_text())['model_calls'] == 2
    assert live._restore_package_checkpoint is restore


def test_fresh_aggregate_failure_is_never_delivery_success(tmp_path, monkeypatch):
    from ai_ops_kit.gates import evidence_collector
    signals, auto, original, ledger = _runtime(tmp_path, monkeypatch, partial=True)
    calls = []
    monkeypatch.setattr(evidence_collector, 'collect', lambda *a, **k: {
        'gate_evidence': {'implementation_verification': {'status': 'fail'}}, 'checks': {},
        'revision': gitio.git(a[1], 'rev-parse', 'HEAD')[1]})
    def callback(*args, **options):
        options['budget'].charge_call();calls.append(options['feature']);return _commit(*args, **options)
    result = _retry(tmp_path, signals, auto, callback)
    assert calls == ['bb'] and not result['proceed'] and not result['aggregate']['all_pass']
    assert result['delivery']['status'] == 'not-requested' and not result['delivery_plan']['ready']
    # Both packages are now pass; exhausted budget still permits zero-callback integration recheck.
    from test_parallel_package_admission import _aggregate
    _aggregate(monkeypatch)
    retried = _retry(tmp_path, signals, auto, lambda *a, **k: calls.append('must-not-run'))
    assert retried['proceed'] and calls == ['bb'] and retried['budget']['remaining_calls'] == 0
    assert retried['package_resume']['reused_packages'] == ['aa', 'bb']
