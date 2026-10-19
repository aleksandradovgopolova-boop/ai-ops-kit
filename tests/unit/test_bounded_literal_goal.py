"""Ordinary goal→plan→execution; controlled transport is not live field acceptance."""
from __future__ import annotations

import json
import re
import threading

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli, ai_ops_cli_commands as cmd
from ai_ops_kit.engine import atomic_planner
from ai_ops_kit.lifecycle import active_work as aw, workitem
from ai_ops_kit.shared import gitio, lifecycle_store

TASK = 'Replace `teh` with `the` in `aa.txt`, `bb.txt`.'


def _repo(root):
    root.mkdir(exist_ok=True)
    assert gitio.run(['init', '-q', '-b', 'main', str(root)])[0] == 0
    gitio.git(root, 'config', 'user.email', 'test@example.test')
    gitio.git(root, 'config', 'user.name', 'Test')
    (root / '.gitignore').write_text('features/\n.ai/\n')
    (root / '.ai-ops.yaml').write_text(yaml.safe_dump({'session_economy': {'auto_parallel_independent_roots': True}}))
    for file in ['aa.txt', 'bb.txt']:(root / file).write_text(f'teh value {file}\n')
    gitio.git(root, 'add', '.')
    assert gitio.git(root, 'commit', '-qm', 'base')[0] == 0
    gitio.git(root, 'remote', 'add', 'origin', 'https://github.com/example/child.git')
    return dict(task_type='typo', risk='low', size='small', task_text=TASK, execution_budget={'max_model_calls': 30})


def _prepare(root, signals, **kwargs):
    return atomic_planner.prepare_literal_goal(root, 'work', signals, None,
        session_identity='fixed-session', execution_policy={'author': True, 'review': True, 'max_steps': 40}, **kwargs)


def test_pure_workitem_factory_preserves_existing_start_contract(tmp_path):
    sig = dict(task_type='typo', risk='low', needs_tests=True)
    expected = workitem.build('work', TASK, signals=sig)
    assert not (tmp_path / 'work').exists()
    assert workitem.start(tmp_path, 'work', TASK, signals=sig) == expected
    assert yaml.safe_load((tmp_path / 'work/workitem.yaml').read_text()) == expected


@pytest.mark.parametrize('task', [TASK, 'Заменить `teh` на `the` в `aa.txt`, `bb.txt`.'])
def test_goal_compiler_builds_actual_admissible_plan_without_model_or_manual_graph(tmp_path, task):
    sig = _repo(tmp_path)
    sig['task_text'] = task
    original = gitio.git(tmp_path, 'rev-parse', 'HEAD')[1]
    assert not list(tmp_path.glob('features/*/work-graph.yaml'))
    assert _prepare(tmp_path, sig)
    auto = cmd._automatic_roots(tmp_path, 'work', sig, None,
        execution_policy={'author': True, 'review': True, 'max_steps': 40})
    assert [p['write_scope'] for p in auto['work_graph']['packages']] == [['aa.txt'], ['bb.txt']]
    assert all(p['depends_on'] == [] for p in auto['work_graph']['packages'])
    assert yaml.safe_load((tmp_path / 'features/work/workitem.yaml').read_text())['task'] == task
    assert auto['budget'].model_calls == 0 and len(auto['task_map']) == 2
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == original
    frozen = {p: p.read_bytes() for p in tmp_path.glob('features/*/*.yaml')}
    assert not _prepare(tmp_path, sig), 'existing versioned plan is never regenerated'
    assert {p: p.read_bytes() for p in frozen} == frozen


@pytest.mark.parametrize('damage', ['budget', 'risk', 'approval', 'same', 'duplicate', 'traversal', 'code-file',
    'source-drift', 'missing', 'untracked', 'source-symlink', 'config-drift', 'foreign-claim', 'foreign-artifact'])
def test_recognized_unsafe_goal_has_no_plan_or_model_effects(tmp_path, damage):
    sig = _repo(tmp_path)
    if damage == 'budget':sig['execution_budget'] = {'max_cost': 1}
    elif damage == 'risk':sig['risk'] = 'high'
    elif damage == 'approval':sig['destructive'] = True
    elif damage == 'same':sig['task_text'] = TASK.replace('with `the`', 'with `teh`')
    elif damage == 'duplicate':sig['task_text'] = TASK.replace('`bb.txt`', '`aa.txt`')
    elif damage == 'traversal':sig['task_text'] = TASK.replace('`bb.txt`', '`../bb.txt`')
    elif damage == 'code-file':sig['task_text'] = TASK.replace('`bb.txt`', '`bb.py`')
    elif damage == 'source-drift':(tmp_path / 'aa.txt').write_text('teh uncommitted\n')
    elif damage == 'missing':(tmp_path / 'aa.txt').unlink()
    elif damage == 'untracked':
        gitio.git(tmp_path, 'rm', '--cached', 'aa.txt');gitio.git(tmp_path, 'commit', '-qm', 'untracked')
    elif damage == 'source-symlink':
        (tmp_path / 'aa.txt').unlink();(tmp_path / 'aa.txt').symlink_to(tmp_path / 'bb.txt')
    elif damage == 'config-drift':
        p = tmp_path / '.ai-ops.yaml';p.write_bytes(p.read_bytes() + b'\n# uncommitted\n')
    elif damage == 'foreign-claim':
        assert aw.register(aw.shared_registry_path(tmp_path), 'foreign', 'ai-ops/foreign', ['aa.txt'],
            'other-session', child_root=tmp_path) == 0
    else:
        p = tmp_path / 'features/work/run-settings.yaml';p.parent.mkdir(parents=True);p.write_text('foreign')
    before = {p: p.read_bytes() for p in tmp_path.glob('features/*/*.yaml')}
    with pytest.raises(ValueError):_prepare(tmp_path, sig)
    assert {p: p.read_bytes() for p in tmp_path.glob('features/*/*.yaml')} == before
    assert not list(tmp_path.glob('features/*/work-graph.yaml'))
    assert not (aw.shared_registry_path(tmp_path).parent / 'budgets').exists()


def test_unknown_goal_and_default_disabled_leave_ordinary_route_and_artifacts_untouched(tmp_path):
    sig = _repo(tmp_path)
    assert not _prepare(tmp_path, dict(sig, task_text='Implement a new product feature'))
    p = tmp_path / '.ai-ops.yaml';p.write_text(yaml.safe_dump({'session_economy': {}}))
    assert not _prepare(tmp_path, sig)
    assert not (tmp_path / 'features').exists()


def test_partial_plan_persistence_resumes_only_matching_files_without_overwrite(tmp_path, monkeypatch):
    sig = _repo(tmp_path)
    write = lifecycle_store.durable_create_batch
    saved = []
    def partial(root, documents):
        first = next(iter(documents))
        assert write(root, {first: documents[first]})['ok']
        saved.append((tmp_path / first, (tmp_path / first).stat().st_ino))
        return {'ok': False, 'error': 'controlled interruption after first artifact'}
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, 'durable_create_batch', partial)
        with pytest.raises(ValueError, match='plan barrier'):_prepare(tmp_path, sig)
    assert not (tmp_path / 'features/work/work-graph.yaml').exists()
    assert _prepare(tmp_path, sig)
    assert saved[0][0].stat().st_ino == saved[0][1]


def test_ordinary_cli_goal_builds_and_executes_isolated_plan_with_exact_fan_in(tmp_path, monkeypatch):
    from ai_ops_kit.providers import orchestrator
    from ai_ops_kit.engine import execution_pipeline
    from ai_ops_kit.delivery import pr_open
    sig = _repo(tmp_path)
    (tmp_path / 'pyproject.toml').write_text("[project]\nname='fixture'\nversion='0.0.1'\n")
    (tmp_path / 'check.py').write_text("from pathlib import Path\nimport subprocess\n"
        "texts=[Path(p).read_text() for p in ('aa.txt','bb.txt')]\n"
        "assert all(t.startswith(('teh value ','the value ')) for t in texts)\n"
        "branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()\n"
        "assert (all if branch=='ai-ops/work' else any)(t.startswith('the value ') for t in texts)\n")
    cfg = yaml.safe_load((tmp_path / '.ai-ops.yaml').read_text())
    cfg['verification'] = {'commands': {'test': 'python3 check.py'}}
    (tmp_path / '.ai-ops.yaml').write_text(yaml.safe_dump(cfg))
    gitio.git(tmp_path, 'add', '.');assert gitio.git(tmp_path, 'commit', '-qm', 'fixture verification')[0] == 0
    base = gitio.git(tmp_path, 'rev-parse', 'HEAD')[1]
    source = {p: (tmp_path / p).read_bytes() for p in ['aa.txt', 'bb.txt', '.ai-ops.yaml']}
    barrier, lock, starts, counts = threading.Barrier(2), threading.Lock(), [], {}
    def transport(prompt):
        found = re.search(r'Replace `teh` with `the` in `(aa|bb)\.txt`', prompt)
        assert found, prompt[:300]
        name = found[1] + '.txt'
        with lock:
            counts[name] = counts.get(name, 0) + 1
            step = counts[name]
            if step == 1:starts.append(name)
        if step == 1:
            barrier.wait(timeout=30)
            return json.dumps({'op': 'write', 'path': name, 'content': source[name].decode().replace('teh', 'the')})
        return json.dumps({'done': True, 'summary': 'literal text correction', 'behavior_unchanged': 'plain text spelling only'})
    monkeypatch.setattr(orchestrator, 'make_provider', lambda *a, **k: transport)
    monkeypatch.setattr(execution_pipeline, '_reverify_against_current_target', lambda *a: {'stale': False, 'verdict': 'controlled-external-target'})
    monkeypatch.setattr(pr_open, 'open_draft_pr', lambda root, branch, **k: {'status': 'opened',
        'head_sha': gitio.git(root, 'rev-parse', 'HEAD')[1], 'number': 7, 'url': 'https://github.com/example/child/pull/7'})
    assert not (tmp_path / 'features').exists()
    rc = ai_ops_cli.main(['do', TASK, str(tmp_path), '--feature', 'work', '--provider', 'mock', '--signals', json.dumps(sig)])
    rep = json.loads((tmp_path / 'features/work/parallel-report.json').read_text())
    assert rc == 0, rep
    assert sorted(starts) == ['aa.txt', 'bb.txt'] and counts == {'aa.txt': 2, 'bb.txt': 2}
    assert rep['budget']['model_calls'] == 4
    assert rep['aggregate']['tested_revision'] == rep['integration_sha'] and rep['aggregate']['all_pass']
    integration = rep['integration_source']['integration_clone']
    for p, raw in source.items():
        assert (tmp_path / p).read_bytes() == raw
        if p.endswith('.txt'):assert gitio.git(integration, 'show', f'HEAD:{p}')[1] == raw.decode().replace('teh', 'the').strip()
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == base
    entry = aw.load(aw.shared_registry_path(tmp_path))['active'][0]
    assert entry['budget_binding']['kind'] == 'GoalBudgetBinding'
    assert entry['auto_admission']['graph_path'] == 'features/work/work-graph.yaml'
    assert all(r['runner_started_at'] and r['runner_finished_at'] for r in rep['trace'])
