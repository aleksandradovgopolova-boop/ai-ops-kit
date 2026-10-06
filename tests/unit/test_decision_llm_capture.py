import json
from pathlib import Path
import subprocess

import pytest

from ai_ops_kit.devtools import decision_eval as ev
from ai_ops_kit.devtools import decision_llm_capture as llm


def test_llm_actual_prompt_is_stripped_and_process_is_isolated():
    data = ev.load_dataset(Path(__file__).resolve().parents[2] / 'qualification/decision-plane/independent-ceremony.json')
    observed = []
    def runner(cmd, **kwargs):
        observed.append((cmd, kwargs))
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"decision":"0","confidence":0.7}'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 10}}]
        return subprocess.CompletedProcess(cmd, 0, stdout='\n'.join(json.dumps(e) for e in events))
    row = llm.one(ev.request(data['cases'][0]), 'test-only', runner=runner, binary='codex')
    assert observed and 'expected' not in observed[0][1]['input']
    assert '--ephemeral' in observed[0][0] and 'read-only' in observed[0][0]
    assert row['decision'] == '0' and row['input_tokens'] == 100


def test_llm_runtime_error_never_becomes_valid_result():
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout='{"type":"turn.failed"}')
    with pytest.raises(ValueError):
        llm.one({'id': 'x', 'task': 'x', 'point': 'ceremony', 'signals': {}, 'options': ['0','1','2','3']},
                'test-only', runner=runner, binary='codex')


def test_llm_capture_uses_every_case_and_retains_actual_responses():
    data = ev.load_dataset(Path(__file__).resolve().parents[2] / 'qualification/decision-plane/independent-ceremony.json')
    seen = []
    def call(req, model):
        seen.append(req['id'])
        return {'decision': '0', 'confidence': .5, 'abstain': False}
    result = llm.capture(data, 'test-only', call=call)
    assert seen == [c['id'] for c in data['cases']]
    assert len(result['providers'][0]['responses']) == 24
    assert result['providers'][0]['responses'][0]['decision'] == '0'
    assert ev.run(data, result)['providers']['llm']['status'] == 'measured'


@pytest.mark.parametrize('fault', ['tool_started', 'tool_updated', 'confidence', 'decision'])
def test_invalid_answer_retains_observed_usage_and_any_tool_event_fails(fault):
    req = {'id': 'x', 'task': 'x', 'point': 'ceremony', 'signals': {}, 'options': ['0','1','2','3']}
    def runner(cmd, **kwargs):
        answer = {'decision': 'outside' if fault == 'decision' else '0',
                  'confidence': None if fault == 'confidence' else .7}
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 10}}]
        if fault.startswith('tool_'):
            events.insert(0, {'type': 'item.' + fault.split('_')[1], 'item': {'type': 'command_execution'}})
        return subprocess.CompletedProcess(cmd, 0, stdout='\n'.join(json.dumps(e) for e in events))
    with pytest.raises(llm.InvalidResponse) as exc:
        llm.one(req, 'test-only', runner=runner, binary='codex')
    assert exc.value.evidence['input_tokens'] == 100
