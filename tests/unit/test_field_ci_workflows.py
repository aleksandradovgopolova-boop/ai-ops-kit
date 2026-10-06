"""Регрессии реальных Garden CI: пустой expression, защищённый main, чужой язык."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
TEMPLATES = KIT / 'templates' / 'ci'


def _workflow(name):
    return yaml.safe_load((TEMPLATES / name).read_text(encoding='utf-8'))


def _detect(tmp_path, files, override=''):
    root = tmp_path / 'child'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    for file in files:
        p = root / file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# fixture\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True)
    # Доказательство входа: исходники действительно отслеживаются, без mock git.
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files']).decode().splitlines()
    assert sorted(tracked) == sorted(files)
    before = subprocess.check_output(['git', '-C', str(root), 'diff', '--cached', '--binary'])
    step = _workflow('ai-ops-codeql.yml')['jobs']['languages']['steps'][1]['run']
    script = step.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    output = tmp_path / 'output'
    result = subprocess.run([sys.executable, '-c', script], cwd=root,
                            env={**os.environ, 'GITHUB_OUTPUT': str(output),
                                 'CODEQL_LANGUAGES': override},
                            capture_output=True, text=True, timeout=30)
    assert subprocess.check_output(['git', '-C', str(root), 'diff', '--cached', '--binary']) == before
    return result, output


@pytest.mark.parametrize(('files', 'languages'), [
    (['api/book.py', '.ai/managed/demo.js'], ['python']),
    (['js/dk-select.js', '.ai/managed/kit.py'], ['javascript-typescript']),
    (['api/book.py', 'web/src/book.ts'], ['javascript-typescript', 'python']),
    (['src/main.mts', 'src/service.cts'], ['javascript-typescript']),
    (['README.md', '.ai/managed/kit.py', 'node_modules/tool.js', 'types/book.d.ts', 'types/book.d.mts', 'types/book.d.cts'], []),
])
def test_codeql_runs_delivered_detection_without_scanning_kit(tmp_path, files, languages):
    result, output = _detect(tmp_path, files)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text().removeprefix('languages=')) == languages
    if not languages:
        assert 'SAST не подтверждён' in result.stdout


@pytest.mark.parametrize('override', ['["unknown"]', '[]', '{"python": true}', 'null', 'not-json', '[1]'])
def test_codeql_invalid_override_is_not_a_green_skip(tmp_path, override):
    result, output = _detect(tmp_path, ['api/book.py'], override)
    assert result.returncode != 0
    assert not output.exists()


def test_codeql_explicit_language_is_used(tmp_path):
    result, output = _detect(tmp_path, ['service.go'], '["go"]')
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text().removeprefix('languages=')) == ['go']


def test_codeql_matrix_uses_detected_product_languages():
    job = _workflow('ai-ops-codeql.yml')['jobs']['analyze']
    assert job['needs'] == 'languages'
    assert job['if'] == "needs.languages.outputs.languages != '[]'"
    assert job['strategy']['matrix']['language'] == '${{ fromJSON(needs.languages.outputs.languages) }}'


def test_coverage_workflow_cannot_write_protected_main():
    workflow = _workflow('ai-ops-feature-coverage.yml')
    assert workflow['permissions'] == {'contents': 'read'}
    steps = workflow['jobs']['feature-coverage']['steps']
    commands = '\n'.join(step.get('run', '') for step in steps)
    assert not re.search(r'\bgit\s+(push|commit|add)\b', commands)
    artifact = next(s for s in steps if s.get('uses') == 'actions/upload-artifact@v4')
    assert artifact['if'] == 'always()'
    assert artifact['with']['path'] == '.ai/feature-coverage-baseline.yaml'
    assert artifact['with']['include-hidden-files'] is True
    assert '--seed' in commands  # существующий ratchet/FAIL не удалён вместе с push


def test_no_template_has_empty_expression_even_in_shell_comment():
    offenders = [p.name for p in TEMPLATES.glob('*.yml')
                 if re.search(r'\$\{\{\s*\}\}', p.read_text(encoding='utf-8'))]
    assert offenders == [], f'GitHub разбирает expressions также в run-комментариях: {offenders}'


@pytest.mark.parametrize(('accepted', 'proposed', 'ok'), [
    (0, 1, False), (1, 0, True), (0, 0, True),
    (0, None, False), (0, 'broken', False), (None, 1, True),
    (None, None, True), (None, 'broken', False), ('broken', 0, False),
])
def test_pr_baseline_guard_executes_against_real_git_base(tmp_path, accepted, proposed, ok):
    root = tmp_path / 'baseline-child'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    for key, val in [('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid')]:
        subprocess.run(['git', '-C', str(root), 'config', key, val], check=True)
    p = root / '.ai/feature-coverage-baseline.yaml'
    p.parent.mkdir()
    def put(n):
        if n is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text('broken: [\n' if n == 'broken' else f'verified_orphans: {n}\n')
    put(accepted)
    (root / 'README.md').write_text('fixture\n')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'baseline'], check=True)
    base = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip()
    put(proposed)
    before = p.read_bytes() if p.exists() else None
    steps = _workflow('ai-ops-feature-coverage.yml')['jobs']['feature-coverage']['steps']
    step = next(s for s in steps if 'BASE_SHA' in s.get('env', {}))
    script = step['run'].split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    result = subprocess.run([sys.executable, '-c', script], cwd=root,
                            env={**os.environ, 'BASE_SHA': base}, capture_output=True, text=True)
    assert (result.returncode == 0) is ok, result.stderr
    assert (p.read_bytes() if p.exists() else None) == before
    assert subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip() == base
