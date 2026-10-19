"""Готовая real Git integration доставляется без нового package/model execution."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pytest

from ai_ops_kit.engine import ai_ops_run, execution_pipeline, parallel_live_dispatch as dsp
from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.delivery import pr_open
from ai_ops_kit.shared import gitio, lifecycle_store
from test_parallel_package_admission import _automatic, _aggregate, _commit


def _ready(root, monkeypatch, *, open_pr=False):
    signals, auto = _automatic(root)
    assert gitio.git(root, 'remote', 'add', 'origin', 'https://github.com/example/child.git')[0] == 0
    _aggregate(monkeypatch)
    calls, posts = [], []
    def package(*args, **kwargs):
        calls.append(kwargs['feature'])
        return _commit(*args, **kwargs)
    def post(clone, branch, **kwargs):
        sha = gitio.git(clone, 'rev-parse', 'HEAD')[1]
        posts.append(sha)
        return {'status': 'opened', 'head_sha': sha, 'number': 7, 'url': 'https://github.com/example/child/pull/7'}
    monkeypatch.setattr(execution_pipeline, '_reverify_against_current_target', lambda *a: {'stale': False})
    monkeypatch.setattr(pr_open, 'open_draft_pr', post)
    rec = dsp.run_parallel_live('write work', signals, root, feature='work', provider='mock',
                                run_fn=package, open_pr=open_pr, **auto)
    assert rec['proceed'] and rec['aggregate']['all_pass'] and sorted(calls) == ['aa', 'bb']
    assert Path(rec['integration_source']['integration_clone']).is_dir()
    def forbidden(*a, **k):
        pytest.fail('delivery retry entered model/provider/package boundary')
    monkeypatch.setattr(ai_ops_run, 'run', forbidden)
    monkeypatch.setattr(ai_ops_run, 'resolve_provider_for_run', forbidden)
    monkeypatch.setattr(dsp, 'run_parallel_live', forbidden)
    return rec, auto['admission']['identity'], posts


def _resume(root, identity, **kwargs):
    return dsp.resume_parallel_delivery(root, 'work', session=identity, execute=True, open_pr=True, **kwargs)


def _remote(rec, **overrides):
    return {'status': 'found', 'repository': 'example/child', 'head_sha': rec['integration_sha'],
            'base_ref': rec['base_binding']['base_ref'], 'number': 7,
            'url': 'https://github.com/example/child/pull/7', **overrides}


def test_engine_cli_delivers_saved_real_integration_and_reuses_receipt_without_new_models(tmp_path, monkeypatch, capsys):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    before_head = gitio.git(tmp_path, 'rev-parse', 'HEAD')[1]
    before_budget = copy.deepcopy(original['budget'])
    capsys.readouterr()
    args = ['resume', str(tmp_path), 'work', '--session', identity, '--execute', '--open-pr', '--reevaluate-only', '--json']
    assert ai_ops_run.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert posts == [original['integration_sha']]
    assert result['budget'] == before_budget and result['delivery_retry']['new_model_calls'] == 0
    assert result['delivery_retry']['new_package_calls'] == 0
    assert result['delivery']['sha_verified'] is True and (tmp_path / result['delivery']['receipt']).is_file()
    first_attempt = result['delivery_retry']['attempt_id']
    monkeypatch.setattr(pr_open, 'reconcile_delivery', lambda *a: _remote(original))
    again = _resume(tmp_path, identity)
    assert dsp.exit_code(again) == 0 and again['delivery']['status'] == 'reconciled'
    assert again['delivery']['reused_receipt'] and posts == [original['integration_sha']]
    assert again['delivery_retry']['attempt_id'] != first_attempt
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == before_head
    assert Path(original['integration_source']['integration_clone']).is_dir()


def test_preflight_does_not_mint_claim_or_deliver(tmp_path, monkeypatch):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    path = aw.shared_registry_path(tmp_path)
    before = path.read_bytes()
    report = tmp_path / 'features/work/parallel-report.json'
    raw = report.read_bytes()
    rec = dsp.resume_parallel_delivery(tmp_path, 'work', session=identity)
    assert rec['resume']['can_resume'] and rec['resume']['resumed'] is False
    assert path.read_bytes() == before and report.read_bytes() == raw and posts == []


@pytest.mark.parametrize('damage', ['corrupt-report', 'malformed-evidence', 'dirty-source', 'advanced-source',
    'base-moved', 'frozen-input', 'foreign-owner', 'replaced-attempt', 'active-attempt', 'source-escape', 'corrupt-outbox'])
def test_invalid_or_foreign_ready_result_never_delivers_or_overwrites_claim(tmp_path, monkeypatch, damage):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    report = tmp_path / 'features/work/parallel-report.json'
    registry = aw.shared_registry_path(tmp_path)
    source = Path(original['integration_source']['integration_clone'])
    if damage == 'corrupt-report':
        report.write_text('{broken')
    elif damage in ('malformed-evidence', 'source-escape'):
        value = json.loads(report.read_text())
        if damage == 'malformed-evidence':
            value['integration_source'] = ['invalid']
        else:
            value['integration_source']['integration_clone'] = str(tmp_path.parent)
        report.write_text(json.dumps(value))
    elif damage in ('dirty-source', 'advanced-source'):
        (source / 'aa.txt').write_text('changed source\n')
        if damage == 'advanced-source':
            assert gitio.git(source, 'add', 'aa.txt')[0] == 0
            assert gitio.git(source, 'commit', '-qm', 'changed')[0] == 0
    elif damage == 'base-moved':
        (tmp_path / 'new.txt').write_text('new base\n')
        assert gitio.git(tmp_path, 'add', 'new.txt')[0] == 0
        assert gitio.git(tmp_path, 'commit', '-qm', 'move base')[0] == 0
    elif damage == 'frozen-input':
        p = tmp_path / 'features/aa/run-settings.yaml'
        p.write_bytes(p.read_bytes() + b'\n# drift\n')
    elif damage == 'corrupt-outbox':
        outbox = tmp_path / 'features/work/delivery-outbox'
        outbox.mkdir()
        (outbox / 'bad.intent.yaml').write_text('kind: wrong\n')
    else:
        data = aw.load(registry)
        entry = data['active'][0]
        if damage == 'foreign-owner':
            entry['owner_session'] = 'another-owner'
        elif damage == 'replaced-attempt':
            entry['auto_admission']['attempt_id'] = 'another-generation'
        else:
            entry['status'] = 'in-progress'
        aw.save(registry, data)
    before_registry, before_report = registry.read_bytes(), report.read_bytes()
    result = _resume(tmp_path, identity)
    assert dsp.exit_code(result) == 2 and result['reason']
    assert posts == [] and registry.read_bytes() == before_registry and report.read_bytes() == before_report
    assert source.is_dir()


@pytest.mark.parametrize('found', [True, False])
def test_unknown_delivery_reconciles_before_any_repeat_post(tmp_path, monkeypatch, found):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    def unknown(clone, *args, **kwargs):
        posts.append(gitio.git(clone, 'rev-parse', 'HEAD')[1])
        return {'status': 'outcome_unknown'}
    monkeypatch.setattr(pr_open, 'open_draft_pr', unknown)
    first = _resume(tmp_path, identity)
    assert len(posts) == 1 and first['delivery']['status'] == 'outcome_unknown'
    monkeypatch.setattr(pr_open, 'reconcile_delivery', lambda *a: _remote(original) if found else {'status': 'unavailable'})
    second = _resume(tmp_path, identity)
    assert len(posts) == 1
    assert dsp.exit_code(second) == (0 if found else 2)
    if found:
        assert second['delivery']['reused_receipt'] and second['delivery']['sha_verified']


def test_concurrent_retry_admission_has_only_one_owner(tmp_path, monkeypatch):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def post(clone, branch, **kwargs):
        entered.set()
        assert release.wait(10)
        posts.append(gitio.git(clone, 'rev-parse', 'HEAD')[1])
        return {'status': 'opened', 'head_sha': posts[-1], 'number': 7, 'url': 'https://github.com/example/child/pull/7'}
    monkeypatch.setattr(pr_open, 'open_draft_pr', post)
    first = []
    thread = threading.Thread(target=lambda: first.append(_resume(tmp_path, identity)))
    thread.start()
    try:
        assert entered.wait(10)
        snapshot = aw.shared_registry_path(tmp_path).read_bytes()
        second = _resume(tmp_path, identity)
        assert dsp.exit_code(second) == 2 and 'claim' in second['reason']
        assert aw.shared_registry_path(tmp_path).read_bytes() == snapshot
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and dsp.exit_code(first[0]) == 0 and len(posts) == 1


def test_takeover_during_post_cannot_overwrite_new_owner_artifacts(tmp_path, monkeypatch):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    expected = {}
    def post(clone, branch, **kwargs):
        assert aw.register(aw.shared_registry_path(tmp_path), 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'],
                           'rescue', child_root=tmp_path, takeover=True, takeover_reason='explicit recovery') == 0
        for name in ('parallel-report.json', 'run-report.json', 'run-handoff.yaml'):
            path = tmp_path / 'features/work' / name
            path.write_text('new-owner\n')
            expected[path] = path.read_bytes()
        expected[aw.shared_registry_path(tmp_path)] = aw.shared_registry_path(tmp_path).read_bytes()
        posts.append(original['integration_sha'])
        return {'status': 'opened', 'head_sha': original['integration_sha'], 'number': 7, 'url': 'https://github.com/example/child/pull/7'}
    monkeypatch.setattr(pr_open, 'open_draft_pr', post)
    result = _resume(tmp_path, identity)
    assert dsp.exit_code(result) == 2 and len(posts) == 1
    assert all(path.read_bytes() == value for path, value in expected.items())
    assert not list((tmp_path / 'features/work/delivery-outbox').glob('*.receipt.yaml'))


def test_retry_checkpoint_failure_is_retryable_without_spend_or_delivery(tmp_path, monkeypatch):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    write = lifecycle_store.durable_write_json
    def fail(path, *args, **kwargs):
        return {'ok': False} if Path(path).name == 'parallel-report.json' else write(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, 'durable_write_json', fail)
        blocked = _resume(tmp_path, identity)
    assert dsp.exit_code(blocked) == 2 and posts == []
    result = _resume(tmp_path, identity)
    assert dsp.exit_code(result) == 0 and posts == [original['integration_sha']]


def test_absent_parallel_report_preserves_generic_resume_path(tmp_path, monkeypatch):
    assert dsp.resume_parallel_delivery(tmp_path, 'missing', session='cli') is None


def test_takeover_during_unknown_reconciliation_cannot_overwrite_new_receipt(tmp_path, monkeypatch):
    original, identity, posts = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(pr_open, 'open_draft_pr', lambda *a, **k: {'status': 'outcome_unknown'})
    first = _resume(tmp_path, identity)
    assert first['delivery']['status'] == 'outcome_unknown'
    did = first['delivery']['delivery_id']
    receipt = tmp_path / f'features/work/delivery-outbox/{did}.receipt.yaml'
    expected = {}
    def reconcile(*args):
        assert aw.register(aw.shared_registry_path(tmp_path), 'work', 'ai-ops/work', ['aa.txt'],
                           'rescue', child_root=tmp_path, takeover=True, takeover_reason='explicit recovery') == 0
        receipt.write_text('new-owner receipt\n')
        expected[receipt] = receipt.read_bytes()
        expected[aw.shared_registry_path(tmp_path)] = aw.shared_registry_path(tmp_path).read_bytes()
        return _remote(original)
    monkeypatch.setattr(pr_open, 'reconcile_delivery', reconcile)
    result = _resume(tmp_path, identity)
    assert dsp.exit_code(result) == 2 and all(p.read_bytes() == value for p, value in expected.items())


@pytest.mark.parametrize('result', [{'status': 'unavailable'}, {'status': 'absent'},
    {'status': 'found', 'repository': 'other/repo'}, {'status': 'found', 'head_sha': 'f' * 40}])
def test_previous_receipt_requires_current_remote_identity_without_repeat_post(tmp_path, monkeypatch, result):
    original, identity, posts = _ready(tmp_path, monkeypatch, open_pr=True)
    assert len(posts) == 1
    monkeypatch.setattr(pr_open, 'reconcile_delivery', lambda *a: _remote(original, **result))
    retried = _resume(tmp_path, identity)
    assert dsp.exit_code(retried) == 2 and len(posts) == 1
