"""Компактная копия: исходники и исполнимое дерево остаются неизменны."""
import ast
import hashlib
import json
import os
import subprocess
import sys

import pytest

from test_installer import _load_installer
from _installer_helpers import _make_child_repo, _run_cli

pytestmark = pytest.mark.unit


@pytest.fixture
def installer():
    return _load_installer()


def test_projection_preserves_ast_lines_strings_and_directives(installer):
    raw = (b'#!/usr/bin/env python3\n# coding: utf-8\n'
           b'"""Module documentation."""\n'
           b'# Ordinary explanatory comment\n\n'
           b'# ruff: noqa: F401\n# custom-tool: keep\n'
           b'# SPDX-License-Identifier: MIT\n'
           b'# Copyright Example\n# All rights reserved.\n'
           b'VALUE = """\n# literal, not a comment\n"""\n'
           b'def answer():\n    """Callable documentation."""\n'
           b'    # Ordinary implementation note\n    return 42  # inline comment\n')
    out = installer.managed_content('ai_ops_kit/example.py', raw)
    assert b'Ordinary explanatory' not in out and b'Ordinary implementation' not in out
    assert ast.dump(ast.parse(raw, type_comments=True), include_attributes=True) == ast.dump(
        ast.parse(out, type_comments=True), include_attributes=True)
    for text in [b'ruff: noqa', b'custom-tool: keep', b'SPDX', b'Copyright', b'All rights reserved',
                 b'# literal, not a comment', b'# inline comment', b'#!/usr/bin/env', b'coding: utf-8']:
        assert text in out
    assert out.count(b'\n') == raw.count(b'\n')
    assert installer.managed_content('ai_ops_kit/example.py', out) == out


@pytest.mark.parametrize('path,raw', [
    ('ai_ops_kit/broken.py', b'# keep on parse failure\ndef broken(:\n'),
    ('templates/example.py', b'# product template comment\nVALUE=1\n'),
    ('registry/example.yaml', b'# configuration comment\nx: 1\n'),
])
def test_unparseable_or_non_engine_content_is_unchanged(installer, path, raw):
    assert installer.managed_content(path, raw) == raw


def test_real_copy_has_compact_checksum_executes_and_no_update_diff(tmp_path, installer, monkeypatch):
    source = tmp_path / 'source.py'
    raw = b'"""Runtime help."""\n# a large historical note\nVALUE = 42\n'
    source.write_bytes(raw)
    source.chmod(0o755)
    rel = 'ai_ops_kit/example.py'
    managed = tmp_path / 'managed'
    target = managed / rel
    target.parent.mkdir(parents=True)
    installer.copy_managed_file(source, target, rel)
    assert target.read_bytes() != raw and source.read_bytes() == raw
    assert target.stat().st_mode & 0o777 == 0o755
    result = subprocess.run([sys.executable, '-c',
                             'import runpy,sys; print(runpy.run_path(sys.argv[1])["VALUE"])', str(target)],
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == '42'
    monkeypatch.setattr(installer, 'MANAGED', managed)
    monkeypatch.setattr(installer._core()._load('delivery_ops'), 'managed_set', lambda: [(source, rel)])
    installer.write_checksums(managed)
    recorded = json.loads((managed / '.checksums.json').read_text())['files'][rel]
    assert recorded == hashlib.sha256(target.read_bytes()).hexdigest()
    assert installer.detect_drift(managed) == []
    assert installer.build_diff() == []
    source.write_bytes(raw + b'NEW_VALUE = 43\n')
    assert installer.build_diff()[0]['action'] == 'replace'


def test_real_install_has_ten_percent_reserve_and_same_python_ast(tmp_path, installer):
    child = _make_child_repo(tmp_path / 'child')
    result = _run_cli(child, 'init', '.')
    assert result.returncode == 0, result.stdout + result.stderr
    managed = child / '.ai' / 'managed'
    actual = sum(p.stat().st_size for p in managed.rglob('*') if p.is_file())
    budget = installer.delivery_budget()
    assert actual <= budget['ceilings']['volume_bytes'] * (1 - budget['warnings']['volume_reserve_fraction'])
    smaller = 0
    for source, rel in installer.managed_set():
        if rel.startswith('ai_ops_kit/') and rel.endswith('.py'):
            delivered = (managed / rel).read_bytes()
            assert ast.dump(ast.parse(source.read_bytes(), type_comments=True), include_attributes=True) == ast.dump(
                ast.parse(delivered, type_comments=True), include_attributes=True), rel
            smaller += len(delivered) < source.stat().st_size
    assert smaller > 0
    runtime = subprocess.run(
        [sys.executable, '-c',
         "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
         "import ai_ops_kit; assert Path(ai_ops_kit.__file__).is_relative_to(Path(sys.argv[1])); "
         "from ai_ops_kit.cli.ai_ops_cli import main; main(['--help'])", str(managed)],
        cwd=child, text=True, capture_output=True,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    assert runtime.returncode == 0, runtime.stdout + runtime.stderr


def test_legacy_raw_install_updates_and_second_diff_is_empty(tmp_path, installer):
    child = _make_child_repo(tmp_path / 'child')
    result = _run_cli(child, 'init', '.')
    assert result.returncode == 0, result.stdout + result.stderr
    managed = child / '.ai' / 'managed'
    # Предыдущая поставка копировала исходники побайтно; создаём её реальные файлы и checksum.
    for source, rel in installer.managed_set():
        if rel.startswith('ai_ops_kit/') and rel.endswith('.py'):
            (managed / rel).write_bytes(source.read_bytes())
    installer.write_checksums(managed)
    legacy_size = sum(p.stat().st_size for p in managed.rglob('*') if p.is_file())
    custom = child / '.ai' / 'custom' / 'owner.md'
    custom.write_text('Owner instructions\n')
    result = _run_cli(child, 'update', '--in-place', timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    compact_size = sum(p.stat().st_size for p in managed.rglob('*') if p.is_file())
    assert compact_size < legacy_size
    assert custom.read_text() == 'Owner instructions\n'
    checksums = json.loads((managed / '.checksums.json').read_text())['files']
    assert all(hashlib.sha256((managed / rel).read_bytes()).hexdigest() == digest
               for rel, digest in checksums.items())
    diff = _run_cli(child, 'diff')
    assert diff.returncode == 0, diff.stdout + diff.stderr
    assert 'diff пуст' in diff.stdout
