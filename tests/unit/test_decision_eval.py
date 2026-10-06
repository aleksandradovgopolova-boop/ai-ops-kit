import copy
import json
from pathlib import Path

import pytest

from ai_ops_kit.devtools import decision_eval as ev

DATASET = Path(__file__).resolve().parents[2] / 'qualification/decision-plane/dataset.json'


@pytest.fixture
def data():
    return ev.load_dataset(DATASET)


def test_same_dataset_two_providers_and_separate_safety(data):
    report = ev.run(data)
    assert {r['provider'] for r in report['cases']} == {'current', 'heuristic'}
    assert len(report['cases']) == 2 * len(data['cases'])
    assert report['metrics']['current']['held_out']['ceremony']['accuracy'] == 1
    assert report['metrics']['current']['held_out']['model_effort']['abstain_rate'] == 1
    assert report['providers']['jev']['status'] == 'not_run'
    assert report['verdict'] == 'continue experiment'


def test_requests_do_not_leak_expected_floor_or_split(data):
    assert set(ev.request(data['cases'][0])) == {'id', 'task', 'signals', 'point', 'options'}


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 1.01, True])
def test_invalid_confidence_fails_closed(data, value):
    with pytest.raises(ValueError):
        ev.evaluate(data['cases'][0], {'decision': '0', 'confidence': value})


def test_observed_unsafe_and_high_confidence_error_are_separate(data):
    case = next(c for c in data['cases'] if c['allowed_by_policy'] == ['3'])
    row = ev.evaluate(case, {'decision': '0', 'confidence': .99})
    assert row['decision'] == '0'  # ответ действительно получен, не исправлен floor
    assert row['unsafe_downgrade'] and row['high_confidence_error']
    assert ev.summarize([row])['hcer'] == 1


def test_unknown_cost_and_confidence_are_not_zero(data):
    row = ev.evaluate(data['cases'][0], {'decision': '0'})
    metrics = ev.summarize([row])
    assert metrics['actual_cost_per_1k_usd'] is None
    assert metrics['hcer'] is None


def test_files_prove_real_decisions_and_cli_status(data, tmp_path):
    assert ev.main(['--dataset', str(DATASET), '--out', str(tmp_path)]) == 1
    report = json.loads((tmp_path / 'report.json').read_text())
    assert len(report['cases']) == len(data['cases']) * 2
    assert report['cases'][0]['decision'] == '0'
    assert (tmp_path / 'report.md').is_file()
    requests = json.loads((tmp_path / 'requests.json').read_text())
    assert requests['dataset_sha256'] == report['dataset_sha256']
    assert 'expected' not in requests['requests'][0]


def captures(data):
    return {'dataset_sha256': ev.run(data)['dataset_sha256'], 'providers': [
        {'id': 'jev', 'revision': 'test-only', 'provenance': 'unit fixture, not live',
         'responses': [{'case_id': c['id'], 'decision': c['expected'], 'confidence': .95} for c in data['cases']]}]}


def test_external_capture_same_corpus(data):
    report = ev.run(data, captures(data))
    assert report['metrics']['jev']['held_out']['ceremony']['accuracy'] == 1
    assert report['verdict'] != 'ship'


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'digest', 'invalid'])
def test_external_invalid_capture_fails_closed(data, fault):
    capture = captures(data)
    responses = capture['providers'][0]['responses']
    if fault == 'missing':
        responses.pop()
    elif fault == 'duplicate':
        responses[-1] = responses[0]
    elif fault == 'digest':
        capture['dataset_sha256'] = 'other'
    else:
        responses[0]['decision'] = 'unbounded'
    with pytest.raises(ValueError):
        ev.run(data, capture)


def test_external_heldout_unsafe_rejects(data):
    capture = captures(data)
    case = next(c for c in data['cases'] if c['split'] == 'held_out' and c['allowed_by_policy'] == ['3'])
    response = next(r for r in capture['providers'][0]['responses'] if r['case_id'] == case['id'])
    response['decision'] = '0'
    assert ev.run(data, capture)['verdict'] == 'reject'


def test_group_leakage_rejected(data, tmp_path):
    changed = copy.deepcopy(data)
    changed['cases'][-1]['group'] = changed['cases'][0]['group']
    path = tmp_path / 'dataset.json'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        ev.load_dataset(path)


def test_percentile_interpolates():
    assert ev.percentile([0, 10], .95) == 9.5
    assert ev.percentile([], .95) is None


@pytest.mark.parametrize('capture', [{}, [], {'providers': []}])
def test_empty_capture_rejected(data, capture):
    with pytest.raises(ValueError):
        ev.run(data, capture)


def test_arbitrary_provider_unsafe_is_rejected(data):
    capture = captures(data)
    capture['providers'][0]['id'] = 'jev-system-one-v1'
    case = next(c for c in data['cases'] if c['split'] == 'held_out' and c['allowed_by_policy'] == ['3'])
    next(r for r in capture['providers'][0]['responses'] if r['case_id'] == case['id'])['decision'] = '0'
    assert ev.run(data, capture)['verdict'] == 'reject'


def test_measured_source_has_actual_hashes(data):
    source = ev.run(data)['providers']['current']['source']
    assert source['revision']
    assert len(source['source_sha256']['ai_ops_kit/gates/spec_levels.py']) == 64


def test_floor_keeps_real_proposal_and_removes_inherited_confidence(data):
    case = next(c for c in data['cases'] if c['allowed_by_policy'] == ['3'])
    raw = {'decision': '0', 'confidence': .99, 'abstain': False}
    assert ev.evaluate(case, raw)['unsafe_downgrade']
    guarded = ev.apply_policy_floor(ev.request(case), raw)
    assert raw['decision'] == '0'
    assert guarded['raw_decision'] == '0'
    assert guarded['decision'] == '3' and guarded['confidence'] is None
    row = ev.evaluate(case, guarded)
    assert not row['unsafe_downgrade'] and row['raw_unsafe_downgrade']


def test_floor_uses_signals_and_not_annotation(data):
    case = data['cases'][0]
    guarded = ev.apply_policy_floor(ev.request(case), {'decision': None, 'abstain': True, 'error': 'timeout'})
    assert guarded['decision'] == '0' and guarded['fallback']
    assert guarded['error'] == 'timeout' and guarded['raw_decision'] is None


def test_floor_does_not_lower_higher_proposal(data):
    assert ev.apply_policy_floor(ev.request(data['cases'][0]), {'decision': '3', 'confidence': .8})['decision'] == '3'


@pytest.mark.parametrize('fault', ['options', 'decision', 'point'])
def test_floor_invalid_input_fails_closed(data, fault):
    req = ev.request(data['cases'][0])
    raw = {'decision': '0'}
    if fault == 'options':
        req['options'] = ['0', '3']
    elif fault == 'decision':
        raw['decision'] = 'invented'
    else:
        req['point'] = 'model_effort'
    with pytest.raises(ValueError):
        ev.apply_policy_floor(req, raw)


def test_guarded_comparison_retains_rejected_raw_provider():
    data = ev.load_dataset(DATASET.parent / 'independent-ceremony.json')
    responses = [{'case_id': c['id'], 'decision': c['expected'], 'confidence': .99, 'latency_ms': 10} for c in data['cases']]
    case = next(c for c in data['cases'] if c['split'] == 'held_out' and c['expected'] == '3')
    next(r for r in responses if r['case_id'] == case['id'])['decision'] = '0'
    capture = {'dataset_sha256': ev.run(data)['dataset_sha256'], 'providers': [
        {'id': 'jev', 'revision': 'test-only', 'provenance': 'unit fixture', 'responses': responses}]}
    derived = ev.with_policy_floor(data, capture)
    assert derived['providers'][0]['responses'] == responses
    report = ev.run(data, derived)
    assert report['candidate_verdicts']['jev'] == 'reject'
    assert report['candidate_verdicts']['jev_guarded'] == 'continue experiment'
    row = next(r for r in report['cases'] if r['provider'] == 'jev_guarded' and r['case_id'] == case['id'])
    assert row['raw_latency_ms'] == 10 and row['latency_ms'] >= 10
    assert row['raw_unsafe_downgrade'] and not row['unsafe_downgrade']
