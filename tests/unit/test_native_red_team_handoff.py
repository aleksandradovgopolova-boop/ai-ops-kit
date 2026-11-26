"""Synthetic transport fixtures, not real humans, adversarial execution or live acceptance."""
import hashlib
import json
import subprocess
from pathlib import Path

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
    assert action['human_jobs'][0]['result_contract_fragment'] == '#/definitions/human_red_team'
    contract = json.loads(Path(action['human_jobs'][0]['result_contract']).read_text())
    assert 'human_red_team' in contract['definitions']
    assert 'reviewer_kind' not in contract['properties']
    assert action['status'] == 'awaiting_specialist_evidence'
    model_job, = action['model_jobs']
    assert model_job['dispatch'] == 'collect-existing-host-review'
    assert model_job['request_sha256'] == action['human_jobs'][0]['request_sha256']
    assert model_job['verdict'].endswith('/ai_red_team.model.reviewer.json')
    assert action['next_action'] == 'collect_existing_model_evidence_or_human_review'
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


@pytest.fixture
def machine_packet(packet, monkeypatch):
    """Host I/O boundary substituted with sealed fixture bytes; no real model calls."""
    from ai_ops_kit.engine import acceptance_verify
    from ai_ops_kit.shared import model_review_receipt
    root, _, verdict, _, report, expected, _, _ = packet
    current = dict(root=str(root), head=expected['reviewed_revision'],
                   managed_sha256='4'*64, config_sha256='5'*64)
    task = {'runtime': 'codex', 'session_id': 'writer-fixture', 'request_id': expected['request_id'],
            'binding': {'head': expected['base_revision']}, 'execution': {'signals': {}}}
    directory = root/'features'/expected['workitem_id']
    directory.mkdir(parents=True)
    (directory/'run-plan.yaml').write_text(yaml.safe_dump({'gates': ['ai_red_team']}))
    monkeypatch.setattr(completion, 'scope', lambda *args, **kwargs: expected)
    monkeypatch.setattr(acceptance_verify, 'criteria_from_spec', lambda *args: (None, [], None))
    handoff, _, _, pending = completion.review_inputs(root, task, current, {})
    request = pending[0]
    machine_path = Path(json.loads(request.read_bytes())['model_alternative']['verdict_artifact'])
    scope = dict(completion.human_scope(root, current, expected), request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    verdict.update(scope, reviewer_kind='model', reviewer='codex:review-fixture')
    machine_path.write_text(json.dumps(verdict))
    receipt = {'schema_version': 1, 'kind': 'observed-model-review', 'gate': 'ai_red_team', 'scope':scope,
               'verdict_sha256':hashlib.sha256(machine_path.read_bytes()).hexdigest(),
               'execution_artifacts':{str(report.relative_to(root)):hashlib.sha256(report.read_bytes()).hexdigest()},
               'writer':{'execution':'completed','session':scope['writer_session'],'turn':'turn-W','canonical_model_id':'vendor/a'},
               'reviewer':{'execution':'completed','session':verdict['reviewer'],'turn':'turn-R','canonical_model_id':'vendor/b'}}
    def host_file(name):
        if name != model_review_receipt.receipt_name(scope):
            raise FileNotFoundError(name)
        return json.dumps(receipt).encode()
    monkeypatch.setattr(model_review_receipt, '_read_host_file', host_file)
    return root, handoff, machine_path, receipt, task, current


def test_finalize_inputs_automatically_consume_host_review_with_no_supplied_digest(machine_packet):
    root, handoff, path, receipt, task, current = machine_packet
    _, reviews, missing, pending = completion.review_inputs(root, task, current, {})
    assert not missing and not pending
    record = reviews['ai_red_team']
    assert record['path'] == str(path.relative_to(root))
    assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record['attack_artifacts'] == receipt['execution_artifacts']
    assert record['model_receipt']['sha256'] == hashlib.sha256(json.dumps(receipt).encode()).hexdigest()
    assert not reviewer_handoff.verdict_path(handoff, 'ai_red_team').exists()
    context = {'scope': record['model_receipt']['scope'], 'host_sha256':record['model_receipt']['sha256'],
               'digests':{'ai_red_team':record['sha256']}}
    evidence, entries = pipeline_evidence._consume_handoff_verdicts(root, ['ai_red_team'], {}, {}, current['head'],
        child_root=handoff, review_base=task['binding']['head'], human_review_context=context)
    assert evidence['ai_red_team']['status'] == 'pass'
    assert entries[-1]['source'] == 'host-model-red-team-artifact'


@pytest.mark.parametrize('damage', ['same-model','same-session','unknown-model','missing-turn','uncompleted',
                                    'foreign-scope','wrong-reviewer','changed-verdict','changed-evidence',
                                    'unobserved-evidence','no-host'])
def test_finalize_inputs_reject_unverified_model_results(machine_packet, monkeypatch, damage):
    from ai_ops_kit.shared import model_review_receipt
    root, _, path, receipt, task, current = machine_packet
    if damage == 'same-model':
        receipt['reviewer']['canonical_model_id'] = receipt['writer']['canonical_model_id']
    elif damage == 'same-session':
        receipt['reviewer']['session'] = receipt['writer']['session']
    elif damage == 'unknown-model':
        receipt['reviewer']['canonical_model_id'] = 'unknown'
    elif damage == 'missing-turn':
        del receipt['writer']['turn']
    elif damage == 'uncompleted':
        receipt['reviewer']['execution'] = 'selected'
    elif damage == 'foreign-scope':
        receipt['scope'] = dict(receipt['scope'], source_sha256='9'*64)
    elif damage == 'wrong-reviewer':
        receipt['reviewer']['session'] = 'codex:unrelated'
    elif damage == 'changed-verdict':
        path.write_bytes(path.read_bytes()+b' ')
    elif damage == 'changed-evidence':
        (root/next(iter(receipt['execution_artifacts']))).write_text('changed')
    elif damage == 'unobserved-evidence':
        receipt['execution_artifacts'] = {}
    else:
        def no_host(_):
            raise FileNotFoundError('no host record')
        monkeypatch.setattr(model_review_receipt, '_read_host_file', no_host)
    _, reviews, missing, requests = completion.review_inputs(root, task, current, {})
    assert not reviews and missing and len(requests) == 1


def test_host_record_is_revalidated_after_finalization(machine_packet):
    root, _, _, receipt, task, current = machine_packet
    _, reviews, _, _ = completion.review_inputs(root, task, current, {})
    from ai_ops_kit.shared import model_review_receipt
    saved = {'model_review_receipt': reviews['ai_red_team']['model_receipt']}
    model_review_receipt.recheck(saved)
    receipt['reviewer']['turn'] = 'replacement'
    with pytest.raises(ValueError, match='изменилась'):
        model_review_receipt.recheck(saved)


def test_user_writable_directory_cannot_supply_host_attestation(tmp_path, monkeypatch):
    from ai_ops_kit.shared import model_review_receipt
    monkeypatch.setattr(model_review_receipt, 'STORE', tmp_path)
    name = '1'*64 + '.json'
    (tmp_path/name).write_text('{}')
    with pytest.raises((ValueError, OSError)):
        model_review_receipt._read_host_file(name)
