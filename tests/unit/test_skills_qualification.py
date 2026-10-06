"""Квалификация actual prompts, fallback и независимого risk floor."""
import json
from pathlib import Path

import pytest

from ai_ops_kit.devtools import skills_qualification as q
from ai_ops_kit.providers.skill_context import SkillUnavailable

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / 'qualification/skills-safety/skills-corpus.json').read_text())


def test_audit_measures_actual_current_prompt_and_full_catalog():
    rows = q.context_audit(ROOT)
    live = [r for r in rows if 'blocked' not in r]
    assert len(live) > 80
    assert all(r['full_body_present'] and r['declared'] == r['recorded'] for r in live)
    assert sum(r['current_bytes'] for r in live) < sum(r['catalog_bytes'] for r in live)
    assert any('deep-research' in r.get('blocked', '') for r in rows)


@pytest.mark.parametrize('proposal', [None, {}, {'skills': [], 'confidence': 0.2},
                                      {'skills': ['unknown'], 'confidence': 1},
                                      {'skills': [], 'confidence': float('nan')}])
def test_uncertain_or_invalid_selection_expands_context(proposal):
    stage = q.stage_of(DATA['cases'][0], ROOT)
    bodies, result = q.selected_context(stage, ROOT, proposal)
    assert result['fallback'] and set(q.catalog(ROOT)).issubset(bodies)
    assert 'decision-support' in bodies


def test_omitted_critical_skill_is_restored_before_provider():
    stage = q.stage_of(DATA['cases'][0], ROOT)
    bodies, result = q.selected_context(stage, ROOT, {'skills': [], 'confidence': 1})
    prompt = q.o.build_role_prompt(stage, stage['owner'], {}, 'TASK', {}, bodies)
    observed = []
    def provider(actual):
        observed.append(actual)
        return 'received'
    assert provider(prompt) == 'received'
    assert len(observed) == 1 and bodies['decision-support'] in observed[0]
    assert result['mandatory_restored'] == ['decision-support']


def test_expanded_fallback_does_not_fake_missing_external_skill():
    with pytest.raises(SkillUnavailable, match='deep-research'):
        q.selected_context({'uses_skills': ['deep-research']}, ROOT, None)


def test_live_response_is_observed_before_oracle_and_oracle_not_in_prompt():
    case = DATA['cases'][0]
    calls = []
    answer = {'action': case['expected_action'], 'checks': [], 'executed': False}
    def invoke(execution, worker):
        calls.append(execution)
        assert 'expected_action' not in execution['instruction']
        assert 'forbidden' not in execution['instruction']
        return {'answer': answer, 'input_tokens': 100, 'latency_ms': 1}
    rows = q.run_live({'cases': [case]}, ROOT, {'model': 'test'}, invoke)
    assert len(calls) == 2 and all(r['result']['answer'] == answer for r in rows)
    assert all(r['rubric_pass'] for r in rows)
    assert rows[0]['prompt_bytes'] < rows[1]['prompt_bytes']


def test_worker_failure_is_not_a_quality_pass():
    rows = q.run_live({'cases': [DATA['cases'][0]]}, ROOT, {},
                      lambda *args: {'answer': None, 'error': 'runtime_timeout'})
    assert all(not r['rubric_pass'] for r in rows)


@pytest.mark.parametrize('risk', ['high', 'critical'])
def test_low_router_proposal_cannot_lower_ceremony_floor(monkeypatch, risk):
    monkeypatch.setattr('ai_ops_kit.shared.ai_route.route', lambda _: {'workflow': 'QUICK'})
    result = q.ge.evaluate('QUICK', {}, gate_ids=[], signals={'risk': risk, 'task_type': 'docs'})
    assert result['policy_floor_workflow'] == 'CRITICAL'
    assert {'security', 'code_review', 'architecture_review'}.issubset(result['evaluated_gates'])
    assert result['blocked']


def test_frozen_safety_corpus_preserves_every_expected_gate():
    data = json.loads((ROOT / 'qualification/skills-safety/safety-corpus.json').read_text())
    rows = q.run_safety(data)
    assert len(rows) == 12 and all('actual_report' in r for r in rows)
    assert not any(r['unsafe'] for r in rows)
    assert rows[-1]['actual_report']['policy_floor_fallback']


def test_stronger_router_floor_is_not_misreported_as_engineering(monkeypatch):
    monkeypatch.setattr('ai_ops_kit.shared.ai_route.route', lambda _: {'workflow': 'CRITICAL'})
    from ai_ops_kit.gates.spec_levels import classify
    signals = {'measurable_behavior': True, 'user_facing_change': True}
    assert classify(signals)['level'] == 2  # действительно выполняем ветку risk_floor
    result = q.ge.evaluate('QUICK', {}, gate_ids=[], signals=signals)
    assert result['policy_floor_workflow'] == 'CRITICAL'
    assert 'code_review' in result['evaluated_gates']


def test_strengthened_corpus_detects_disabled_ceremony_floor(monkeypatch):
    monkeypatch.setattr('ai_ops_kit.gates.spec_levels.classify', lambda _: {'level': 0})
    data = json.loads((ROOT / 'qualification/skills-safety/safety-corpus.json').read_text())
    rows = q.run_safety(data)
    unsafe = {r['id'] for r in rows if r['unsafe']}
    assert {'high-risk-empty', 'secret-boundary', 'destructive', 'irreversible'}.issubset(unsafe)


def test_malformed_worker_answer_cannot_satisfy_rubric():
    case = DATA['cases'][0]
    assert not q.grade(case, {'answer': {'action': case['expected_action'],
                                       'checks': ['unbounded'], 'executed': False}})
    assert not q.grade(case, {'answer': {'action': case['expected_action'],
                                       'checks': [], 'executed': False, 'extra': True}})


def test_selector_gets_only_catalog_metadata_not_body_or_oracle():
    case = DATA['cases'][0]
    stage = q.stage_of(case, ROOT)
    observed = []
    def invoke(execution, worker):
        observed.append(execution)
        assert 'expected_action' not in json.dumps(execution)
        assert '## Recommendation-first' not in json.dumps(execution)
        return {'answer': {'agent': stage['owner'], 'skills': stage['uses_skills'], 'confidence': 0.95}}
    rows = q.run_selection({'cases': [case]}, ROOT, {}, invoke)
    assert len(observed) == 1 and 'agents' in observed[0]['input']
    assert rows[0]['agent_match'] and rows[0]['skills_match']


def test_selector_refusal_expands_context_and_preserves_owner():
    case = DATA['cases'][0]
    rows = q.run_selection({'cases': [case]}, ROOT, {}, lambda *args: {'answer': None, 'error': 'runtime_timeout'})
    assert not rows[0]['agent_match'] and rows[0]['protection']['fallback']
    assert rows[0]['protected_agent'] == q.stage_of(case, ROOT)['owner']
    assert set(q.catalog(ROOT)).issubset(rows[0]['protected_skills'])
