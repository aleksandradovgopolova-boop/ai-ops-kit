"""Реальные подпроцессы: журнал переживает таймаут, общий бюджет и повторный запуск."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SOURCE = Path(__file__).resolve().parents[2] / 'installer' / 'setup_run.py'
spec = importlib.util.spec_from_file_location('setup_run_under_test', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SetupRun, SetupStopped = module.SetupRun, module.SetupStopped


def events(run):
    return [json.loads(line) for line in run.journal.read_text().splitlines()]


def test_success_records_source_step_output_and_unknown_costs(tmp_path):
    with SetupRun(tmp_path, timeout=5) as run:
        result = run.command('probe', [sys.executable, '-c', "print('result')"])
        assert result.returncode == 0
        assert result.stdout.strip() == 'result'
    recorded = events(run)
    assert [row['event'] for row in recorded] == ['run_started', 'step_started', 'step_finished', 'run_finished']
    assert recorded[0]['human_active_minutes'] is None
    assert recorded[0]['USD'] is None
    assert recorded[-1]['status'] == 'completed'
    assert recorded[2]['elapsed_seconds'] > 0
    assert (run.directory / recorded[2]['stdout_log']).read_text().strip() == 'result'


def test_timeout_keeps_real_side_effect_and_partial_stdout_stderr(tmp_path):
    marker = tmp_path / 'before-timeout'
    late = tmp_path / 'must-not-exist'
    script = (f"from pathlib import Path; import time, sys; Path({str(marker)!r}).write_text('made'); "
              "print('partial stdout', flush=True); print('partial stderr', file=sys.stderr, flush=True); "
              f"time.sleep(10); Path({str(late)!r}).write_text('late')")
    with pytest.raises(SetupStopped):
        with SetupRun(tmp_path, timeout=1) as run:
            run.command('hang', [sys.executable, '-u', '-c', script])
    assert marker.read_text() == 'made'
    assert not late.exists()
    recorded = events(run)
    step = next(row for row in recorded if row['event'] == 'step_finished')
    assert step['status'] == 'timeout'
    assert 'partial stdout' in (run.directory / step['stdout_log']).read_text()
    assert 'partial stderr' in (run.directory / step['stderr_log']).read_text()
    assert recorded[-1]['status'] == 'timeout'


def test_budget_is_shared_and_second_step_cannot_reset_it(tmp_path):
    start = time.monotonic()
    with pytest.raises(SetupStopped):
        with SetupRun(tmp_path, timeout=1.2) as run:
            run.command('first', [sys.executable, '-c', 'import time; time.sleep(0.5)'])
            run.command('second', [sys.executable, '-c', 'import time; time.sleep(1)'])
    assert time.monotonic() - start < 2.5
    steps = [row for row in events(run) if row['event'] == 'step_started']
    assert steps[1]['timeout_seconds'] < steps[0]['timeout_seconds'] - 0.4


def test_failed_command_and_retry_keep_separate_histories(tmp_path):
    with SetupRun(tmp_path, timeout=5) as first:
        result = first.command('bad', [sys.executable, '-c', 'raise SystemExit(7)'])
        assert result.returncode == 7
    old = first.journal.read_bytes()
    with SetupRun(tmp_path, timeout=5) as second:
        second.command('good', [sys.executable, '-c', "print('retry')"])
    assert first.directory != second.directory
    assert first.journal.read_bytes() == old
    assert events(first)[-1]['status'] == 'failed'
    assert events(second)[-1]['status'] == 'completed'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX process groups')
def test_timeout_stops_descendant_before_it_can_change_files(tmp_path):
    marker = tmp_path / 'descendant-started'
    late = tmp_path / 'descendant-late'
    child = (f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); "
             f"time.sleep(2); Path({str(late)!r}).touch()")
    script = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(20)"
    with pytest.raises(SetupStopped):
        with SetupRun(tmp_path, timeout=1) as run:
            run.command('tree', [sys.executable, '-c', script])
    assert marker.exists()
    time.sleep(1.3)
    assert not late.exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX SIGTERM')
def test_parent_termination_leaves_interrupted_journal_and_output(tmp_path):
    marker = tmp_path / 'started'
    script = (f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); "
              "print('before termination', flush=True); time.sleep(20)")
    launcher = (f"import sys; sys.path.insert(0,{str(SOURCE.parent)!r}); from setup_run import SetupRun; "
                f"\nwith SetupRun(__import__('pathlib').Path({str(tmp_path)!r}),timeout=10) as run:"
                f"\n run.command('work',[sys.executable,'-u','-c',{script!r}])")
    parent = subprocess.Popen([sys.executable, '-c', launcher], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        parent.send_signal(signal.SIGTERM)
        parent.communicate(timeout=5)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate()
    journals = list((tmp_path / '.ai/runtime/setup').glob('*/events.jsonl'))
    assert len(journals) == 1
    rows = [json.loads(line) for line in journals[0].read_text().splitlines()]
    assert rows[-1]['status'] == 'interrupted'
    assert 'before termination' in (journals[0].parent / 'work.stdout.log').read_text()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX Git hook and signal cleanup')
def test_timed_out_git_hook_releases_locks_and_allows_retry(child):
    def git(*args):
        return subprocess.run(['git', '-C', str(child), *args], capture_output=True, text=True)
    target = child / 'KIT.txt'
    target.write_text('kit change\n')
    assert git('add', 'KIT.txt').returncode == 0
    hook = child / '.git/hooks/pre-commit'
    hook.write_text('#!/bin/sh\necho hook-started\nsleep 20\n')
    hook.chmod(0o755)
    with pytest.raises(SetupStopped):
        with SetupRun(child, timeout=1) as run:
            run.command('git-commit', ['git', 'commit', '-m', 'kit change', '--', 'KIT.txt'])
    assert 'hook-started' in ((run.directory / 'git-commit.stdout.log').read_text()
                              + (run.directory / 'git-commit.stderr.log').read_text())
    assert not list((child / '.git').glob('*index*.lock'))
    hook.unlink()
    assert git('add', 'KIT.txt').returncode == 0
    retry = git('commit', '-m', 'kit change', '--', 'KIT.txt')
    assert retry.returncode == 0, retry.stderr
    assert git('show', 'HEAD:KIT.txt').stdout == 'kit change\n'


def test_setup_keeps_init_refusal_code_and_stops_before_doctor(child, tmp_path, monkeypatch):
    marker = child / 'refusal-actually-ran'
    refusing = tmp_path / 'refusing_init.py'
    refusing.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit(2)\n")
    loader = importlib.util.spec_from_file_location('refusal_installer', SOURCE.with_name('ai_ops.py'))
    installer = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(installer)
    setup = installer._setup_ops()
    monkeypatch.setattr(installer, "HERE", refusing)
    code = setup.cmd_setup(child, timeout=10)
    assert marker.exists(), 'the refusing initializer must actually run'
    assert code == 2
    journal = next((child / '.ai/runtime/setup').glob('*/events.jsonl'))
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert rows[-1]['status'] == 'failed'
    assert next(row for row in rows if row.get('step') == 'init' and row['event'] == 'step_finished')['exit_code'] == 2
    assert not any(row.get('step') == 'doctor' for row in rows)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX SIGTERM')
def test_setup_signal_exit_does_not_attribute_runtime_termination_to_human(child, tmp_path):
    marker = child / 'initializer-started'
    slow = tmp_path / 'slow_init.py'
    slow.write_text(f"from pathlib import Path\nimport time\nprint('init partial output',flush=True)\n"
                    f"Path({str(marker)!r}).touch()\ntime.sleep(20)\n")
    launcher = (f"import importlib.util,sys; from pathlib import Path; "
                f"spec=importlib.util.spec_from_file_location('signal_installer',{str(SOURCE.with_name('ai_ops.py'))!r}); "
                "installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer); "
                f"setup=installer._setup_ops(); installer.HERE=Path({str(slow)!r}); "
                f"sys.exit(setup.cmd_setup({str(child)!r},timeout=10))")
    parent = subprocess.Popen([sys.executable, '-u', '-c', launcher], cwd=child,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), 'initializer must produce output before interruption'
        parent.send_signal(signal.SIGTERM)
        stdout, stderr = parent.communicate(timeout=10)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate()
    assert parent.returncode == 1, stdout + stderr
    assert 'получен сигнал прерывания' in stdout
    assert 'прервана пользователем' not in stdout
    journal = next((child / '.ai/runtime/setup').glob('*/events.jsonl'))
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert rows[-1]['status'] == 'interrupted'
    assert 'init partial output' in (journal.parent / 'init.stdout.log').read_text()
