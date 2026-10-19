"""Локальная CLI предпосылка и безопасный повтор после её восстановления."""
import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp
from _parallel_dispatch_helpers import _real_repo, _real_commit


@pytest.mark.parametrize('provider', ['claude-cli', 'claude-code-local'])
@pytest.mark.parametrize('mode', ['missing', 'not-executable'])
def test_missing_local_cli_blocks_before_parallel_dispatch(tmp_path, monkeypatch, mode, provider):
    from ai_ops_kit.providers import orchestrator_providers as providers
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'fixture-claude'
    if mode == 'not-executable':
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o644)
        assert binary.is_file()
    else:
        assert not binary.exists()
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    assert providers.claude_binary() is None
    dispatch_marker = tmp_path / 'dispatch-started'
    calls = []

    def dispatch(*args, **kwargs):
        dispatch_marker.write_text('actual dispatch reached\n')
        return {'proceed': False}

    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider=provider,
                               runner=dispatch, run_fn=lambda *a, **k: calls.append('model'))
    assert not dispatch_marker.exists()
    assert rec['stage'] == 'preflight' and 'provider unavailable' in rec['reason']
    assert dsp.exit_code(rec) == 2 and calls == []
    assert not (root / '.git/ai-ops-parallel').exists()


@pytest.mark.parametrize('provider', ['claude-cli', 'claude-code-local'])
def test_executable_local_cli_reaches_real_isolated_execution_without_native_call(tmp_path, monkeypatch, provider):
    from ai_ops_kit.providers import orchestrator_providers as providers
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'fixture-claude'
    native_marker = tmp_path / 'native-was-called'
    binary.write_text(f'#!/bin/sh\nprintf called > "{native_marker}"\nexit 77\n')
    binary.chmod(0o755)
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    assert providers.claude_binary() == str(binary)
    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider=provider,
                               run_fn=_real_commit)
    assert rec['integration_sha'] and rec['aggregate']['all_pass']
    assert set(rec['package_results']) == {'aa', 'bb'}
    assert all(row['sha'] for row in rec['package_results'].values())
    assert not native_marker.exists()


@pytest.mark.parametrize('provider', ['claude-cli', 'claude-code-local'])
def test_missing_cli_refuses_before_durable_admission_validation(tmp_path, monkeypatch, provider):
    from ai_ops_kit.lifecycle import active_work
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'absent-claude'
    assert not binary.exists()
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    validation_calls = []

    def validate(*args, **kwargs):
        validation_calls.append('admission')
        raise active_work.ActiveWorkCorrupt('fixture: later admission reached')

    monkeypatch.setattr(active_work, 'validate_admission', validate)
    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider=provider,
                               admission={'identity': 'fixture'}, run_fn=lambda *a, **k: None)
    assert validation_calls == []
    assert rec['stage'] == 'preflight' and 'provider unavailable' in rec['reason']


@pytest.mark.parametrize('provider', ['claude-cli', 'claude-code-local'])
def test_retry_after_local_cli_restore_starts_each_package_once(tmp_path, monkeypatch, provider):
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'restored-claude'
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    starts = []

    def run(*args, **kwargs):
        starts.append(kwargs['feature'])
        return _real_commit(*args, **kwargs)

    blocked = dsp.run_parallel_live('T', {}, root, feature='WG', provider=provider, run_fn=run)
    assert blocked['stage'] == 'preflight' and 'provider unavailable' in blocked['reason']
    assert starts == [] and not (root / '.git/ai-ops-parallel').exists()
    native_marker = tmp_path / 'native-called'
    binary.write_text(f'#!/bin/sh\nprintf called > "{native_marker}"\nexit 77\n')
    binary.chmod(0o755)
    assert binary.is_file()
    resumed = dsp.run_parallel_live('T', {}, root, feature='WG', provider=provider, run_fn=run)
    assert resumed['aggregate']['all_pass'] and resumed['integration_sha']
    assert sorted(starts) == ['aa', 'bb']
    assert not native_marker.exists()
