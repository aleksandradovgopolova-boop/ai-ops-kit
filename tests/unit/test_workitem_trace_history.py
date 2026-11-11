"""Existing package report/archive history; synthetic receipts only."""
import builtins
import io
import json
from pathlib import Path
import socket
import subprocess

import pytest

from ai_ops_kit.devtools import workitem_trace
from ai_ops_kit.engine import pipeline_stages, workpackage_executor
from ai_ops_kit.shared import lifecycle_store, usage_ledger

pytestmark = pytest.mark.unit


def write_report(directory, wid='wi', *, status='fail'):
    report = {'kind': 'execution-pipeline', 'workitem_id': wid,
              'gates': {'evaluated': ['code_review'], 'unmet': ['code_review'] if status == 'fail' else []},
              'reviews': [{'gate': 'code_review', 'status': status, 'blockers': ['SECRET']}],
              'loop': pipeline_stages._build_loop_section({
                  'stopped': 'done', 'steps': 3, 'denied': [],
                  'transcript': [{'step': 1, 'op': 'read', 'allowed': True, 'ok': True, 'reason': 'SECRET'},
                                 {'step': 2, 'op': 'shell', 'allowed': False, 'reason': 'SECRET'},
                                 {'step': 3, 'done': True, 'summary': 'SECRET'}]}, []),
              'task': 'SECRET', 'commit': {'sha': 'a'*40}}
    assert workpackage_executor._persist_package_report(directory, directory.parent, wid, report) is None
    return report


@pytest.fixture
def history(tmp_path):
    feature = tmp_path/'features'/'wi'
    package = feature/'work-packages'/'p1'
    write_report(package/'attempts'/'attempt-10')
    write_report(package/'attempts'/'attempt-2')
    write_report(package, status='pass')
    assert lifecycle_store.journal_append(feature/'lifecycle-journal.jsonl', {
        'kind': 'package_end', 'workitem_id': 'wi', 'run_id': 'r', 'package_id': 'p1'})['ok']
    usage_ledger.append(tmp_path, 'wi', [{'run_id': 'r', 'package_id': 'p1',
                                       'usage_status': 'unavailable', 'trigger': 'initial'}])
    return tmp_path, package


def test_history_preserves_numeric_archive_order_and_current_without_invented_attempt(history):
    root, _ = history
    report = workitem_trace.compute(root, 'wi')
    assert [s['storage_attempt'] for s in report['snapshots']] == [2, 10, None]
    assert [s['scope'] for s in report['snapshots']] == ['archived-package', 'archived-package', 'current-package']
    assert all(e['attempt_id'] is None for e in report['events'])
    assert {e['kind'] for e in report['events']} >= {'invocation', 'package_end', 'gate', 'review', 'tool_attempt'}
    package_ids = {e['package_id'] for e in report['events'] if e.get('package_id')}
    assert len(package_ids) == 1
    for snapshot in report['snapshots']:
        assert len([e for e in report['events'] if e.get('snapshot_id') == snapshot['id']]) == 4
    assert report['metrics']['tool_calls']['total'] is None
    assert report == workitem_trace.compute(root, 'wi')
    assert 'SECRET' not in json.dumps(report)
    text = workitem_trace.format_text(report)
    assert 'archived-package' in text and 'tool_attempt' in text


def test_receipts_do_not_add_duplicate_invocations_or_historical_totals(history):
    root, _ = history
    report = workitem_trace.compute(root, 'wi')
    assert report['metrics']['invocations']['total'] == 1
    assert report['metrics']['failed_gates']['total'] is None
    assert report['metrics']['failed_gates']['known'] is None


@pytest.mark.parametrize('content', ['SECRET', '[]', '{"kind":"other","workitem_id":"wi"}',
                                      '{"kind":"execution-pipeline","workitem_id":"other"}'])
def test_invalid_or_unbound_history_is_diagnosed_and_excluded(history, content):
    root, package = history
    (package/'attempts'/'attempt-2'/'report.json').write_text(content)
    report = workitem_trace.compute(root, 'wi')
    assert report['status'] == 'partial'
    assert len(report['snapshots']) == 2
    assert 'package-history:corrupt-or-unbound' in report['diagnostics']
    assert 'SECRET' not in json.dumps(report)


def test_missing_archive_report_is_visible_without_filling_numeric_gaps(history):
    root, package = history
    (package/'attempts'/'attempt-2'/'report.json').unlink()
    report = workitem_trace.compute(root, 'wi')
    assert 'package-history:missing-report' in report['diagnostics']
    assert [s['storage_attempt'] for s in report['snapshots']] == [10, None]


def test_symlink_archive_is_not_traversed(history, tmp_path):
    root, package = history
    secret = tmp_path/'outside'
    secret.mkdir()
    (secret/'report.json').write_text('SECRET')
    (package/'attempts'/'attempt-3').symlink_to(secret, target_is_directory=True)
    report = workitem_trace.compute(root, 'wi')
    assert 'package-history:unsafe-path' in report['diagnostics']
    assert len(report['snapshots']) == 3
    assert 'SECRET' not in json.dumps(report)


def test_duplicate_tool_steps_are_ambiguous_and_not_counted_twice(history):
    root, package = history
    path = package/'report.json'
    record = json.loads(path.read_text())
    record['loop']['transcript'] = [{'step': 1, 'op': 'read', 'allowed': True},
                                   {'step': 1, 'op': 'write', 'allowed': False}]
    path.write_text(json.dumps(record))
    report = workitem_trace.compute(root, 'wi')
    current = report['snapshots'][-1]
    assert not any(e['kind'] == 'tool_attempt' and e.get('snapshot_id') == current['id'] for e in report['events'])
    assert 'package-history:ambiguous-tool-steps' in report['diagnostics']


def test_history_reads_no_write_network_process_or_transcript_prose(history, monkeypatch):
    root, _ = history
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before and any(b'SECRET' in raw for raw in before.values())
    def guard(original):
        def opened(file, mode='r', *args, **kw):
            assert not any(c in mode for c in 'wax+')
            return original(file, mode, *args, **kw)
        return opened
    def denied(*args, **kw):
        pytest.fail('write/network/process attempted')
    monkeypatch.setattr(builtins, 'open', guard(builtins.open))
    monkeypatch.setattr(io, 'open', guard(io.open))
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(Path, 'mkdir', denied)
    monkeypatch.setattr(Path, 'unlink', denied)
    report = workitem_trace.compute(root, 'wi')
    assert len(report['snapshots']) == 3
    assert 'SECRET' not in json.dumps(report)
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_missing_package_id_in_ledger_is_not_inferred_from_only_package(history):
    root, _ = history
    path = root/'features'/'wi'/'usage-ledger.jsonl'
    records = [json.loads(line) for line in path.read_text().splitlines()]
    for row in records:
        row['package_id'] = None
    path.write_text('\n'.join(json.dumps(row) for row in records)+'\n')
    report = workitem_trace.compute(root, 'wi')
    assert next(e for e in report['events'] if e['kind'] == 'invocation')['package_id'] is None
    assert all(s['package_id'] for s in report['snapshots'])


@pytest.mark.parametrize('metadata', [[{'step': 0, 'op': 'read', 'allowed': True}],
                                      [{'step': 0, 'op': 'read', 'allowed': False}]])
def test_zero_based_producer_step_is_preserved_with_unknown_invocation(history, metadata):
    root, package = history
    path = package/'report.json'
    record = json.loads(path.read_text())
    record['loop']['transcript'] = metadata
    path.write_text(json.dumps(record))
    report = workitem_trace.compute(root, 'wi')
    sid = report['snapshots'][-1]['id']
    event = next(e for e in report['events'] if e.get('snapshot_id') == sid and e['kind'] == 'tool_attempt')
    assert event['step'] == 0 and event['attempt_id'] is None
    assert event['duration_s'] is None and event['run_id'] is None
    assert event['ok'] is None


def test_same_snapshot_contents_are_not_deduplicated_across_storage_attempts(history):
    root, _ = history
    report = workitem_trace.compute(root, 'wi')
    archives = [s for s in report['snapshots'] if s['scope'] == 'archived-package']
    assert len({s['id'] for s in archives}) == 2
    event_ids = [e['id'] for e in report['events']]
    assert len(event_ids) == len(set(event_ids))


def test_text_trace_distinguishes_successful_and_denied_tool_attempts(history):
    root, _ = history
    text = workitem_trace.format_text(workitem_trace.compute(root, 'wi'))
    tool_lines = [line for line in text.splitlines() if 'tool_attempt' in line]
    successful = [line for line in tool_lines if 'operation=read' in line]
    denied = [line for line in tool_lines if 'operation=shell' in line]
    assert len(successful) == len(denied) == 3
    assert all('step=1' in line and 'allowed=True' in line and 'ok=True' in line for line in successful)
    assert all('step=2' in line and 'allowed=False' in line and 'ok=unknown' in line for line in denied)
    assert 'SECRET' not in text
