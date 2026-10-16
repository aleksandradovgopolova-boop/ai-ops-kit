"""Одна native стадия: positive, fail-closed, side-effect и настоящий hook subprocess."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import codex_stage as stage
from ai_ops_kit.devtools.codex_stage_hook import handle
from ai_ops_kit.devtools.codex_stage_cli import main

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = {'intake': 'Проблема и пользователь', 'requirements': 'Сохранить черновик без публикации'}


@pytest.fixture
def auth(tmp_path):
    path = tmp_path / 'auth.json'
    path.write_text('{"synthetic_auth":true}')
    return path


def native_runner(mutation=None):
    def run(args, **kwargs):
        home = Path(kwargs['env']['CODEX_HOME'])
        control = Path(args[args.index('--output-last-message') + 1]).parent
        assert kwargs['cwd'].name == 'workspace'
        assert kwargs['env'].get('OPENAI_API_KEY') is None
        assert args[args.index('--sandbox') + 1] == 'read-only'
        assert '--ignore-user-config' in args and args[-1] == '-'
        assert (home / 'auth.json').stat().st_mode & 0o777 == 0o600
        hooks = json.loads((home / 'hooks.json').read_text())['hooks']
        command = hooks['SessionStart'][0]['hooks'][0]['command']
        if mutation != 'missing-hook':
            event = {'hook_event_name': 'SessionStart', 'session_id': 'session', 'source': 'startup'}
            # Настоящий child процесс Python исполняет тот же handler, что native CLI.
            hook = subprocess.run(command, shell=True, input=json.dumps(event), text=True,
                                  capture_output=True, check=True)
            output = json.loads(hook.stdout)
            assert 'contradiction-resolution' in output['hookSpecificOutput']['additionalContext']
        if mutation == 'tool':
            handle(control, {'hook_event_name': 'PreToolUse', 'session_id': 'session',
                             'turn_id': 'turn', 'tool_use_id': 'call', 'tool_name': 'Bash',
                             'tool_input': {'command': 'echo forbidden'}})
        if mutation == 'side-effect':
            (kwargs['cwd'] / 'changed').write_text('actual forbidden side effect')
            assert (kwargs['cwd'] / 'changed').is_file()
        if mutation == 'timeout':
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        if mutation == 'ack':
            (control / 'ack.json').write_text('{"output_sha256":"wrong"}')
        (control / 'answer.txt').write_text('' if mutation == 'empty' else '# Specification\nНастоящий ответ')
        events = [{'type': 'thread.started', 'thread_id': 'session'},
                  {'type': 'item.completed', 'item': {'type': 'error', 'message': stage.HOOK_TRUST_NOTICE}},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'answer'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 3}}]
        if mutation == 'stream-tool':
            events.insert(1, {'type': 'item.completed', 'item': {'type': 'command_execution'}})
        if mutation == 'native-error':
            events.insert(1, {'type': 'item.completed', 'item': {'type': 'error', 'message': 'actual refusal'}})
        if mutation == 'session':
            events[0]['thread_id'] = 'another-session'
        if mutation == 'no-completion':
            events.pop()
        return subprocess.CompletedProcess(args, 1 if mutation == 'exit' else 0,
                                          '\n'.join(json.dumps(e) for e in events), '')
    return run


def test_native_stage_publishes_actual_artifact_before_blocked_gate_assertion(tmp_path, auth):
    output = tmp_path / 'result'
    report = stage.run_specification('Задача', PUBLISHED, output, model='test',
                                     auth_file=auth, runner=native_runner())
    assert (output / 'stage-specification.md').read_text() == '# Specification\nНастоящий ответ'
    assert report['provenance']['kind'] == 'REASONING'
    gates = json.loads((output / 'GateReport.json').read_text())
    assert gates['blocked'] and gates['unmet_gates']
    assert report['workflow_status'] == 'blocked'
    assert not (output / 'TaskState.yaml').exists()
    assert report['context_receipt']['runtime_delivery_verified'] is False


@pytest.mark.parametrize('mutation', ['missing-hook', 'tool', 'side-effect', 'timeout', 'ack',
                                     'empty', 'stream-tool', 'native-error', 'session', 'no-completion', 'exit'])
def test_native_failure_never_publishes_stage(tmp_path, auth, mutation):
    output = tmp_path / 'result'
    with pytest.raises((ValueError, OSError, subprocess.TimeoutExpired)):
        stage.run_specification('Задача', PUBLISHED, output, model='test',
                                auth_file=auth, runner=native_runner(mutation))
    assert not output.exists()


def test_missing_skill_refuses_before_native_launch(tmp_path, auth):
    package = tmp_path / 'package'
    (package / 'registry').mkdir(parents=True)
    (package / 'manifest').mkdir()
    (package / 'registry/workflows.yaml').write_bytes((ROOT / 'registry/workflows.yaml').read_bytes())
    (package / 'manifest/ai-ops-manifest.yaml').write_text(yaml.safe_dump(
        {'skills': {'shipped': [{'id': 'contradiction-resolution', 'path': 'missing/SKILL.md'}]}}))
    def never(*args, **kwargs):
        pytest.fail('native runtime не должен быть запущен')
    with pytest.raises(ValueError):
        stage.run_specification('Задача', PUBLISHED, tmp_path / 'result', model='test',
                                auth_file=auth, package_root=package, runner=never)


def test_native_private_auth_copy_removed(tmp_path, auth):
    seen = []
    execute = native_runner()
    def capture(args, **kwargs):
        seen.append(Path(kwargs['env']['CODEX_HOME']))
        return execute(args, **kwargs)
    stage.run_specification('Задача', PUBLISHED, tmp_path / 'result', model='test',
                            auth_file=auth, runner=capture)
    assert seen and not seen[0].exists()
    assert auth.is_file()
    assert 'synthetic_auth' not in (tmp_path / 'result/NativeStageReport.json').read_text()


def test_existing_output_is_not_overwritten(tmp_path, auth):
    with pytest.raises(ValueError, match='существует'):
        stage.run_specification('Задача', PUBLISHED, tmp_path, model='test', auth_file=auth)
    assert auth.is_file()


def test_report_write_failure_does_not_publish_partial_artifact(tmp_path, auth, monkeypatch):
    original = Path.write_text
    def failing(path, *args, **kwargs):
        if path.name == 'NativeStageReport.json':
            raise OSError('simulated disk failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', failing)
    output = tmp_path / 'result'
    with pytest.raises(OSError):
        stage.run_specification('Задача', PUBLISHED, output, model='test',
                                auth_file=auth, runner=native_runner())
    assert not output.exists()
    assert not list(tmp_path.glob('.codex-stage-*'))


def test_publication_race_does_not_overwrite_existing_destination(tmp_path):
    output = tmp_path / 'result'
    output.mkdir()
    marker = output / 'owned'
    marker.write_text('existing')
    with pytest.raises(FileExistsError):
        stage.publish(output, 'answer', {}, {})
    assert marker.read_text() == 'existing'


@pytest.mark.parametrize('published', [{}, {'intake': 'x'}, {'intake': '', 'requirements': 'x'}])
def test_published_inputs_required_before_launch(published):
    with pytest.raises(ValueError):
        stage.prepare('Задача', published, ROOT)


def test_hook_denies_all_tools_without_executing_payload(tmp_path):
    marker = tmp_path / 'marker'
    result = handle(tmp_path, {'hook_event_name': 'PreToolUse',
                              'tool_input': {'command': f'touch {marker}'}})
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert not marker.exists()


def test_cli_failure_uses_not_executed_code(tmp_path):
    input_file = tmp_path / 'input.json'
    input_file.write_text('{}')
    assert main(['--input', str(input_file), '--output-dir', str(tmp_path / 'out'),
                 '--model', 'test']) == 2
