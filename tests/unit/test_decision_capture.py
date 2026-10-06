import json
from pathlib import Path
import urllib.error

import pytest

from ai_ops_kit.devtools import decision_capture as cap
from ai_ops_kit.devtools import decision_eval as ev


@pytest.fixture
def data():
    return ev.load_dataset(Path(__file__).resolve().parents[2] / 'qualification/decision-plane/dataset.json')


def test_real_post_body_and_returned_decision(data):
    sent = []
    def post(body):
        sent.append(json.loads(body))
        option = sent[-1]['state']['options'][0]
        return {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': option, 'confidence': .6}},
                'usage': {'input_tokens': 10, 'output_tokens': 0}}
    result = cap.capture(data, 'test-secret', 'jev-test', post=post, input_price=.042)
    assert len(sent) == len(data['cases'])
    assert all('expected' not in s['state'] for s in sent)
    assert 'test-secret' not in json.dumps(result)
    assert result['providers'][0]['responses'][0]['decision'] == '0'
    assert result['providers'][0]['responses'][0]['estimated_cost_usd'] == pytest.approx(.00000042)
    assert ev.run(data, result)['providers']['jev']['status'] == 'measured'


def test_provider_failure_abstains_without_leaking_key(data):
    def post(body):
        raise urllib.error.URLError('test-secret')
    result = cap.capture(data, 'test-secret', 'jev-test', post=post)
    assert all(r['abstain'] and r['error'] for r in result['providers'][0]['responses'])
    assert 'test-secret' not in json.dumps(result)
    assert ev.run(data, result)['verdict'] != 'ship'


def test_missing_key_never_calls_provider(data):
    sent = []
    with pytest.raises(ValueError):
        cap.capture(data, None, 'jev-test', post=lambda b: sent.append(b))
    assert sent == []


def test_unbounded_response_is_failed_closed(data):
    def post(body):
        return {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': 'invented', 'confidence': .99}},
                'usage': {'input_tokens': 10, 'output_tokens': 0}}
    result = cap.capture(data, 'test-secret', 'jev-test', post=post)
    assert all(r['abstain'] for r in result['providers'][0]['responses'])


def test_redirect_does_not_forward_credentials():
    assert cap.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example') is None


@pytest.mark.parametrize('confidence', [None, True, float('nan')])
def test_jev_requires_numeric_confidence_and_retains_usage(data, confidence):
    def post(body):
        option = json.loads(body)['state']['options'][0]
        return {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': option, 'confidence': confidence}},
                'usage': {'input_tokens': 10, 'output_tokens': 0}}
    result = cap.capture(data, 'secret', 'jev-test', post=post, input_price=.042)
    row = result['providers'][0]['responses'][0]
    assert row['abstain'] and row['error']
    assert row['input_tokens'] == 10
    assert row['estimated_cost_usd'] == pytest.approx(.00000042)


def test_invalid_choice_retains_paid_usage(data):
    def post(body):
        return {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': 'invented', 'confidence': .9}},
                'usage': {'input_tokens': 10, 'output_tokens': 0}}
    row = cap.capture(data, 'secret', 'jev-test', post=post)['providers'][0]['responses'][0]
    assert row['abstain']
    assert row['input_tokens'] == 10


def test_free_service_never_forwards_real_key(data, monkeypatch):
    requests = []
    class Response:
        def __enter__(self):
            import io
            return io.StringIO(json.dumps({'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': '0', 'confidence': .9}}, 'usage': {'input_tokens': 10, 'output_tokens': 0}}))
        def __exit__(self, *args):
            pass
    class Opener:
        def open(self, req, timeout):
            requests.append(req)
            return Response()
    monkeypatch.setattr(cap.urllib.request, 'build_opener', lambda *args: Opener())
    result = cap.capture(data, 'real-key-do-not-forward', 'jev-latest', service='classifier-free')
    assert requests
    assert all(r.full_url == cap.FREE_ENDPOINT and r.get_header('Authorization') == 'Bearer unused' for r in requests)
    assert 'real-key-do-not-forward' not in json.dumps(result)
    assert result['providers'][0]['endpoint'] == cap.FREE_ENDPOINT
    assert result['providers'][0]['responses'][0]['actual_cost_usd'] == 0
