import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from ai_ops_kit.devtools import decision_eval
from ai_ops_kit.gates import gate_executor
from ai_ops_kit.devtools.decision_provider import (
    CallbackDecisionProvider, DecisionReply, DecisionRequest, run_decision,
)


@pytest.fixture
def sample():
    return DecisionRequest({'risk': 'high', 'nested': {'value': ['original']}},
                           'Какой уровень?', ('0', '1', '2', '3'), 'ceremony')


def adapter(callback, name='rules', kind='deterministic'):
    return CallbackDecisionProvider(name, 'fixture-v1', kind, callback)


@pytest.mark.parametrize('kind,provenance', [('deterministic', 'FACT'), ('heuristic', 'JUDGMENT'), ('model', 'JUDGMENT')])
def test_provider_swap_same_bounded_consumer_and_audit(sample, kind, provenance):
    calls = []
    def choose(req, budget):
        calls.append((req.options, req.state['risk'], budget))
        return DecisionReply('selected', '3', .95 if kind != 'deterministic' else None)
    result = run_decision(sample, adapter(choose, kind=kind), budget_ms=1000)
    assert calls[0][:2] == (sample.options, 'high')  # вызов действительно состоялся
    assert 0 < calls[0][2] <= 1000
    assert result.status == 'selected' and result.decision == '3'
    assert result.provenance == provenance and result.provider == 'rules'
    record = json.loads(json.dumps(result.to_dict()))
    assert record['schema_version'] == 1 and record['decision_type'] == 'ceremony'
    assert record['attempts'][0]['revision'] == 'fixture-v1'
    assert len(record['attempts'][0]['request_sha256']) == 64
    assert not result.fallback


@pytest.mark.parametrize('reply', [DecisionReply('selected', 'invented', .99),
    DecisionReply('selected', '3', True), DecisionReply('selected', '3', float('nan')),
    DecisionReply('selected', '3', float('inf')), DecisionReply('selected', '3', 1.1),
    DecisionReply('selected', None), DecisionReply('abstain', '3'),
    DecisionReply('abstain'), DecisionReply('error', confidence=.99, reason='error'),
    {'status': 'selected', 'decision': '3', 'provenance': 'FACT'}])
def test_malformed_reply_fails_closed(sample, reply):
    result = run_decision(sample, adapter(lambda req, budget: reply), budget_ms=1000)
    assert result.status == 'error' and result.decision is None
    assert result.attempts[0].reason == 'invalid_response'


@pytest.mark.parametrize('exception,reason', [(TimeoutError('secret'), 'timeout'),
                                              (OSError('secret'), 'provider_error')])
def test_provider_failure_does_not_leak_exception_or_select(sample, exception, reason):
    calls = []
    def fail(req, budget):
        calls.append(req.question)
        raise exception
    result = run_decision(sample, adapter(fail), budget_ms=1000)
    assert calls == [sample.question]
    assert result.status == 'error' and result.decision is None
    assert result.attempts[0].reason == reason
    assert 'secret' not in json.dumps(result.to_dict())


def test_fallback_actual_invocation_preserves_refusal_and_original_input(sample):
    calls = []
    def first(req, budget):
        calls.append('primary')
        req.state['nested']['value'].append('mutated')
        return DecisionReply('abstain', reason='uncertain')
    def second(req, budget):
        calls.append(('fallback', req.state['nested']['value'][:]))
        return DecisionReply('selected', '3')
    result = run_decision(sample, adapter(first, 'primary', 'model'),
                          budget_ms=1000, fallback=adapter(second, 'fallback'))
    assert calls == ['primary', ('fallback', ['original'])]
    assert sample.state['nested']['value'] == ['original']
    assert result.status == 'selected' and result.fallback
    assert result.provider == 'fallback' and result.provenance == 'FACT'
    assert result.attempts[0].status == 'abstain'
    assert result.attempts[0].provenance == 'JUDGMENT'
    assert result.attempts[0].reason == 'uncertain'
    assert result.attempts[0].request_sha256 == result.attempts[1].request_sha256


def test_selected_never_invokes_fallback(sample):
    calls = []
    def fallback(req, budget):
        calls.append('unexpected')
        return DecisionReply('selected', '3')
    result = run_decision(sample, adapter(lambda req, budget: DecisionReply('selected', '3')),
                          budget_ms=1000, fallback=adapter(fallback))
    assert result.status == 'selected' and calls == [] and not result.fallback


def test_fallback_failure_stays_error(sample):
    calls = []
    def fail(req, budget):
        calls.append('fallback')
        raise TimeoutError
    result = run_decision(sample, adapter(lambda req, budget: DecisionReply('abstain', reason='uncertain')),
                          budget_ms=1000, fallback=adapter(fail, 'fallback'))
    assert calls == ['fallback']
    assert result.status == 'error' and result.decision is None and result.fallback
    assert len(result.attempts) == 2


def test_late_reply_rejected_without_starting_fallback(sample):
    calls = []
    def primary(req, budget):
        calls.append('primary')
        return DecisionReply('selected', '3')
    with patch('ai_ops_kit.devtools.decision_provider.time.monotonic', side_effect=[0, 0, 0, 2, 2, 2]):
        result = run_decision(sample, adapter(primary), budget_ms=1000,
                              fallback=adapter(lambda req, budget: calls.append('fallback')))
    assert calls == ['primary']
    assert result.status == 'error' and result.decision is None and not result.fallback
    assert result.attempts[0].reason == 'budget_exceeded'


@pytest.mark.parametrize('budget', [0, -1, True, float('nan'), float('inf')])
def test_invalid_budget_rejected_before_call(sample, budget):
    calls = []
    with pytest.raises(ValueError):
        run_decision(sample, adapter(lambda req, budget: calls.append('called')), budget_ms=budget)
    assert calls == []


@pytest.mark.parametrize('change', [{'options': ('0', '0')}, {'options': ()}, {'question': ''},
    {'state': {1: 'integer key'}}, {'state': {'tuple': (1, 2)}}, {'state': {'nan': float('nan')}}])
def test_invalid_request_rejected_before_call(sample, change):
    calls = []
    with pytest.raises(ValueError):
        run_decision(replace(sample, **change), adapter(lambda req, budget: calls.append('called')), budget_ms=1000)
    assert calls == []


def test_model_proposal_remains_judgment_and_policy_floor_is_external(sample):
    calls = []
    def unsafe(req, budget):
        calls.append('model')
        return DecisionReply('selected', '0', .99)
    result = run_decision(sample, adapter(unsafe, 'model', 'model'), budget_ms=1000)
    assert calls == ['model'] and result.decision == '0'  # реально получено до policy
    assert result.provenance == 'JUDGMENT'
    guarded = decision_eval.apply_policy_floor({'point': 'ceremony', 'signals': sample.state,
        'options': list(sample.options)}, {'decision': result.decision, 'confidence': result.confidence})
    assert guarded['decision'] == '3' and guarded['raw_decision'] == '0'
    gate = {'validator': 'test', 'blocking': True, 'required_evidence': ['tests_passed']}
    evidence = {'status': 'pass', 'provenance': result.provenance, 'provided': ['tests_passed']}
    judged = gate_executor.evaluate_gate('tests', gate, {'tests': evidence})
    assert judged['provenance'] == 'JUDGMENT' and judged['status'] == 'fail'
    assert not gate_executor.evidence_verdict([judged], {'tests': gate})['verified']


def test_existing_harness_really_invokes_contract():
    with patch('ai_ops_kit.devtools.decision_eval._current_rules', wraps=decision_eval._current_rules) as rules:
        response = decision_eval.current({'point': 'ceremony', 'task': 'Критичное изменение',
                                          'signals': {'risk': 'high'}, 'options': ['0', '1', '2', '3']})
    assert rules.call_count == 1
    assert response['decision'] == '3' and not response['abstain']
    assert response['decision_audit']['attempts'][0]['provider'] == 'current'


def test_expired_before_first_call_never_invokes_adapter(sample):
    calls = []
    with patch('ai_ops_kit.devtools.decision_provider.time.monotonic', side_effect=[0, 2]):
        result = run_decision(sample, adapter(lambda req, budget: calls.append('called')), budget_ms=1000)
    assert calls == [] and result.status == 'error' and result.decision is None
    assert result.attempts[0].reason == 'budget_exceeded'


def test_harness_provider_error_remains_error_in_metrics():
    with patch('ai_ops_kit.devtools.decision_eval._current_rules', side_effect=TimeoutError):
        response = decision_eval.current({'point': 'ceremony', 'task': 'Задача',
                                          'signals': {}, 'options': ['0', '1', '2', '3']})
    assert response['error'] == 'timeout' and response['abstain']
    assert response['decision_audit']['status'] == 'error'
