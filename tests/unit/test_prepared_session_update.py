"""Synthetic linked-worktree state, never real colleague/model acceptance."""
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import signal
import time

import pytest

from ai_ops_kit.cli import project_session as cli
from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration as pending
from ai_ops_kit.lifecycle import session_migration_store as store
from test_project_session import project as base_project
from test_session_migration import manifest
from tests.unit._installer_helpers import _make_child_repo

pytestmark = pytest.mark.unit


@pytest.fixture
def prepared_linked(tmp_path, monkeypatch):
    primary = base_project.__wrapped__(tmp_path, monkeypatch)
    root = tmp_path / 'linked'
    sessions.git(primary, 'worktree', 'add', '-b', 'prepared-fixture', str(root))
    (root / '.gitignore').write_text('.ai/runtime/\n')
    manifest(root)
    sessions.git(root, 'add', '-A')
    sessions.git(root, 'commit', '-qm', 'prepared environment')
    task = sessions.begin(root, 'codex', 'owner', 'Check the saved result', 'original-turn')
    monkeypatch.chdir(root)
    assert cli.main(['run', '--runtime', 'codex', '--session', 'owner', '--signals',
                     '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    task = sessions.load(root, 'codex', 'owner')
    assert task['status'] == 'running' and task['execution']['prepared'] is True
    assert (root / '.git').is_file()
    (root / 'result.txt').write_text('actual committed result\n')
    sessions.git(root, 'add', 'result.txt')
    sessions.git(root, 'commit', '-qm', 'result after original base')
    assert task['binding']['head'] != sessions.git(root, 'rev-parse', 'HEAD')
    return root, task


def task_path(root, task):
    return sessions.session_dir(root, task['runtime'], task['session_id']) / (task['request_id'] + '.json')


def retained(root, task):
    directory = task_path(root, task).parent
    index = Path(sessions.git(root, 'rev-parse', '--git-path', 'index'))
    if not index.is_absolute():
        index = root / index
    return {'task': task_path(root, task).read_bytes(),
            'claim': (directory / (task['request_id'] + '.execution-claim')).read_bytes(),
            'index': index.read_bytes(), 'git_pointer': (root / '.git').read_bytes(),
            'head': sessions.git(root, 'rev-parse', 'HEAD'),
            'branch': sessions.git(root, 'branch', '--show-current'),
            'artifacts': sessions.artifact_inputs(root, 'session-' + task['request_id'])}


def test_prepared_capture_preserves_same_linked_task_and_original_base(prepared_linked, tmp_path):
    root, task = prepared_linked
    before = retained(root, task)
    with pytest.raises(ValueError, match='standalone'):
        pending.capture(root, tmp_path / 'old-path.json')
    update = importlib.import_module('ai_ops_kit.lifecycle.session_prepared_update')
    path = tmp_path / 'snapshot.json'
    result = update.capture(root, 'codex', 'owner', path)
    assert retained(root, task) == before
    saved = store.document(path)
    assert result['sha256'] == store.sha(path.read_bytes())
    assert saved['kind'] == 'prepared-session-update-snapshot'
    assert json.loads(store.raw(saved['task']))['binding'] == task['binding']
    assert saved['context']['binding']['head'] == before['head']
    assert saved['context']['binding']['head'] != task['binding']['head']


def test_prepared_capture_refuses_busy_request_without_mutation(prepared_linked, tmp_path):
    root, task = prepared_linked
    before = retained(root, task)
    update = importlib.import_module('ai_ops_kit.lifecycle.session_prepared_update')
    path = tmp_path / 'snapshot.json'
    with sessions.session_lock(task_path(root, task).parent / 'requests'):
        with pytest.raises(ValueError):
            update.capture(root, 'codex', 'owner', path)
    assert retained(root, task) == before and not path.exists()


@pytest.mark.parametrize('phase', ['running', 'claimed', 'unknown'])
def test_unknown_verification_is_not_disposed(prepared_linked, tmp_path, phase):
    root, task = prepared_linked
    task['verification'] = {'phase': phase, 'attempt': 'unconfirmed'}
    sessions.write(task_path(root, task), task)
    before = retained(root, task)
    update = importlib.import_module('ai_ops_kit.lifecycle.session_prepared_update')
    path = tmp_path / 'snapshot.json'
    with pytest.raises(ValueError):
        update.capture(root, 'codex', 'owner', path)
    assert retained(root, task) == before and not path.exists()


@pytest.fixture
def stock_prepared(tmp_path, monkeypatch):
    """Actual stock installer and controller; only provider readiness is a synthetic stub."""
    from ai_ops_kit.providers import codex_native
    kit = Path(__file__).resolve().parents[2]
    source = tmp_path / 'stock-source'
    source.mkdir()
    data = subprocess.run(['git', 'archive', 'HEAD'], cwd=kit, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(source, filter='data')
    sessions.git(source, 'init', '-q')
    sessions.git(source, 'config', 'user.email', 'fixture@example.invalid')
    sessions.git(source, 'config', 'user.name', 'Fixture')
    sessions.git(source, 'add', '-A')
    sessions.git(source, 'commit', '-qm', 'stock fixture source')
    primary = _make_child_repo(tmp_path / 'primary')
    env = dict(os.environ, PYTHONPATH='', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', AI_OPS_PYTHON=sys.executable, GIT_CONFIG_GLOBAL='/dev/null')
    env.pop('CODEX_HOME', None)

    def stock(*args):
        result = subprocess.run([sys.executable, '-P', str(source / 'installer/ai_ops.py'), *args],
                                cwd=primary, env=env, text=True, capture_output=True, timeout=180)
        assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]

    stock('init', str(primary))
    import yaml
    path = primary / '.ai-ops.yaml'
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault('standard', {})['team_session'] = 'required'
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    stock('update', '--in-place')
    sessions.git(primary, 'add', '-A')
    sessions.git(primary, 'add', '-f', '.ai/managed')
    sessions.git(primary, 'commit', '-qm', 'installed stock')
    root = tmp_path / 'linked-stock'
    sessions.git(primary, 'worktree', 'add', '-b', 'prepared-stock', str(root))
    monkeypatch.setattr(codex_native, 'readiness', lambda *a, **k: {
        'ready': True, 'provider': 'codex-app-server', 'evidence': {'fixture': True}})
    monkeypatch.chdir(root)
    task = sessions.begin(root, 'codex', 'owner', 'Check saved results', 'fixture-turn')
    assert cli.main(['run', '--runtime', 'codex', '--session', 'owner', '--signals',
                     '{"task_type":"quick","size":"small","risk":"low"}']) == 1
    task = sessions.load(root, 'codex', 'owner')
    assert task['execution']['prepared'] is True
    (root / 'result.txt').write_text('committed product result\n')
    sessions.git(root, 'add', 'result.txt')
    sessions.git(root, 'commit', '-qm', 'product result')
    for name in ('ai_ops_kit/lifecycle/session_prepared_update.py',
                 'ai_ops_kit/lifecycle/project_session.py',
                 'ai_ops_kit/cli/project_session_migrate.py',
                 'ai_ops_kit/cli/project_session_resume.py',
                 'ai_ops_kit/cli/project_session_completion.py'):
        shutil.copyfile(kit / name, source / name)
    policy = source / sessions.POLICY
    policy.write_text(policy.read_text() + '\n<!-- Synthetic delivery qualification. -->\n')
    sessions.git(source, 'add', '-A')
    sessions.git(source, 'commit', '-qm', 'qualified policy increment')
    return root, task, source, sessions.git(source, 'rev-parse', 'HEAD')


@pytest.mark.slow
def test_real_stock_prepared_update_retains_base_and_can_rollback(stock_prepared, tmp_path):
    from ai_ops_kit.cli import project_session_completion as completion, project_session_resume as resume
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, revision = stock_prepared
    before = retained(root, task)
    scope_before = completion.scope(task, sessions.binding(root))
    snapshot = tmp_path / 'stock-snapshot.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    applied = update.apply(root, snapshot, captured['sha256'], source, revision)
    saved = sessions.load(root, 'codex', 'owner')
    assert applied['phase'] == 'committed' and applied['accepted'] is False and applied['models'] == 0
    assert saved['request_id'] == task['request_id'] and saved['binding'] == task['binding']
    assert saved['execution'] == task['execution']
    after = retained(root, saved)
    for key in ('claim', 'index', 'git_pointer', 'head', 'branch', 'artifacts'):
        assert after[key] == before[key], key
    resume.check(root, saved)
    env = update._environment(root / '.ai/managed')
    result = subprocess.run([sys.executable, '-P', '-m', 'ai_ops_kit.cli.project_session',
                             'run', '--runtime', 'codex', '--session', 'owner'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 1, result.stdout[-3000:] + result.stderr[-3000:]
    assert json.loads(result.stdout)['request_id'] == task['request_id']
    assert retained(root, sessions.load(root, 'codex', 'owner')) == after
    assert not sessions.verify(root, 'codex', 'owner')['accepted']
    scope_after = completion.scope(saved, sessions.binding(root))
    assert scope_after['base_revision'] == task['binding']['head'] != before['head']
    assert scope_after['managed_sha256'] != scope_before['managed_sha256']
    with pytest.raises(ValueError):
        update.apply(root, snapshot, captured['sha256'], source, revision)
    result = update.rollback(root, applied['id'], applied['plan_sha256'])
    assert result['phase'] == 'rolled_back'
    assert retained(root, task) == before
    resume.check(root, task)


@pytest.mark.slow
@pytest.mark.parametrize('damage', ['shared-driver', 'formatted-driver', 'major', 'old-source', 'new-hook'])
def test_incompatible_source_or_shared_driver_is_refused_before_installer(stock_prepared, tmp_path, damage):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, revision = stock_prepared
    if damage == 'shared-driver':
        sessions.git(root, 'config', 'merge.ai-ops-plan.driver', 'owner-only-driver %O %A %B')
    elif damage == 'formatted-driver':
        config = update._git_path(root, '--git-common-dir') / 'config'
        line = next(line for line in config.read_bytes().splitlines() if b'driver = python3' in line)
        config.write_bytes(config.read_bytes().replace(line, line.replace(b'= ', b'= "') + b'"'))
    elif damage == 'major':
        (source / 'VERSION').write_text('5.0.0\n')
        sessions.git(source, 'add', 'VERSION')
        sessions.git(source, 'commit', '-qm', 'major version fixture')
        revision = sessions.git(source, 'rev-parse', 'HEAD')
    elif damage == 'old-source':
        (source / 'ai_ops_kit/lifecycle/session_prepared_update.py').unlink()
        sessions.git(source, 'add', '-A')
        sessions.git(source, 'commit', '-qm', 'source without continuation capability')
        revision = sessions.git(source, 'rev-parse', 'HEAD')
    else:
        path = source / 'ai_ops_kit/lifecycle/project_session.py'
        text = path.read_text()
        assert '"timeout": 15' in text
        path.write_text(text.replace('"timeout": 15', '"timeout": 14'))
        sessions.git(source, 'add', '-A')
        sessions.git(source, 'commit', '-qm', 'different hook definition')
        revision = sessions.git(source, 'rev-parse', 'HEAD')
    before, git_before = retained(root, task), update.git_identity(root)
    installed = store.inventory(root, pending.INSTALL + ('.github', '.ai/runtime/backups'))
    snapshot = tmp_path / 'rejected-snapshot.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    with pytest.raises(ValueError):
        update.apply(root, snapshot, captured['sha256'], source, revision)
    assert retained(root, task) == before and update.git_identity(root) == git_before
    assert store.inventory(root, pending.INSTALL + ('.github', '.ai/runtime/backups')) == installed
    assert not list((root / store.AREA).glob('*/journal.json'))


@pytest.mark.slow
def test_old_verification_is_archived_and_concurrent_input_prevents_rollback(stock_prepared, tmp_path):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, revision = stock_prepared
    old = {'phase': 'finished', 'process_exit_code': 0, 'attempt': 'historical-not-current',
           'sha256': '1' * 64, 'review_digests': {'old': '2' * 64}}
    task['verification'] = old
    task['verification_history'] = [{'phase': 'failed', 'process_exit_code': 2}]
    sessions.write(task_path(root, task), task)
    snapshot = tmp_path / 'history-snapshot.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    applied = update.apply(root, snapshot, captured['sha256'], source, revision)
    saved = sessions.load(root, 'codex', 'owner')
    assert 'verification' not in saved
    assert saved['verification_history'] == task['verification_history'] + [old]
    assert saved['binding'] == task['binding']
    path = task_path(root, saved).parent / (saved['request_id'] + '.inputs') / 'new.json'
    path.parent.mkdir()
    path.write_text('{"new":"independent input"}')
    before = pending.protected_files(root)
    installed = store.inventory(root, pending.INSTALL)
    with pytest.raises(ValueError, match='claim|artifacts|session'):
        update.rollback(root, applied['id'], applied['plan_sha256'])
    assert pending.protected_files(root) == before
    assert store.inventory(root, pending.INSTALL) == installed


@pytest.mark.slow
def test_unknown_after_task_replace_recovers_only_through_explicit_rollback(stock_prepared, tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, revision = stock_prepared
    before = retained(root, task)
    snapshot = tmp_path / 'interrupted-snapshot.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    original = store.replace

    def interrupted(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path == task_path(root, task):
            raise OSError('synthetic fsync outcome after actual replacement')

    monkeypatch.setattr(store, 'replace', interrupted)
    with pytest.raises(OSError, match='actual replacement'):
        update.apply(root, snapshot, captured['sha256'], source, revision)
    assert task_path(root, task).read_bytes() != before['task']
    journal_path = next((root / store.AREA).glob('*/journal.json'))
    journal = store.document(journal_path)
    assert journal['phase'] == 'applying'
    with pytest.raises(ValueError, match='incomplete'):
        sessions.load(root, 'codex', 'owner')
    monkeypatch.setattr(store, 'replace', original)
    rolled = update.rollback(root, journal['id'], journal['plan_sha256'])
    assert rolled['phase'] == 'rolled_back' and retained(root, task) == before


@pytest.mark.slow
def test_parent_sitecustomize_cannot_replace_stock_imports(stock_prepared, tmp_path, monkeypatch):
    import venv
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, revision = stock_prepared
    polluted = tmp_path / 'polluted-interpreter'
    venv.EnvBuilder(with_pip=False, system_site_packages=False).create(polluted)
    site = polluted / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    marker = tmp_path / 'unexpected-site-effect'
    shadow = tmp_path / 'shadow'
    (shadow / 'ai_ops_kit').mkdir(parents=True)
    (shadow / 'ai_ops_kit/__init__.py').write_text('raise RuntimeError("unreviewed shadow imported")\n')
    (site / 'shadow.pth').write_text(f'import pathlib,sys; pathlib.Path({str(marker)!r}).write_text("executed"); sys.path.insert(0,{str(shadow)!r})\n')
    python = polluted / 'bin/python'
    result = subprocess.run([str(python), '-P', '-c', 'pass'], capture_output=True, timeout=5)
    assert result.returncode == 0 and marker.read_text() == 'executed'
    marker.unlink()
    monkeypatch.setattr(sys, 'executable', str(python))
    snapshot = tmp_path / 'isolated-snapshot.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    applied = update.apply(root, snapshot, captured['sha256'], source, revision)
    assert applied['phase'] == 'committed'
    assert not marker.exists(), 'parent .pth must not execute in probe, installer or smoke children'
    assert sessions.load(root, 'codex', 'owner')['binding'] == task['binding']


@pytest.mark.parametrize('cancel', [None, signal.SIGINT, signal.SIGTERM])
def test_blocked_install_is_bounded_and_never_restarted(prepared_linked, tmp_path, cancel):
    """Synthetic installer blocks in a real OS read; this is not stock qualification."""
    from test_project_session_resume_bounds import alive
    root, task = prepared_linked
    source = tmp_path / 'blocking-source'
    (source / 'installer').mkdir(parents=True)
    fifo, marker = tmp_path / 'blocked.fifo', tmp_path / 'entered.json'
    os.mkfifo(fifo)
    script = source / 'installer/ai_ops.py'
    script.write_text('import os,json\nfrom pathlib import Path\n'
                      f'fd=os.open({str(fifo)!r},os.O_RDWR)\n'
                      f'Path({str(marker)!r}).write_text(json.dumps({{"pid":os.getpid()}}))\n'
                      'os.read(fd,1)\n')
    kit = Path(__file__).resolve().parents[2]
    snapshot = tmp_path / 'blocked-snapshot.json'
    from ai_ops_kit.lifecycle import session_prepared_update as update
    captured = update.capture(root, 'codex', 'owner', snapshot)
    before = retained(root, task)
    # Replace only admission/probe for this process-control unit fixture. Actual
    # run_process, locks, intent/journal, OS blocking and cleanup remain unmocked.
    code = f'''from pathlib import Path
from ai_ops_kit.lifecycle import session_prepared_update as u
u._source=lambda source, revision: Path(source)
u._probe=lambda *a: {{"paths":[".ai/managed"]}}
u.apply(Path({str(root)!r}),Path({str(snapshot)!r}),{captured['sha256']!r},
        Path({str(source)!r}),"fixture-revision",timeout={1.5 if cancel is None else 30})
'''
    started = time.monotonic()
    parent = subprocess.Popen([sys.executable, '-P', '-c', code], cwd=tmp_path,
                              env=dict(os.environ, PYTHONPATH=str(kit)),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and parent.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), parent.communicate(timeout=3)[1].decode()
        pid = json.loads(marker.read_text())['pid']
        assert alive(pid), 'worker must actually reach the blocking syscall'
        if cancel is not None:
            parent.send_signal(cancel)
        parent.communicate(timeout=6)
        assert parent.returncode != 0
        assert time.monotonic() - started < 10
        assert not alive(pid)
        assert retained(root, task) == before
        with pytest.raises(ValueError, match='incomplete'):
            store.incomplete(root)
        journal = next((root / store.AREA).glob('*/journal.json'))
        assert store.document(journal)['phase'] == 'installing'
        assert not (journal.parent / 'plan.json').exists()
        with store.barrier(root, exclusive=True, recovery=True), pending._old_locks(root):
            assert retained(root, task) == before
    finally:
        if parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.communicate(timeout=5)


@pytest.mark.slow
def test_removed_stock_file_survives_interrupted_rollback(stock_prepared, tmp_path):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task, source, _ = stock_prepared
    relative = 'rules/ai/EvalTooling.md'
    target = root / '.ai/managed' / relative
    original = store.read(target)
    preserved = retained(root, task)
    sessions.git(source, 'rm', relative)
    sessions.git(source, 'commit', '-qm', 'retire managed fixture asset')
    snapshot = tmp_path / 'before-removal.json'
    captured = update.capture(root, 'codex', 'owner', snapshot)
    applied = update.apply(root, snapshot, captured['sha256'], source, sessions.git(source, 'rev-parse', 'HEAD'))
    assert not target.exists()
    program = """
import os, sys
from pathlib import Path
from ai_ops_kit.lifecycle import session_prepared_update as update
root, transaction, checksum, relative, moment = sys.argv[1:]
name = Path(relative).name
stock_link = os.link
def crash(source, destination, **options):
    if destination == name and moment == 'before':
        os._exit(71)
    stock_link(source, destination, **options)
    if destination == name:
        os._exit(72)
os.link = crash
update.rollback(Path(root), transaction, checksum)
"""
    env = update._environment(Path(update.__file__).resolve().parents[2])
    for moment, code in [('before', 71), ('after', 72)]:
        proc = subprocess.run([sys.executable, '-P', '-c', program, str(root), applied['id'],
                               applied['plan_sha256'], relative, moment], cwd=root,
                              env=env, timeout=120, capture_output=True)
        assert proc.returncode == code, proc.stderr[-2000:]
        if moment == 'before':
            assert not target.exists()
        else:
            assert target.read_bytes() == store.raw(original)
            assert target.stat().st_nlink == 2
    assert update.rollback(root, applied['id'], applied['plan_sha256'])['phase'] == 'rolled_back'
    assert target.stat().st_nlink == 1 and store.read(target) == original
    assert retained(root, task) == preserved


def test_create_only_rollback_preserves_racing_file(tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root = tmp_path.resolve()
    target = root / 'removed'
    source = root / 'original'
    source.write_bytes(b'original')
    link = os.link

    def race(*args, **kwargs):
        target.write_bytes(b'concurrent owner')
        return link(*args, **kwargs)

    monkeypatch.setattr(os, 'link', race)
    with pytest.raises(FileExistsError):
        update._restore_file(target, store.read(source), None, root / 'staging')
    assert target.read_bytes() == b'concurrent owner'


def test_partial_stage_write_never_exposes_partial_destination(tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root = tmp_path.resolve()
    original = root / 'original'
    original.write_bytes(b'bytes with original mode')
    original.chmod(0o751)
    before = store.read(original)
    dest, staging = root / 'removed', root / 'staging'
    fdopen = os.fdopen

    class FailingWriter:
        def __init__(self, fd, mode):
            self.handle = fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *exception):
            self.handle.close()

        def write(self, data):
            self.handle.write(data[:3])
            raise OSError('injected partial write')

    with monkeypatch.context() as patch:
        patch.setattr(os, 'fdopen', FailingWriter)
        with pytest.raises(OSError, match='partial write'):
            update._restore_file(dest, before, None, staging)
    assert not dest.exists()
    update._discard_restore_stage(dest, staging)
    update._restore_file(dest, before, None, staging)
    assert store.read(dest) == before and dest.stat().st_nlink == 1


def test_driver_rehearsal_git_error_is_a_clean_refusal(prepared_linked, tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import session_prepared_update as update
    root, task = prepared_linked
    before = retained(root, task)
    run = subprocess.run

    def fail_preview(argv, **kwargs):
        if argv[:3] == ['git', 'config', '--file']:
            return subprocess.CompletedProcess(argv, 1)
        return run(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'run', fail_preview)
    with pytest.raises(ValueError, match='could not rehearse'):
        update._check_driver(root, tmp_path, {'core.bare': 'false'})
    assert retained(root, task) == before
