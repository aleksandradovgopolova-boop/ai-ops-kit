"""Synthetic transport fixtures, not real humans, adversarial execution or live acceptance."""
import hashlib
import json
import subprocess

import pytest
import yaml

from ai_ops_kit.checks import reviewer_result
from ai_ops_kit.cli import project_session_completion as completion
from ai_ops_kit.engine import pipeline_evidence, pipeline_helpers, reviewer_handoff
from ai_ops_kit.gates import gate_executor

pytestmark = pytest.mark.unit


@pytest.fixture
def packet(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q')
    source = tmp_path/'result.py'
    source.write_text('VALUE = 0\n')
    git('add', 'result.py')
    git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    source.write_text('VALUE = 7\n')
    git('add', 'result.py')
    git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'result')
    head = git('rev-parse', 'HEAD')
    expected = {'workitem_id': 'session-' + 'a'*32, 'request_id': 'a'*32,
        'writer_session': 'codex:writer-fixture', 'base_revision': base, 'reviewed_revision': head,
        'source_sha256': '1'*64, 'inputs_sha256': '2'*64, 'artifacts_sha256': '3'*64}
    handoff = tmp_path/'.ai/runtime/fixture.reviews'
    report = tmp_path/'.ai/runtime/adversarial-fixture.json'
    report.parent.mkdir(parents=True)
    report.write_text('{"fixture_only": true, "not_live_acceptance": true}\n')
    required = gate_executor.load_gates()['ai_red_team']['required_evidence']
    verdict = dict(expected, schema_version=1, kind='reviewer-result', gate='ai_red_team', status='pass',
        reviewer='independent-human-fixture', reviewer_kind='human', review_role='ai-red-teamer',
        review_root=str(tmp_path.resolve()),
        managed_sha256='4'*64, config_sha256='5'*64,
        checks=[{'id': key, 'status': 'pass', 'evidence': [{'file': 'result.py', 'lines': '1'}]}
                for key in required],
        attack_evidence=[{'kind': 'adversarial-execution', 'path': str(report.relative_to(tmp_path)),
                          'tested_revision': head, 'sha256': hashlib.sha256(report.read_bytes()).hexdigest()}])
    path = reviewer_handoff.verdict_path(handoff, 'ai_red_team')
    path.parent.mkdir(parents=True)
    def save():
        path.write_text(json.dumps(verdict))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    save()
    human_scope = dict(expected, review_root=str(tmp_path.resolve()), managed_sha256='4'*64, config_sha256='5'*64)
    return tmp_path, handoff, verdict, path, report, expected, human_scope, save


def consume(packet, trusted=True):
    root, handoff, verdict, path, _, expected, human_scope, _ = packet
    context = {'scope': human_scope, 'digests': {'ai_red_team': hashlib.sha256(path.read_bytes()).hexdigest()}} if trusted else None
    return pipeline_evidence._consume_handoff_verdicts(root, ['ai_red_team'], {}, {}, expected['reviewed_revision'],
        child_root=handoff, review_base=expected['base_revision'], human_review_context=context)


def test_specialized_human_result_is_consumed_without_generic_same_model_review(packet):
    _, _, verdict, path, report, _, _, _ = packet
    assert path.is_file() and report.is_file() and verdict['attack_evidence']
    assert 'ai_red_team' in pipeline_helpers.NO_SELF_REVIEW
    assert pipeline_helpers._reviewable_gates(['ai_red_team'], {}) == []
    evidence, reviews = consume(packet)
    assert evidence['ai_red_team']['status'] == 'pass'
    assert reviews[-1]['source'] == 'human-red-team-artifact'


def test_untrusted_file_is_not_consumed_just_because_it_exists(packet):
    evidence, _ = consume(packet, trusted=False)
    assert evidence.get('ai_red_team', {}).get('status') != 'pass'


@pytest.mark.parametrize('damage', ['agent', 'ordinary-review', 'writer', 'stale', 'foreign-root',
    'foreign-config', 'foreign-policy', 'missing-attack', 'changed-attack', 'missing-check'])
def test_specialized_ingestion_is_fail_closed(packet, damage):
    root, _, verdict, _, report, _, _, save = packet
    if damage == 'agent':verdict['reviewer_kind'] = 'agent'
    elif damage == 'ordinary-review':verdict['review_role'] = 'code-reviewer'
    elif damage == 'writer':verdict['reviewer'] = verdict['writer_session']
    elif damage == 'stale':verdict['reviewed_revision'] = '0'*40
    elif damage == 'foreign-root':verdict['review_root'] = str(root.parent/'foreign')
    elif damage == 'foreign-config':verdict['config_sha256'] = '6'*64
    elif damage == 'foreign-policy':verdict['managed_sha256'] = '7'*64
    elif damage == 'missing-attack':verdict['attack_evidence'] = []
    elif damage == 'changed-attack':report.write_text('changed')
    elif damage == 'missing-check':verdict['checks'].pop()
    save()  # even an external digest does not repair wrong binding/shape/proof bytes
    evidence, _ = consume(packet)
    assert evidence.get('ai_red_team', {}).get('status') != 'pass'


def test_human_request_is_exposed_separately_from_native_agent_jobs(packet, monkeypatch):
    root, _, _, verdict_path, attack_path, expected, _, _ = packet
    task = {'runtime': 'codex', 'session_id': 'writer-fixture', 'request_id': 'a'*32,
            'binding': {'head': expected['base_revision']}, 'execution': {'signals': {}}}
    directory = root/'features'/expected['workitem_id'];directory.mkdir(parents=True)
    (directory/'run-plan.yaml').write_text(yaml.safe_dump({'gates': ['ai_red_team']}))
    from ai_ops_kit.engine import acceptance_verify
    monkeypatch.setattr(acceptance_verify, 'criteria_from_spec', lambda *args: (None, [], None))
    monkeypatch.setattr(completion, 'scope', lambda *args, **kwargs: expected)
    current = {'head': expected['reviewed_revision'], 'root': str(root), 'managed_sha256': '4'*64, 'config_sha256': '5'*64}
    handoff, accepted, missing, pending = completion.review_inputs(root, task, current, {})
    assert not accepted and missing and len(pending) == 1 and pending[0].is_file()
    action = completion.review_jobs(root, task, expected, pending)
    assert action['jobs'] == [] and len(action['human_jobs']) == 1
    assert action['human_jobs'][0]['gate'] == 'ai_red_team'
    assert action['status'] == 'awaiting_human'
    assert action['human_jobs'][0]['request_sha256'] == hashlib.sha256(pending[0].read_bytes()).hexdigest()
    payload = verdict_path.read_bytes()
    verdict_path = reviewer_handoff.verdict_path(handoff, 'ai_red_team')
    verdict_path.write_bytes(payload)
    before = verdict_path.read_bytes(), attack_path.read_bytes(), json.dumps(task, sort_keys=True)
    _, accepted, missing, pending = completion.review_inputs(root, task, current,
        {'ai_red_team': hashlib.sha256(before[0]).hexdigest()})
    assert not missing and not pending
    assert accepted['ai_red_team']['attack_artifacts'] == {
        str(attack_path.relative_to(root)): hashlib.sha256(before[1]).hexdigest()}
    assert (verdict_path.read_bytes(), attack_path.read_bytes(), json.dumps(task, sort_keys=True)) == before


def test_malformed_specialized_checks_return_errors_instead_of_crashing():
    assert reviewer_result.check_human_red_team({'checks': None, 'status': 'pass'}, ['attack_scenarios_run'])
