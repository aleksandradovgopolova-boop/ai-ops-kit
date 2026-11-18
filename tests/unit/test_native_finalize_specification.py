"""Native specification: real artifacts, honest evidence, no disabled CLI."""
import hashlib
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.engine import pipeline_evidence, pipeline_helpers, pipeline_authoring
from ai_ops_kit.gates import gate_executor, spec_levels

pytestmark = pytest.mark.unit
WID = 'native-spec-case'
SIGNALS = {'task_type': 'ENGINEERING', 'size': 'M', 'risk': 'medium'}


def native_project(root):
    (root/'.ai-ops.yaml').write_text('openspec:\n  enabled: false\n')
    path, _, _ = spec_levels.create_spec(root, WID, SIGNALS)
    doc = yaml.safe_load(path.read_text())
    for name in doc['sections']:
        doc['sections'][name] = {'status': 'complete', 'content': f'Конкретное описание {name} для этой задачи.'}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True))
    directory = root/'.ai/runplan'/WID
    directory.mkdir(parents=True)
    (directory/'requirements.yaml').write_text(yaml.safe_dump({
        'schema_version': 1, 'kind': 'requirements-artifact',
        'requirements': [{'id': 'R1', 'statement': 'Сохранять результат задачи',
                          'acceptance': ['После проверки сохранённый результат доступен']}]}))
    return path


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def gate(evidence, mode='native-spec-first'):
    definition = gate_executor.load_gates()['specification']
    return gate_executor.evaluate_gate('specification', definition, evidence,
                                      signals={'specification_validation': mode})


def test_native_specification_uses_real_artifacts_without_cli_or_writes(tmp_path, monkeypatch):
    path = native_project(tmp_path)
    assert path.is_file() and (tmp_path/'.ai/runplan'/WID/'requirements.yaml').stat().st_size > 0
    before = snapshot(tmp_path)
    calls = []
    monkeypatch.setattr(pipeline_evidence, '_openspec_validate', lambda *args: calls.append(args))
    evidence = pipeline_evidence._reevaluate_artifact_evidence(tmp_path, WID, ['specification'])
    assert calls == [] and snapshot(tmp_path) == before
    assert evidence['specification']['status'] == 'pass'
    assert set(evidence['specification']['provided']) == {'native_spec_valid', 'requirements_covered'}
    assert 'openspec_valid' not in evidence['specification']['provided']
    assert gate(evidence)['status'] == 'pass'


@pytest.mark.parametrize('mutation', ['empty-content', 'missing-requirements', 'invalid-requirements',
                                       'foreign-workitem', 'foreign-requirements', 'needs-human', 'broken-yaml'])
def test_native_specification_rejects_incomplete_or_foreign_artifacts(tmp_path, mutation):
    path = native_project(tmp_path)
    doc = yaml.safe_load(path.read_text())
    if mutation == 'empty-content':
        doc['sections']['requirements']['content'] = ''
    elif mutation == 'foreign-workitem':
        doc['workitem_id'] = 'another-task'
    elif mutation == 'needs-human':
        doc['sections']['requirements']['status'] = 'needs_human'
    if mutation == 'missing-requirements':
        (tmp_path/'.ai/runplan'/WID/'requirements.yaml').unlink()
    elif mutation == 'invalid-requirements':
        (tmp_path/'.ai/runplan'/WID/'requirements.yaml').write_text('requirements: []\n')
    elif mutation == 'foreign-requirements':
        requirement_path = tmp_path/'.ai/runplan'/WID/'requirements.yaml'
        data = yaml.safe_load(requirement_path.read_text());data['workitem_id'] = 'foreign-task'
        requirement_path.write_text(yaml.safe_dump(data))
    elif mutation == 'broken-yaml':
        path.write_text('sections: [unterminated')
    else:
        path.write_text(yaml.safe_dump(doc, allow_unicode=True))
    before = snapshot(tmp_path)
    evidence = pipeline_evidence._reevaluate_artifact_evidence(tmp_path, WID, ['specification'])
    assert snapshot(tmp_path) == before
    assert gate(evidence)['status'] == 'fail'
    assert 'openspec_valid' not in evidence.get('specification', {}).get('provided', [])


def test_native_evidence_cannot_close_default_or_unknown_gate_profile(tmp_path):
    native_project(tmp_path)
    evidence = pipeline_evidence._reevaluate_artifact_evidence(tmp_path, WID, ['specification'])
    assert gate(evidence, 'openspec')['status'] == 'fail'
    assert gate(evidence, 'unrecognized-validator')['status'] == 'fail'


@pytest.mark.parametrize('provided', [[], ['native_spec_valid'], ['requirements_covered']])
def test_native_gate_still_requires_every_declared_evidence_key(provided):
    assert gate({'specification': {'status': 'pass', 'provided': provided}})['status'] == 'fail'


@pytest.mark.parametrize('enabled', [False, True])
def test_actual_pipeline_uses_config_instead_of_authored_profile_signal(tmp_path, monkeypatch, enabled):
    from ai_ops_kit.engine import execution_pipeline, run_plan
    native_project(tmp_path)
    (tmp_path/'.ai-ops.yaml').write_text(yaml.safe_dump({'openspec': {'enabled': enabled}}))
    calls = []
    def cli(*args):
        calls.append(args)
        return True, True, 'synthetic successful CLI result'
    monkeypatch.setattr(pipeline_evidence, '_openspec_validate', cli)
    signals = {'task_type': 'QUICK', 'specification_validation': 'native-spec-first' if enabled else 'openspec'}
    plan = run_plan.build_plan(signals, workitem_id=WID)
    plan['gates'].append('specification')
    result = execution_pipeline.run_pipeline('Проверить имеющиеся артефакты', signals, tmp_path, None,
        plan=plan, feature=WID, reevaluate_only=True, install_deps=False)
    specification = next(g for g in result['gates']['gate_results'] if g['gate'] == 'specification')
    assert specification['status'] == 'pass'
    assert bool(calls) is enabled


@pytest.mark.parametrize('value', ['"false"', '0', '[]'])
def test_invalid_openspec_setting_does_not_select_native_mode(tmp_path, value):
    (tmp_path/'.ai-ops.yaml').write_text(f'openspec:\n  enabled: {value}\n')
    assert pipeline_helpers._specification_mode(tmp_path) == 'openspec'


def test_default_mode_executes_actual_cli_and_disabled_mode_never_does(tmp_path, monkeypatch):
    binary = tmp_path/'openspec'
    marker = tmp_path/'cli-invoked'
    binary.write_text(f'#!/bin/sh\nprintf invoked > "{marker}"\nexit 0\n')
    binary.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    assert pipeline_helpers._specification_mode(tmp_path) == 'openspec'
    available, ok, _ = pipeline_helpers._openspec_validate(tmp_path, WID)
    assert available and ok and marker.read_text() == 'invoked'
    marker.unlink()
    (tmp_path/'.ai-ops.yaml').write_text('openspec:\n  enabled: false\n')
    available, ok, reason = pipeline_helpers._openspec_validate(tmp_path, WID)
    assert not available and not ok and 'отключ' in reason
    assert not marker.exists()


def test_native_authoring_checks_existing_spec_without_new_model_or_openspec_tree(tmp_path):
    native_project(tmp_path)
    def forbidden(*args):
        pytest.fail('native specification must not invoke a model or disabled OpenSpec')
    before = snapshot(tmp_path)
    from ai_ops_kit.shared.budget import Budget
    evidence, entry = pipeline_authoring._run_spec_authoring(
        forbidden, tmp_path, {}, WID, 'Сохранить результат', Budget(), forbidden)
    assert entry['closed'] is True
    assert gate(evidence)['status'] == 'pass'
    assert snapshot(tmp_path) == before and not (tmp_path/'openspec').exists()
