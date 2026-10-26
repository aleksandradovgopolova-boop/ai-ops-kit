"""Регрессия реального пути scanner → graph → selector."""
from pathlib import Path

from ai_ops_kit.context import repo_graph
from ai_ops_kit.gates import verification_tiers

ROOT = Path(__file__).resolve().parents[2]


def test_security_fallback_imports_have_known_targets():
    scanner = ROOT / 'ai_ops_kit/security/security_scan.py'
    assert repo_graph._dependency_uncertainty(scanner) is None
    import ast
    targets, complete = repo_graph._known_file_spec_targets(scanner, ast.parse(scanner.read_text()))
    assert complete
    assert {p.name for p in targets} == {
        'secret_formats.py', 'scan_secret_noise.py', 'scan_sql_template.py',
        'scan_prose.py', 'scan_exec_call.py', 'scan_inline_code.py',
        'scan_vendor.py', 'scan_deps.py',
    }


def test_real_secret_formats_change_selects_scanner_tests():
    result = verification_tiers.select_tests(
        ['ai_ops_kit/shared/secret_formats.py'], str(ROOT), lifecycle_intent='draft',
        profile={'stacks': [{'language': 'python', 'commands': {'test': 'python -m pytest tests/ -q'}}]},
    )
    assert result['tier'] == 'affected', result['note']
    assert not result['full_command']
    assert 0 < len(result['affected_tests']) < len(list((ROOT / 'tests').rglob('test_*.py')))
    assert any('security_scan' in path for path in result['affected_tests'])


def test_missing_fallback_target_remains_dynamic(tmp_path):
    import shutil
    scanner = ROOT / 'ai_ops_kit/security/security_scan.py'
    copy = tmp_path / 'ai_ops_kit/security/security_scan.py'
    copy.parent.mkdir(parents=True)
    shutil.copy2(scanner, copy)
    assert repo_graph._dependency_uncertainty(copy) == 'dynamic'
