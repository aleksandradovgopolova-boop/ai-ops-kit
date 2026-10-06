import json
from pathlib import Path
import subprocess

import pytest

from ai_ops_kit.devtools import decision_eval as ev
from ai_ops_kit.devtools import decision_model_experiment as exp

ROOT = Path(__file__).resolve().parents[2] / 'qualification/decision-plane'


@pytest.fixture
def data():
    return ev.load_dataset(ROOT / 'model-routing-dataset.json')


@pytest.fixture
def config():
    return json.loads((ROOT / 'model-workers.json').read_text())


def proposal_capture(data):
    return {'dataset_sha256': ev.run(data)['dataset_sha256'], 'providers': [
        {'id': 'jev', 'revision': 'test-only', 'provenance': 'unit fixture', 'responses': [
            {'case_id': c['id'], 'decision': 'fast/low', 'confidence': .99, 'latency_ms': 1,
             'input_tokens': 10, 'output_tokens': 2} for c in data['cases']]}]}


def test_real_proposal_cannot_lower_high_risk_floor(data, config):
    case = next(c for c in data['cases'] if c['signals']['risk'] == 'high')
    raw = {'decision': 'fast/low', 'confidence': .99}
    assert ev.evaluate(case, raw)['unsafe_downgrade']
    selected = exp.select(ev.request(case), raw, config['workers'], .9)
    assert selected['raw_decision'] == 'fast/low'
    assert selected['decision'] == 'deep/high' and selected['independent_review_required']


def test_unavailable_strongest_stops_without_cheap_worker(data, config):
    case = next(c for c in data['cases'] if c['expected'] == 'strongest/high')
    selected = exp.select(ev.request(case), {'decision': 'fast/low', 'confidence': .99}, config['workers'], .9)
    assert selected['decision'] == 'human-required' and selected['worker_unavailable']


def test_low_confidence_returns_actual_baseline(data, config):
    case = next(c for c in data['cases'] if c['signals']['risk'] == 'medium')
    selected = exp.select(ev.request(case), {'decision': 'fast/low', 'confidence': .89}, config['workers'], .9)
    assert selected['fallback']
    assert selected['decision'] == exp.baseline(case['signals'])


def test_invalid_choice_fails_closed(data, config):
    with pytest.raises(ValueError):
        exp.select(ev.request(data['cases'][0]), {'decision': 'invented', 'confidence': .99}, config['workers'], .9)


def test_worker_prompt_has_no_oracle_and_actual_result_retained(data):
    observed = []
    def runner(cmd, **kwargs):
        observed.append((cmd, kwargs['input']))
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"accepted":[true,true,false,true]}'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 10}}]
        return subprocess.CompletedProcess(cmd, 0, stdout='\n'.join(json.dumps(e) for e in events))
    result = exp.invoke_worker(data['cases'][0]['execution'], {'model': 'test-only', 'effort': 'low'}, runner=runner, binary='codex')
    assert observed and 'expected_answer' not in observed[0][1]
    assert result['answer'] == {'accepted': [True,True,False,True]}
    assert result['input_tokens'] == 100
    assert 'model_reasoning_effort="low"' in observed[0][0]


def test_every_actual_worker_call_has_result_before_oracle_comparison(data, config):
    observed = []
    def call(execution, worker):
        observed.append(worker)
        return {'answer': {'wrong': True}, 'latency_ms': 10, 'input_tokens': 100, 'output_tokens': 10}
    report = exp.run(data, proposal_capture(data), config, call=call)
    assert observed and len(report['executions']) == len(observed)
    assert all(r['answer'] == {'wrong': True} for r in report['executions'])
    assert not any(r['downstream_correct'] for r in report['cases'])
    assert not any(r['unsafe_downgrade'] for r in report['cases'])
    assert all(r['decision'] == 'human-required' for r in report['cases'] if r['case_id'] == 'mr-destructive-approval')


def test_router_requests_have_context_and_no_expected_answer(data):
    req = ev.request(data['cases'][0])
    assert set(req['context']) == {'instruction', 'input'}
    assert 'expected_answer' not in json.dumps(req)


def test_explicit_human_floor_wins_over_critical_even_with_strongest_available(config):
    req = {'point': 'model_effort', 'options': exp.CHOICES,
           'signals': {'risk': 'critical', 'model_policy_floor': 'human-required'}}
    workers = {**config['workers'], 'strongest/high': {'model': 'test', 'effort': 'high'}}
    assert exp.select(req, {'decision': 'strongest/high', 'confidence': 1}, workers, .9)['decision'] == 'human-required'


def test_invalid_declared_floor_not_hidden_by_secret_boundary():
    with pytest.raises(ValueError):
        exp.floor({'secret_boundary': True, 'model_policy_floor': 'invented'})


@pytest.mark.parametrize("item_type,accepted", [("error", True), ("command_execution", False)])
def test_warning_is_retained_but_tool_use_fails_closed(data, item_type, accepted):
    def runner(cmd, **kwargs):
        events = [{"type": "item.completed", "item": {"type": item_type, "message": "diagnostic"}},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
                  {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}]
        return subprocess.CompletedProcess(cmd, 0, stdout="\n".join(json.dumps(e) for e in events))
    result = exp.invoke_worker(data["cases"][0]["execution"], {"model": "test", "effort": "low"}, runner=runner, binary="codex")
    assert (result["answer"] == {"ok": True}) is accepted
    assert result["input_tokens"] == 12
    assert result["raw_events"][0]["item"]["type"] == item_type


def test_worker_timeout_is_saved_failure_without_fabricated_usage(data):
    def runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
    result = exp.invoke_worker(data["cases"][0]["execution"], {"model": "test", "effort": "low"}, runner=runner, binary="codex")
    assert result["error"] == "runtime_timeout"
    assert result["answer"] is None
    assert "input_tokens" not in result
    assert result["latency_ms"] >= 0


@pytest.mark.parametrize("stdout", ['[]', '{"type":"turn.completed","usage":null}', '{"type":"item.completed","item":null}', 'invalid-json'])
def test_malformed_worker_stream_is_saved_failure(data, stdout):
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout)
    result = exp.invoke_worker(data["cases"][0]["execution"], {"model": "test", "effort": "low"}, runner=runner, binary="codex")
    assert result["answer"] is None
    assert result["error"] == "invalid_runtime_result"
