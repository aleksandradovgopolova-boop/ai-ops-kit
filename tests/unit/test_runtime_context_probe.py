"""Prototype: сериализация, отказ, gaps и отсутствие side effects в реальном CLI."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import runtime_context_probe as p

ROOT = Path(__file__).resolve().parents[2]
STAGE = {'id': 'review', 'owner': 'reviewer', 'review_mode': 'read-only', 'uses_skills': ['example']}


@pytest.fixture
def package(tmp_path):
    (tmp_path / 'manifest').mkdir()
    (tmp_path / 'skills/example').mkdir(parents=True)
    (tmp_path / 'skills/example/SKILL.md').write_text('SKILL_MARKER: проверить границы', encoding='utf-8')
    (tmp_path / 'manifest/ai-ops-manifest.yaml').write_text(yaml.safe_dump(
        {'skills': {'shipped': [{'id': 'example', 'path': 'skills/example/SKILL.md'}]}}))
    return tmp_path


def events(runtime='codex'):
    common = {'session_id': 'session', 'cwd': '/fixture', 'permission_mode': 'default'}
    start = {**common, 'hook_event_name': 'SessionStart', 'source': 'startup'}
    tool = {**common, 'tool_name': 'Bash', 'tool_use_id': 'call', 'tool_input': {'command': 'printf fixture'}}
    if runtime == 'codex':
        tool['turn_id'] = 'turn'
    return [start, {**tool, 'hook_event_name': 'PreToolUse'},
            {**tool, 'hook_event_name': 'PostToolUse', 'tool_response': {'stdout': 'fixture'}}]


@pytest.mark.parametrize('runtime', p.RUNTIMES)
def test_exact_skill_body_and_owner_reach_serialized_context(package, runtime):
    result = p.probe(runtime, STAGE, events(runtime), package)
    context = result['context_output']['hookSpecificOutput']['additionalContext']
    assert 'SKILL_MARKER: проверить границы' in context and 'reviewer' in context
    assert 'read-only' in context
    receipt = result['context_receipt']
    assert receipt['context_sha256'] == hashlib.sha256(context.encode()).hexdigest()
    assert receipt['binding']['skills']['example'] == hashlib.sha256('SKILL_MARKER: проверить границы'.encode()).hexdigest()
    assert receipt['runtime_delivery_verified'] is False
    assert result['audit']['paired_calls'] == 1 and result['audit']['status'] == 'observed'
    assert result['audit']['native_coverage_verified'] is False


def test_missing_required_skill_refuses_before_context(package):
    (package / 'skills/example/SKILL.md').unlink()
    with pytest.raises(ValueError):
        p.probe('codex', STAGE, events(), package)


def test_context_budget_refuses_without_truncating(package, monkeypatch):
    monkeypatch.setattr(p, 'MAX_CONTEXT_BYTES', 5)
    with pytest.raises(ValueError, match='бюджет'):
        p.context_response('codex', STAGE, package)


@pytest.mark.parametrize('field', ['id', 'owner', 'review_mode'])
def test_missing_stage_binding_refuses(package, field):
    stage = {k: v for k, v in STAGE.items() if k != field}
    with pytest.raises(ValueError):
        p.context_response('codex', stage, package)


def test_unknown_runtime_refuses(package):
    with pytest.raises(ValueError):
        p.context_response('unknown', STAGE, package)


@pytest.mark.parametrize('mutation,reason', [
    (lambda e: e[:2], 'missing_result'),
    (lambda e: [e[0], e[2]], 'orphan_result'),
    (lambda e: e + [e[2]], 'duplicate_payload'),
    (lambda e: [e[0], e[1], {**e[2], 'session_id': 'other'}], 'session_mismatch'),
    (lambda e: [e[0], e[1], {**e[2], 'tool_input': {'command': 'different'}}], 'action_mismatch'),
    (lambda e: e + [{'hook_event_name': 'FutureEvent', 'session_id': 'session'}], 'unsupported_event'),
    (lambda e: e + [None], 'malformed_payload'),
    (lambda e: e[1:], 'missing_session_start'),
    (lambda e: e + [{**e[1], 'extra': 'different'}], 'duplicate_call'),
    (lambda e: e + [{'hook_event_name': 'PreToolUse'}], 'missing_or_invalid_identity'),
])
def test_replay_gaps_are_explicit(mutation, reason):
    audit = p.audit_events('codex', mutation(events()))
    assert audit['status'] == 'degraded'
    assert reason in {g['reason'] for g in audit['gaps']}
    assert audit['side_effect_verified'] is False


def test_audit_does_not_store_raw_arguments_results_or_paths():
    data = events()
    data[1]['tool_input'] = data[2]['tool_input'] = {'command': 'PRIVATE_SECRET', 'path': '/PRIVATE_PATH'}
    data[2]['tool_response'] = {'stdout': 'PRIVATE_RESULT'}
    audit = json.dumps(p.audit_events('codex', data))
    assert all(s not in audit for s in ('PRIVATE_SECRET', 'PRIVATE_PATH', 'PRIVATE_RESULT', '/fixture'))


def invoke(package, raw):
    return subprocess.run([sys.executable, '-m', 'ai_ops_kit.devtools.runtime_context_probe',
                           '--runtime', 'codex', '--package-root', str(package)],
                          input=raw, capture_output=True, cwd=ROOT, timeout=10)


def test_real_cli_observes_tool_payload_without_executing_it(package):
    target = package / 'do-not-write.txt'
    command = f'echo changed > {target}'
    data = events()
    data[1]['tool_input'] = data[2]['tool_input'] = {'command': command}
    before = {str(f.relative_to(package)): f.read_bytes() for f in package.rglob('*') if f.is_file()}
    run = invoke(package, json.dumps({'stage': STAGE, 'events': data}).encode())
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['audit']['paired_calls'] == 1
    assert not target.exists()
    after = {str(f.relative_to(package)): f.read_bytes() for f in package.rglob('*') if f.is_file()}
    assert before == after


def test_real_cli_missing_skill_emits_no_context(package):
    (package / 'skills/example/SKILL.md').unlink()
    run = invoke(package, json.dumps({'stage': STAGE, 'events': events()}).encode())
    assert run.returncode == 2 and run.stdout == b''
    assert json.loads(run.stderr)['status'] == 'error'


def test_real_cli_gap_returns_degraded_exit_code(package):
    run = invoke(package, json.dumps({'stage': STAGE, 'events': events()[:2]}).encode())
    assert run.returncode == 1
    assert json.loads(run.stdout)['audit']['status'] == 'degraded'


@pytest.mark.parametrize('raw', [b'{', b'null', b'{}', b'x' * (p.MAX_INPUT_BYTES + 1)])
def test_real_cli_invalid_input_returns_no_context(package, raw):
    run = invoke(package, raw)
    assert run.returncode == 2 and run.stdout == b''
    assert json.loads(run.stderr)['status'] == 'error'


@pytest.mark.parametrize('mode,writer', [('unknown', None), ('read-only', 'reviewer')])
def test_invalid_role_binding_refuses(package, mode, writer):
    with pytest.raises(ValueError):
        p.context_response('codex', {**STAGE, 'review_mode': mode, 'writer': writer}, package)


@pytest.mark.parametrize('field,reason', [('tool_response', 'missing_response'), ('turn_id', 'unbound_tool_event')])
def test_incomplete_result_shape_is_degraded(field, reason):
    data = events()
    del data[2][field]
    audit = p.audit_events('codex', data)
    assert audit['status'] == 'degraded'
    assert reason in {g['reason'] for g in audit['gaps']}
