"""Настоящий package commit переживает partial failure и удаление disposable clone."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ai_ops_kit.engine import parallel_live as live
from ai_ops_kit.shared import gitio, lifecycle_store
from _parallel_dispatch_helpers import _real_repo, _real_commit


def _run_partial(tmp_path, monkeypatch, *, worktree=False):
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    if worktree:
        alternate = tmp_path / 'alternate'
        assert gitio.git(root, 'worktree', 'add', '-q', '-b', 'alternate', str(alternate))[0] == 0
        root = alternate
    clones = {}
    def run(task, signals, clone, **options):
        clones[options['feature']] = Path(clone)
        result = _real_commit(task, signals, clone, **options)
        result['ready_for_pr'] = options['feature'] == 'aa'
        return result
    result = live.run_live_concurrent(wg, root, base, {'aa': 'A', 'bb': 'B'}, {}, run)
    return root, base, result, clones


@pytest.mark.parametrize('worktree', [False, True])
def test_reported_package_commit_is_readable_after_partial_failure_and_cleanup(tmp_path, monkeypatch, worktree):
    root, base, result, clones = _run_partial(tmp_path, monkeypatch, worktree=worktree)
    assert not result['proceed'] and result['stage'] == 'pre-fan-in'
    assert result['package_results']['aa']['status'] == 'pass'
    sha = result['package_results']['aa']['sha']
    assert sha != base and all(not p.exists() for p in clones.values())
    assert gitio.git(root, 'gc', '--prune=now')[0] == 0, 'checkpoint ref must protect commit beyond dangling-object grace period'
    rc, content, _ = gitio.git(root, 'show', f'{sha}:aa.py')
    assert rc == 0 and content == "VALUE = 'aa'", 'SHA metadata alone is not retained Git source'
    receipt = json.loads(Path(result['package_artifacts']['receipt']).read_text())
    items = {p['package_id']: p for p in receipt['packages']}
    assert items['aa']['retained_ref'].startswith('refs/ai-ops/parallel/')
    assert gitio.git(root, 'rev-parse', '--verify', items['aa']['retained_ref'])[1] == sha
    assert gitio.git(root, 'rev-parse', 'HEAD')[1] == base
    assert gitio.git(root, 'status', '--porcelain')[1] == ''
    assert not result['delivery_plan']['ready'], 'retained source never promotes failed fan-in'


@pytest.mark.parametrize('fault', ['fetch', 'update-ref', 'old-git', 'ref-collision', 'cas-race', 'readback'])
def test_retention_fault_never_deletes_last_package_source(tmp_path, monkeypatch, fault):
    original = live._git
    touched = []
    def git(root, *args, **kw):
        argv = list(args)
        if fault == 'old-git' and argv == ['--version']:
            touched.append('old-git')
            return live.subprocess.CompletedProcess([], 0, stdout='git version 2.35.0\n', stderr='')
        if fault == 'ref-collision' and 'rev-parse' in argv and '--quiet' in argv and any(str(a).startswith('refs/ai-ops/parallel/') for a in argv):
            ref = argv[-1]
            base = gitio.git(root, 'rev-parse', 'HEAD')[1]
            assert gitio.git(root, 'update-ref', ref, base)[0] == 0
            touched.append((ref, base))
        if fault == 'cas-race' and 'update-ref' in argv and 'core.fsync=objects,reference' in argv:
            ref = argv[argv.index('update-ref') + 1]
            base = gitio.git(root, 'rev-parse', 'HEAD')[1]
            assert gitio.git(root, 'update-ref', ref, base)[0] == 0
            touched.append((ref, base))
        if fault == 'readback' and 'rev-parse' in argv and '--verify' in argv and '--quiet' not in argv and any(str(a).startswith('refs/ai-ops/parallel/') for a in argv):
            touched.append('readback')
            return live.subprocess.CompletedProcess([], 0, stdout='f' * 40 + '\n', stderr='')
        if fault in ('fetch', 'update-ref') and fault in argv and 'core.fsync=objects,reference' in argv:
            touched.append(fault)
            raise RuntimeError('controlled checkpoint fault')
        return original(root, *args, **kw)
    monkeypatch.setattr(live, '_git', git)
    root, base, result, clones = _run_partial(tmp_path, monkeypatch)
    assert touched, 'the intended retention boundary was actually reached'
    assert result['package_artifacts']['status'] == 'blocked'
    assert result['package_artifacts']['checkpoint_failure'] == {
        'fetch': 'fetch', 'update-ref': 'ref-write', 'old-git': 'unsupported-git',
        'ref-collision': 'ref-conflict', 'cas-race': 'ref-write', 'readback': 'ref-readback'}[fault]
    assert result['cleanup']['status'] == 'retained' and all(p.exists() for p in clones.values())
    assert result['delivery']['open_pr'] is False and not result['delivery_plan']['ready']
    assert gitio.git(root, 'rev-parse', 'HEAD')[1] == base
    if fault in ('ref-collision', 'cas-race'):
        ref, expected = touched[0]
        assert gitio.git(root, 'rev-parse', '--verify', ref)[1] == expected, 'never overwrite conflicting checkpoint'


def test_same_checkpoint_retry_is_idempotent_after_receipt_failure(tmp_path, monkeypatch):
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    paths = {}
    original = lifecycle_store.durable_write_json
    def fault(path, *args, **kw):
        return {'ok': False} if Path(path).name == 'package-receipt.json' else original(path, *args, **kw)
    def run(task, sig, clone, **opts):
        paths[opts['feature']] = {'path': str(clone)}
        return _real_commit(task, sig, clone, **opts)
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, 'durable_write_json', fault)
        result = live.run_live_concurrent(wg, root, base, {'aa': 'A', 'bb': 'B'}, {}, run)
    assert result['package_artifacts']['status'] == 'blocked'
    run_dir = Path(result['package_artifacts']['retained_source'])
    run_id = hashlib.sha256(str(run_dir.resolve()).encode()).hexdigest()
    ref = f"refs/ai-ops/parallel/{run_id}/{hashlib.sha256(b'aa').hexdigest()}"
    before = gitio.git(root, 'rev-parse', '--verify', ref)
    assert before[0] == 0 and before[1] == result['package_results']['aa']['sha']
    proof = live._preserve_package_artifacts(root, base, paths, run_dir, result['package_results'])
    assert proof['status'] == 'preserved' and proof['new_product_calls'] == 0
    assert gitio.git(root, 'rev-parse', '--verify', ref) == before


def test_checkpoint_fetch_is_local_hardened_and_never_runs_auto_maintenance(tmp_path, monkeypatch):
    original, fetches = live._git, []
    def git(root, *args, **kw):
        if 'fetch' in args and 'core.fsync=objects,reference' in args:
            fetches.append(args)
        return original(root, *args, **kw)
    monkeypatch.setattr(live, '_git', git)
    root, base, result, clones = _run_partial(tmp_path, monkeypatch)
    assert result['package_artifacts']['status'] == 'preserved' and len(fetches) == 2
    for args in fetches:
        assert all(flag in args for flag in ('core.fsyncMethod=fsync', '--no-tags', '--no-write-fetch-head',
            '--no-recurse-submodules', '--no-auto-maintenance', '--no-write-commit-graph', '--no-prune', '--no-prune-tags'))
        assert Path(args[-2]).is_absolute()
    assert gitio.git(root, 'config', '--local', '--get', 'core.fsync')[0] == 1, 'per-command durability does not persist config'
