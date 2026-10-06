"""Проверка будущего PR на настоящем рабочем дереве, без побочных записей."""
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.validation import validate_parallel_safety as safety

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / 'installer'))
import ai_ops as installer  # noqa: E402
import asset_ops  # noqa: E402


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, 'init', '-q', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'test')
    (tmp_path / 'README.md').write_text('initial\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'initial')
    git(tmp_path, 'switch', '-qc', 'feature')
    monkeypatch.setattr(installer, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(installer, 'PKG', PKG)
    # Воспроизвести namespace, оставленный тестом другого экземпляра установщика.
    monkeypatch.setattr(installer._core(), '_AO_NS', {'REPO_ROOT': PKG, 'PKG': PKG})
    # Фасад хранит текущий экземпляр установщика: привязать независимо от порядка тестов.
    installer._core()
    return tmp_path


def changes(root, data=True):
    (root / 'planning').mkdir()
    (root / 'planning/plan.yaml').write_text('work: []\n')
    if data:
        (root / '.ai/project').mkdir(parents=True)
        (root / '.ai/project/quality-baseline.json').write_text('{}\n')


def test_untracked_plan_and_json_rejected_by_validate(repo, monkeypatch, capsys):
    changes(repo)
    assert '.ai/project/quality-baseline.json' in safety.working_changed_files(repo, 'main')
    monkeypatch.setattr(installer._core(), 'run_validators', lambda checks: [])
    assert asset_ops.cmd_validate(['--base', 'main']) == 1
    assert 'СМЕШИВАЕТ' in capsys.readouterr().out


def test_document_and_plan_allowed(repo):
    changes(repo, data=False)
    (repo / 'README.md').write_text('changed\n')
    assert asset_ops._validate_pre_pr(['--base', 'main']) == 0


def test_missing_explicit_base_is_not_pass(repo, capsys):
    assert asset_ops._validate_pre_pr(['--base', 'missing']) == 1
    assert 'UNKNOWN' in capsys.readouterr().out


def test_missing_base_argument_rejected(repo):
    assert asset_ops._validate_pre_pr(['--base']) == 1


def test_automatic_base_checks_unstaged_and_staged_changes(repo):
    changes(repo)
    git(repo, 'add', 'planning/plan.yaml')
    assert asset_ops._validate_pre_pr([]) == 1


def test_validation_preserves_head_index_and_files(repo):
    changes(repo)
    git(repo, 'add', 'planning/plan.yaml')
    before = (git(repo, 'rev-parse', 'HEAD'), git(repo, 'diff', '--cached'),
              git(repo, 'status', '--porcelain'), (repo / 'planning/plan.yaml').read_bytes(),
              (repo / '.ai/project/quality-baseline.json').read_bytes())
    assert asset_ops._validate_pre_pr(['--base', 'main']) == 1
    after = (git(repo, 'rev-parse', 'HEAD'), git(repo, 'diff', '--cached'),
             git(repo, 'status', '--porcelain'), (repo / 'planning/plan.yaml').read_bytes(),
             (repo / '.ai/project/quality-baseline.json').read_bytes())
    assert before == after


def test_install_exception_and_ignored_files_preserved(repo):
    changes(repo)
    (repo / '.ai/managed').mkdir()
    (repo / '.ai/managed/VERSION').write_text('4.9.3\n')
    (repo / '.gitignore').write_text('ignored.py\n')
    (repo / 'ignored.py').write_text('unused\n')
    assert 'ignored.py' not in safety.working_changed_files(repo, 'main')
    assert asset_ops._validate_pre_pr(['--base', 'main']) == 0


def test_committed_branch_change_is_checked(repo):
    changes(repo)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'changes')
    assert asset_ops._validate_pre_pr(['--base', 'main']) == 1


def test_pre_pr_validator_and_registry_are_delivered():
    core = installer._core()
    assert core.is_runtime_asset('ai_ops_kit/validation/validate_parallel_safety.py')
    assert core.is_runtime_asset('registry/coordination-files.yaml')


def test_staged_change_hidden_by_worktree_is_checked(repo):
    changes(repo)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'baseline')
    git(repo, 'branch', '-f', 'main', 'HEAD')
    plan = repo / 'planning/plan.yaml'
    initial = plan.read_text()
    plan.write_text('work: [staged]\n')
    git(repo, 'add', 'planning/plan.yaml')
    plan.write_text(initial)
    (repo / '.ai/project/quality-baseline.json').write_text('{"changed": true}\n')
    assert 'planning/plan.yaml' in git(repo, 'diff', '--cached', '--name-only').decode()
    assert asset_ops._validate_pre_pr(['--base', 'main']) == 1


def test_direct_installer_validate_works_without_pythonpath(repo):
    import os
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, str(PKG / 'installer/ai_ops.py'),
                             'validate', '--base', 'main'], cwd=repo, env=env,
                            capture_output=True, text=True)
    assert 'Traceback' not in result.stderr
    assert 'PARALLEL-SAFETY-OK' in result.stdout
