"""Kernel-held capacity spans processes, never masquerades provider failure as NOT_STARTED."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp, parallel_live as live
from ai_ops_kit.lifecycle import active_work as aw, work_claims as claims
from ai_ops_kit.shared.budget import Budget
from test_parallel_package_admission import _automatic, _aggregate, _commit


ROOT = Path(__file__).resolve().parents[2]


def _claim(root):
    signals, auto = _automatic(root)
    admission = dict(auto['admission'], attempt_id='capacity-test')
    assert aw.register(aw.shared_registry_path(root), 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'],
        admission['identity'], child_root=root, admission=admission) == 0
    return signals, auto, admission


def _ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=15), 'own resource child did not respond'
    line = process.stdout.readline().strip()
    assert line == 'HELD', line


def test_real_processes_share_two_slots_and_process_exit_releases_capacity(tmp_path):
    _, _, admission = _claim(tmp_path)
    code = """import json,sys
from pathlib import Path
from ai_ops_kit.lifecycle.work_claims import automatic_package_slot
with automatic_package_slot(Path(sys.argv[1]),'work',json.loads(sys.argv[2])):
 print('HELD',flush=True)
 sys.stdin.readline()
"""
    children = []
    try:
        for _ in range(2):
            child = subprocess.Popen([sys.executable, '-c', code, str(tmp_path), json.dumps(admission)],
                cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(child);_ready(child)
        entered, budget = [], Budget(max_model_calls=3)
        with pytest.raises(claims.PackageCapacityUnavailable, match='busy'):
            with claims.automatic_package_slot(tmp_path, 'work', admission):
                budget.charge_call(); entered.append('provider')
        assert entered == [] and budget.model_calls == 0
        # Abrupt exit of ONLY our child releases its kernel-held local callback slot.
        children[0].terminate();children[0].communicate(timeout=15)
        with claims.automatic_package_slot(tmp_path, 'work', admission) as slot:
            assert slot['limit'] == 2 and slot['scope'] == 'git-common-store'
            assert slot['attempt_id'] == admission['attempt_id']
        children[1].communicate('\n', timeout=15)
        assert children[1].returncode == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=15)


def test_automatic_busy_is_known_not_started_then_partial_retry_calls_models_once(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path)
    _aggregate(monkeypatch)
    actual = live.run_live_concurrent
    def occupy(wg, root, base, tasks, sig, callback, **options):
        admission = aw.load(aw.shared_registry_path(tmp_path))['active'][0]['auto_admission']
        with claims.automatic_package_slot(tmp_path, 'work', admission), claims.automatic_package_slot(tmp_path, 'work', admission):
            return actual(wg, root, base, tasks, sig, callback, **options)
    called = []
    def provider(*args, **options):
        options['budget'].charge_call();called.append(options['feature']);return _commit(*args, **options)
    first = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
        run_fn=provider, runner=occupy, **auto)
    assert not first['proceed'] and called == [] and first['budget']['model_calls'] == 0
    assert first['package_artifacts']['status'] == 'preserved'
    for result in first['package_results'].values():
        assert result['status'] == 'fail' and result['sha'] is None
        assert result['package_capacity']['status'] == 'not-started'
    receipt = json.loads(Path(first['package_artifacts']['receipt']).read_text())
    assert all(p['package_capacity']['status'] == 'not-started' for p in receipt['packages'])
    retried = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock',
        run_fn=provider, **dict(auto, budget=Budget.from_dict(auto['budget'].limits())))
    assert retried['proceed'] and sorted(called) == ['aa', 'bb']
    assert retried['budget']['model_calls'] == 2
    assert all(r['package_capacity']['callback_returned'] for r in retried['package_results'].values())


@pytest.mark.parametrize('damage', ['directory-symlink', 'lock-symlink', 'lock-open-error', 'owner', 'input'])
def test_resource_admission_failure_never_enters_callback_or_changes_other_owner(tmp_path, monkeypatch, damage):
    _, _, admission = _claim(tmp_path)
    directory = aw.shared_registry_path(tmp_path).parent / 'package-slots'
    target = tmp_path / 'untouched';target.mkdir()
    if damage == 'directory-symlink':directory.symlink_to(target, target_is_directory=True)
    elif damage == 'lock-symlink':
        directory.mkdir();(target / 'lock').write_text('do not modify')
        (directory / 'callback-0.lock').symlink_to(target / 'lock')
    elif damage == 'lock-open-error':
        original = os.open
        def denied(path, *args, **kwargs):
            if str(path).endswith('.lock') and 'package-slots' in str(path):raise PermissionError('controlled')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(os, 'open', denied)
    elif damage == 'owner':
        assert aw.register(aw.shared_registry_path(tmp_path), 'work', 'ai-ops/work', ['aa.txt', 'bb.txt'], 'rescue',
            child_root=tmp_path, takeover=True, takeover_reason='explicit test recovery') == 0
    else:
        path = tmp_path / 'features/aa/run-settings.yaml';path.write_text(path.read_text() + '\n# drift\n')
    before = aw.shared_registry_path(tmp_path).read_bytes()
    called = []
    error = aw.ActiveWorkCorrupt if damage in ('owner', 'input') else claims.PackageCapacityUnavailable
    with pytest.raises(error):
        with claims.automatic_package_slot(tmp_path, 'work', admission):called.append('provider')
    assert called == [] and aw.shared_registry_path(tmp_path).read_bytes() == before
    if (target / 'lock').exists():assert (target / 'lock').read_text() == 'do not modify'


def test_callback_exception_releases_only_own_slot(tmp_path):
    _, _, admission = _claim(tmp_path)
    with claims.automatic_package_slot(tmp_path, 'work', admission):
        with pytest.raises(RuntimeError, match='already entered'):
            with claims.automatic_package_slot(tmp_path, 'work', admission):
                raise RuntimeError('already entered callback')
        with claims.automatic_package_slot(tmp_path, 'work', admission):
            with pytest.raises(claims.PackageCapacityUnavailable):
                with claims.automatic_package_slot(tmp_path, 'work', admission):pytest.fail('third entered')
    # Both outer contexts have released their own fds; no leaked slot after exception.
    with ExitStack() as stack:
        stack.enter_context(claims.automatic_package_slot(tmp_path, 'work', admission))
        stack.enter_context(claims.automatic_package_slot(tmp_path, 'work', admission))


def test_capacity_exception_from_entered_callback_is_error_not_not_started(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path)
    _aggregate(monkeypatch)
    called = []
    def provider(*args, **options):
        options['budget'].charge_call();called.append(options['feature'])
        raise claims.PackageCapacityUnavailable('controlled exception after actual callback entry')
    result = dsp.run_parallel_live('write work', signals, tmp_path, feature='work', provider='mock', run_fn=provider, **auto)
    assert sorted(called) == ['aa', 'bb'] and result['budget']['model_calls'] == 2
    assert not result['proceed']
    assert all(r['status'] == 'error' and not r.get('package_capacity') for r in result['package_results'].values())


def test_unexpected_flock_error_closes_all_owned_descriptors(tmp_path, monkeypatch):
    import fcntl
    _, _, admission = _claim(tmp_path)
    flock, fdopen, closed = fcntl.flock, os.fdopen, []
    def opened(*args, **kwargs):
        stream = fdopen(*args, **kwargs);closed.append(stream);return stream
    def failing(fd, flags):
        if any(fd is stream for stream in closed):raise OSError('controlled flock failure')
        return flock(fd, flags)
    monkeypatch.setattr(os, 'fdopen', opened);monkeypatch.setattr(fcntl, 'flock', failing)
    with pytest.raises(claims.PackageCapacityUnavailable):
        with claims.automatic_package_slot(tmp_path, 'work', admission):pytest.fail('entered')
    assert closed and all(f.closed for f in closed)


def test_different_canonical_work_claims_share_the_same_store_slots(tmp_path):
    _, _, admission = _claim(tmp_path)
    other = dict(admission, attempt_id='other-work-generation')
    assert aw.register(aw.shared_registry_path(tmp_path), 'other', 'ai-ops/other', ['cc.txt'],
        other['identity'], child_root=tmp_path, admission=other) == 0
    with claims.automatic_package_slot(tmp_path, 'work', admission):
        with claims.automatic_package_slot(tmp_path, 'other', other):
            with pytest.raises(claims.PackageCapacityUnavailable, match='busy'):
                with claims.automatic_package_slot(tmp_path, 'other', other):pytest.fail('third work callback entered')
