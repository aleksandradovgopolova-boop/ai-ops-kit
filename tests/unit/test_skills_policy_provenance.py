"""Реальные границы skills/policy/provenance, без model calls."""
import hashlib
import json

import pytest
import yaml

from ai_ops_kit.providers import orchestrator as o
from ai_ops_kit.gates import gate_executor as ge
from ai_ops_kit.shared import ai_route
from ai_ops_kit.providers.skill_context import resolve_skills, SkillUnavailable


@pytest.fixture
def skill_workflow(tmp_path, monkeypatch):
    root = tmp_path / 'package'
    (root / 'registry').mkdir(parents=True)
    (root / 'manifest').mkdir()
    (root / 'skills/example').mkdir(parents=True)
    (root / 'skills/example/SKILL.md').write_text('SKILL_MARKER: проверяй контраст', encoding='utf-8')
    wf = {'QUICK': {'stages': [{'id': 'verify', 'owner': 'judge', 'review_mode': 'read-only', 'uses_skills': ['example']}], 'quality_gates': []}}
    (root / 'registry/workflows.yaml').write_text(yaml.safe_dump({'workflows': wf}))
    (root / 'registry/agents.yaml').write_text(yaml.safe_dump({'agents': []}))
    (root / 'manifest/ai-ops-manifest.yaml').write_text(yaml.safe_dump({'skills': {'shipped': [{'id': 'example', 'path': 'skills/example/SKILL.md'}]}}))
    monkeypatch.setattr(o, 'PKG', root)
    monkeypatch.setattr(ge, 'load_workflows', lambda: wf)
    monkeypatch.setattr(ge, 'load_gates', lambda: {})
    return root, tmp_path / 'child'


def test_declared_skill_reaches_provider_and_saved_artifact(skill_workflow):
    _, child = skill_workflow
    calls = []
    def provider(prompt):
        calls.append(prompt)
        return 'реально получен skill' if 'SKILL_MARKER' in prompt else 'missing'
    state, run_dir = o.run_workflow('QUICK', 'проверить экран', child, provider=provider, verbose=False)
    assert len(calls) == 1 and 'SKILL_MARKER' in calls[0]
    assert 'read-only' in calls[0]
    assert (run_dir / 'stage-verify.md').read_text() == 'реально получен skill'
    assert json.loads((run_dir / 'stage-verify.provenance.json').read_text())['kind'] == 'JUDGMENT'
    assert state['skill_context']['verify']['example']['sha256'] == hashlib.sha256('SKILL_MARKER: проверяй контраст'.encode()).hexdigest()


def test_missing_skill_blocks_before_provider(skill_workflow):
    root, child = skill_workflow
    (root / 'skills/example/SKILL.md').unlink()
    calls = []
    state, run_dir = o.run_workflow('QUICK', 'задача', child, provider=lambda p: calls.append(p), verbose=False)
    assert not calls
    assert state['status'] == 'blocked' and state['skill_failure']['stage'] == 'verify'
    assert not (run_dir / 'stage-verify.md').exists()


def test_external_skill_requires_actual_runtime_resolution(skill_workflow):
    root, _ = skill_workflow
    stage = {'uses_skills': ['external']}
    with pytest.raises(SkillUnavailable):
        resolve_skills(stage, root)
    assert resolve_skills(stage, root, resolver=lambda sid: 'EXTERNAL_MARKER') == {'external': 'EXTERNAL_MARKER'}
    def timeout(sid):
        raise TimeoutError()
    with pytest.raises(SkillUnavailable):
        resolve_skills(stage, root, resolver=timeout)


def test_manifest_escape_is_rejected(skill_workflow):
    root, _ = skill_workflow
    (root / 'manifest/ai-ops-manifest.yaml').write_text(yaml.safe_dump({'skills': {'shipped': [{'id': 'escape', 'path': '../secret'}]}}))
    with pytest.raises(SkillUnavailable):
        resolve_skills({'uses_skills': ['escape']}, root)


@pytest.mark.parametrize('signals,required', [
    ({'task_type': 'QUICK', 'risk': 'critical'}, 'security'),
    ({'task_type': 'QUICK', 'security_surface_changed': True}, 'security'),
    ({'task_type': 'QUICK', 'privileged': True}, 'security'),
    ({'task_type': 'QUICK', 'ui_changed': True}, 'accessibility_review'),
])
def test_empty_router_selection_cannot_remove_policy(monkeypatch, signals, required):
    monkeypatch.setattr(ge, 'deterministic_run', lambda validator: None)
    proposed = []
    assert proposed == []  # действительно получено предложение удалить весь набор
    report = ge.evaluate('QUICK', {}, gate_ids=proposed, signals=signals)
    assert required in report['evaluated_gates']
    assert 'implementation_verification' in report['evaluated_gates']
    assert report['blocked']


def test_router_failure_keeps_strong_policy(monkeypatch):
    monkeypatch.setattr(ge, 'deterministic_run', lambda validator: None)
    def timeout(signals):
        raise TimeoutError()
    monkeypatch.setattr(ai_route, 'route', timeout)
    report = ge.evaluate('QUICK', {}, gate_ids=[], signals={'risk': 'high'})
    assert report['policy_floor_workflow'] == 'CRITICAL' and report['policy_floor_fallback']
    assert report['blocked'] and 'security' in report['evaluated_gates']


@pytest.mark.parametrize('kind', ['JUDGMENT', 'REASONING', 'HUMAN_DECISION'])
def test_non_fact_cannot_close_deterministic_gate(monkeypatch, kind):
    gate = {'validator': 'test', 'blocking': True, 'required_evidence': ['tests_passed']}
    payload = {'status': 'pass', 'provided': ['tests_passed'], 'provenance': kind}
    assert payload['status'] == 'pass'  # входной ложный pass до реакции policy
    result = ge.evaluate_gate('tests', gate, {'tests': payload})
    assert result['status'] == 'fail' and result['provenance'] == kind
    assert not ge.evidence_verdict([result], {'tests': gate})['verified']


def test_human_decision_is_not_ai_recommendation():
    gate = {'human_approval': True, 'blocking': True}
    ai = ge.evaluate_gate('approval', gate, {'approval': {'status': 'pass', 'provenance': 'JUDGMENT'}})
    human = ge.evaluate_gate('approval', gate, {'approval': {'status': 'pass', 'source': 'human'}})
    assert ai['status'] == 'fail'
    assert human['status'] == 'pass' and human['provenance'] == 'HUMAN_DECISION'
    assert not ge.evidence_verdict([human], {'approval': gate})['verified']


def test_fact_provenance_reaches_machine_and_cli(capsys, monkeypatch):
    gate = {'validator': 'test', 'blocking': True}
    monkeypatch.setattr(ge, 'load_workflows', lambda: {'QUICK': {'quality_gates': ['tests']}})
    monkeypatch.setattr(ge, 'load_gates', lambda: {'tests': gate})
    monkeypatch.setattr(ge, 'deterministic_run', lambda v: ('pass', [], []))
    ge.main(['gate_executor', 'QUICK'])
    report = json.loads(capsys.readouterr().out)
    assert report['claim_origins']['tests'] == {'kind': 'FACT', 'description': 'факт проверки'}
    assert report['evidence_verdict']['verified']


def test_reviewer_collector_preserves_ai_origin():
    gate = {'validator': 'symbolic', 'blocking': True}
    payload = ge.evidence_from_reviewer_result(gate, {'status': 'pass'}, 'stage.json')
    assert payload['provenance'] == 'JUDGMENT'
    assert ge.evaluate_gate('tests', gate, {'tests': payload})['status'] == 'fail'


@pytest.mark.parametrize('value', [None, [], {}, 'UNKNOWN'])
def test_malformed_provenance_fails_closed(value):
    result = ge.evaluate_gate('test', {'validator': 'symbolic', 'blocking': True},
                              {'test': {'status': 'pass', 'provenance': value}})
    assert result['status'] == 'fail' and result['provenance'] is None


def test_reasoning_does_not_replace_independent_review():
    gate = {'review_mode': 'read-only', 'blocking': True}
    result = ge.evaluate_gate('review', gate, {'review': {'status': 'pass', 'provenance': 'REASONING'}})
    assert result['status'] == 'fail'


def test_source_cannot_relabel_ai_as_fact():
    result = ge.evaluate_gate('tests', {'validator': 'symbolic', 'blocking': True},
                              {'tests': {'status': 'pass', 'source': 'ai_judgment', 'provenance': 'FACT'}})
    assert result['status'] == 'fail' and result['provenance'] is None


def test_legacy_evidence_does_not_acquire_invented_origin():
    for gate in ({'validator': 'symbolic', 'blocking': True}, {'human_approval': True, 'blocking': True}):
        result = ge.evaluate_gate('gate', gate, {'gate': {'status': 'pass'}})
        assert result['provenance'] is None
        assert not ge.evidence_verdict([result], {'gate': gate})['verified']


def test_unconditional_human_gate_is_not_removed(monkeypatch):
    monkeypatch.setattr(ge, 'load_workflows', lambda: {'QUICK': {'quality_gates': []}})
    monkeypatch.setattr(ge, 'load_gates', lambda: {'approval': {'human_approval': True, 'blocking': True}})
    result = ge.evaluate('QUICK', {}, gate_ids=[])
    assert result['blocked'] and result['unmet_gates'] == ['approval']


def test_malformed_manifest_blocks_before_call(skill_workflow):
    root, child = skill_workflow
    (root / 'manifest/ai-ops-manifest.yaml').write_text('skills: [')
    calls = []
    state, _ = o.run_workflow('QUICK', 'задача', child, provider=lambda p: calls.append(p), verbose=False)
    assert not calls and state['status'] == 'blocked' and state['skill_failure']


def test_runtime_installed_skill_reaches_default_workflow_entry(skill_workflow):
    root, child = skill_workflow
    wf_path = root / 'registry/workflows.yaml'
    wf = yaml.safe_load(wf_path.read_text())
    wf['workflows']['QUICK']['stages'][0]['uses_skills'] = ['external']
    wf_path.write_text(yaml.safe_dump(wf))
    installed = child / '.claude/skills/external/SKILL.md'
    installed.parent.mkdir(parents=True)
    installed.write_text('INSTALLED_RUNTIME_SKILL')
    calls = []
    state, _ = o.run_workflow('QUICK', 'задача', child, provider=lambda p: calls.append(p) or 'output', verbose=False)
    assert state['status'] == 'done' and 'INSTALLED_RUNTIME_SKILL' in calls[0]


def test_unknown_legacy_review_is_not_labeled_as_ai_judgment():
    gate = {'review_mode': 'read-only', 'blocking': True}
    result = ge.evaluate_gate('review', gate, {'review': {'status': 'pass'}})
    verdict = ge.evidence_verdict([result], {'review': gate})
    assert verdict['ai_judgment'] == [] and verdict['unknown'] == ['review']
