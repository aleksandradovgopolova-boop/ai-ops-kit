"""Непросмотренные каталоги не дают ложную уверенность targeted selection."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.context import repo_graph
from ai_ops_kit.gates import verification_tiers as tiers

PROFILE = {'stacks': [{'language': 'python', 'commands': {'test': 'python -m pytest tests -q'}}]}


def write(root, name, text=''):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_directory_alias_really_imports_changed_code_and_requires_full(tmp_path):
    source = write(tmp_path, 'real/__init__.py', 'VALUE = 1\n')
    write(tmp_path, 'tests/test_direct.py', 'from real import VALUE\ndef test_direct(): assert VALUE == 1\n')
    write(tmp_path, 'tests/test_alias.py', 'from alias import VALUE\ndef test_alias(): assert VALUE == 1\n')
    (tmp_path / 'alias').symlink_to('real', target_is_directory=True)
    def run():
        return subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_alias.py', '-q'],
                              cwd=tmp_path, capture_output=True, text=True,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_ADDOPTS': ''})
    assert run().returncode == 0
    source.write_text('VALUE = 22\n')
    failed = run()
    assert failed.returncode == 1 and '22 == 1' in failed.stdout
    result = tiers.select_tests(['real/__init__.py'], tmp_path, profile=PROFILE)
    assert result['full_command'] and 'incomplete' in result['note']


def test_directory_traversal_error_requires_full_without_reading_hidden_source(tmp_path, monkeypatch):
    write(tmp_path, 'src/a.py', 'VALUE = 1\n')
    write(tmp_path, 'tests/test_a.py', 'from src.a import VALUE\n')
    hidden = write(tmp_path, 'hidden/consumer.py', 'from src.a import VALUE\n').parent
    original = os.scandir
    def scan(path):
        if Path(path) == hidden:
            raise PermissionError(13, 'controlled unreadable directory', str(hidden))
        return original(path)
    monkeypatch.setattr(os, 'scandir', scan)
    result = tiers.select_tests(['src/a.py'], tmp_path, profile=PROFILE)
    assert result['full_command'] and 'incomplete' in result['note']


@pytest.mark.parametrize('external', [False, True])
def test_directory_alias_is_recorded_without_following_target(tmp_path, monkeypatch, external):
    root = tmp_path / 'repo'
    write(root, 'src/a.py', 'VALUE = 1\n')
    target = tmp_path / 'outside' if external else root / 'real'
    write(target, 'secret.py', 'VALUE = 2\n')
    (root / 'alias').symlink_to(target, target_is_directory=True)
    original = os.scandir
    def scan(path):
        assert Path(path) != root / 'alias'
        assert not external or not Path(path).is_relative_to(target)
        return original(path)
    monkeypatch.setattr(os, 'scandir', scan)
    graph = repo_graph.build_graph(root, subdirs=None)
    assert 'alias' in graph['uncertainties']
    assert 'alias/secret.py' not in graph['files']


def test_excluded_symlink_tree_keeps_ordinary_targeted_selection(tmp_path):
    write(tmp_path, 'src/a.py', 'VALUE = 1\n')
    write(tmp_path, 'tests/test_a.py', 'from src.a import VALUE\n')
    (tmp_path / 'node_modules').symlink_to(tmp_path.parent / 'not-present', target_is_directory=True)
    result = tiers.select_tests(['src/a.py'], tmp_path, profile=PROFILE)
    assert not result['full_command'] and result['affected_tests'] == ['tests/test_a.py']


def test_explicit_symlink_subdir_is_not_traversed(tmp_path, monkeypatch):
    write(tmp_path, 'real/a.py', 'VALUE = 1\n')
    (tmp_path / 'alias').symlink_to('real', target_is_directory=True)
    original = os.scandir
    def scan(path):
        assert Path(path) not in (tmp_path / 'alias', tmp_path / 'real')
        return original(path)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'scandir', scan)
        graph = repo_graph.build_graph(tmp_path, subdirs=('alias',))
    assert graph['files'] == {} and graph['uncertainties'] == ['alias']


def test_javascript_alias_directory_also_requires_full(tmp_path):
    write(tmp_path, 'real/index.ts', 'export const value = 1;\n')
    write(tmp_path, 'tests/direct.test.ts', "import {value} from '../real';\n")
    write(tmp_path, 'tests/alias.test.ts', "import {value} from '../alias';\n")
    (tmp_path / 'alias').symlink_to('real', target_is_directory=True)
    profile = {'stacks': [{'language': 'typescript', 'commands': {'test': 'vitest run'}}]}
    result = tiers.select_tests(['real/index.ts'], tmp_path, profile=profile)
    assert result['full_command'] and 'incomplete' in result['note']
