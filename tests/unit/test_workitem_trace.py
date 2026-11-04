"""Read-only WorkItem trace: real local fixtures, no runtime/model invocation."""
import builtins
import io
import json
import socket
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.shared import lifecycle_store
from ai_ops_kit.devtools import workitem_trace

pytestmark = pytest.mark.unit


@pytest.fixture
def traced(tmp_path):
    feature = tmp_path / 'features' / 'wi-1'
    feature.mkdir(parents=True)
    events = [
        {'kind': 'run_start', 'run_id': 'r1', 'workitem_id': 'wi-1', 'attempt_id': 'a1',
         'timestamp': '2026-11-01T10:00:00Z', 'prompt': 'SECRET'},
        {'kind': 'run_end', 'run_id': 'r1', 'workitem_id': 'wi-1', 'attempt_id': 'a1',
         'timestamp': '2026-11-01T10:00:03Z', 'status': 'not-ready'},
        {'kind': 'run_start', 'run_id': 'r1', 'workitem_id': 'wi-1', 'attempt_id': 'a2'},
    ]
    for event in events:
        assert lifecycle_store.journal_append(feature / 'lifecycle-journal.jsonl', event)['ok']
    calls = [
        {'run_id': 'r1', 'workitem_id': 'wi-1', 'trigger': 'initial', 'usage_status': 'measured',
         'input_tokens': 10, 'output_tokens': 0, 'cost': 0.1, 'cost_status': 'measured'},
        {'run_id': 'r1', 'workitem_id': 'wi-1', 'trigger': 'retry', 'usage_status': 'unavailable',
         'input_tokens': None, 'output_tokens': None, 'cost': None, 'cost_status': 'unavailable'},
    ]
    (feature / 'usage-ledger.jsonl').write_text('\n'.join(json.dumps(c) for c in calls)+'\n')
    (feature / 'run-report.json').write_text(json.dumps({
        'workitem_id': 'wi-1', 'gates': {'evaluated': ['lint', 'code_review'], 'unmet': ['code_review']},
        'reviews': [{'gate': 'code_review', 'status': 'fail', 'blockers': ['SECRET']}],
        'task': 'SECRET', 'loop': {'transcript': 'SECRET'},
    }))
    return tmp_path, feature


def test_links_runs_invocations_gates_reviews_and_measures_only_timestamp_pair(traced):
    root, _ = traced
    report = workitem_trace.compute(root, 'wi-1')
    assert len(report['runs']) == 1
    assert [a['duration_s'] for a in report['runs'][0]['attempts']] == [3.0, None]
    assert len([e for e in report['events'] if e['kind'] == 'invocation']) == 2
    assert {e['kind'] for e in report['events']} >= {'gate', 'review', 'run_start', 'run_end'}
    assert all(e['attempt_id'] is None for e in report['events'] if e['kind'] == 'invocation')
    assert report['metrics']['retries']['known'] == 1
    assert report['metrics']['cost_usd'] == {'known': 0.1, 'total': None, 'status': 'unknown'}
    assert report['metrics']['input_tokens']['known'] == 10
    assert report['metrics']['output_tokens']['known'] == 0
    assert report == workitem_trace.compute(root, 'wi-1')


def test_absent_data_is_unknown_and_does_not_create_root(tmp_path):
    root = tmp_path / 'absent'
    report = workitem_trace.compute(root, 'wi-1')
    assert report['status'] == 'no-data'
    assert all(v['total'] is None for v in report['metrics'].values())
    assert not root.exists()


def test_corrupt_journal_and_ledger_are_reported_without_partial_total(traced):
    root, feature = traced
    with (feature / 'lifecycle-journal.jsonl').open('a') as out:
        out.write('SECRET malformed\n')
    with (feature / 'usage-ledger.jsonl').open('a') as out:
        out.write('SECRET malformed\n')
    report = workitem_trace.compute(root, 'wi-1')
    assert report['status'] == 'partial'
    assert 'journal:corrupt' in report['diagnostics']
    assert 'usage:corrupt' in report['diagnostics']
    assert report['metrics']['retries']['total'] is None
    assert 'SECRET' not in json.dumps(report)


def test_identical_ledger_rows_are_distinct_calls_and_product_copy_not_counted(traced):
    root, feature = traced
    path = feature / 'usage-ledger.jsonl'
    row = path.read_text().splitlines()[0]
    path.write_text(row+'\n'+row+'\n')
    product = root / '.ai' / 'usage'
    product.mkdir(parents=True)
    (product / 'product-ledger.jsonl').write_text(row+'\n')
    report = workitem_trace.compute(root, 'wi-1')
    assert report['metrics']['invocations']['total'] == 2
    assert report['metrics']['cost_usd']['total'] == 0.2


def test_explicit_repeated_event_id_is_deduplicated_but_conflict_is_partial(tmp_path):
    feature = tmp_path / 'features' / 'wi-1'
    feature.mkdir(parents=True)
    event = {'kind': 'fix_attempt', 'run_id': 'r', 'workitem_id': 'wi-1', 'event_id': 'e1'}
    for e in [event, event]:
        assert lifecycle_store.journal_append(feature / 'lifecycle-journal.jsonl', e)['ok']
    assert len(workitem_trace.compute(tmp_path, 'wi-1')['events']) == 1
    assert lifecycle_store.journal_append(feature / 'lifecycle-journal.jsonl', dict(event, kind='run_end'))['ok']
    report = workitem_trace.compute(tmp_path, 'wi-1')
    assert 'journal:duplicate-conflict' in report['diagnostics']
    assert report['status'] == 'partial'


@pytest.mark.parametrize('wid', ['../outside', '/absolute', '.', 'a/b', ''])
def test_rejects_unsafe_workitem_path(tmp_path, wid):
    with pytest.raises(ValueError, match='workitem'):
        workitem_trace.compute(tmp_path, wid)


def test_symlink_source_rejected(traced, tmp_path):
    root, feature = traced
    secret = tmp_path / 'secret.json'
    secret.write_text('{"task":"SECRET"}')
    (feature / 'run-report.json').unlink()
    (feature / 'run-report.json').symlink_to(secret)
    report = workitem_trace.compute(root, 'wi-1')
    assert 'report:unsafe-path' in report['diagnostics']
    assert 'SECRET' not in json.dumps(report)


def test_no_filesystem_writes_network_or_processes_and_redacts_all_text(traced, monkeypatch):
    root, _ = traced
    snapshot = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert snapshot and any('SECRET' in b.decode() for b in snapshot.values())
    real_open, real_io_open = builtins.open, io.open

    def guard(original):
        def opened(file, mode='r', *a, **kw):
            assert not any(c in mode for c in 'wax+'), 'trace attempted write'
            return original(file, mode, *a, **kw)
        return opened

    def denied(*a, **kw):
        pytest.fail('trace attempted network/process/write')

    monkeypatch.setattr(builtins, 'open', guard(real_open))
    monkeypatch.setattr(io, 'open', guard(real_io_open))
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(Path, 'mkdir', denied)
    monkeypatch.setattr(Path, 'unlink', denied)
    monkeypatch.setattr(Path, 'rename', denied)
    report = workitem_trace.compute(root, 'wi-1')
    assert 'SECRET' not in json.dumps(report)
    assert 'SECRET' not in workitem_trace.format_text(report)
    assert snapshot == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_failed_gates_are_lower_bound_from_latest_snapshot(traced):
    root, _ = traced
    report = workitem_trace.compute(root, 'wi-1')
    assert report['metrics']['failed_gates'] == {'known': 1, 'total': None, 'status': 'unknown'}
    assert report['metrics']['tool_calls']['total'] is None
    assert report['metrics']['human_interventions']['total'] is None


@pytest.mark.parametrize('value', [-1, True, '10', None])
def test_invalid_tokens_never_become_measured_zero(traced, value):
    root, feature = traced
    row = {'run_id': 'r', 'input_tokens': value, 'usage_status': 'measured', 'trigger': 'initial'}
    (feature / 'usage-ledger.jsonl').write_text(json.dumps(row)+'\n')
    metric = workitem_trace.compute(root, 'wi-1')['metrics']['input_tokens']
    assert metric == {'known': None, 'total': None, 'status': 'unknown'}


@pytest.mark.parametrize('start,end', [
    ('2026-11-01T10:00:00', '2026-11-01T10:00:01'),
    ('2026-11-01T10:00:02Z', '2026-11-01T10:00:01Z'),
    ('SECRET', '2026-11-01T10:00:01Z'),
    (None, None),
])
def test_invalid_or_absent_timestamps_never_use_latency_or_file_mtime(tmp_path, start, end):
    feature = tmp_path / 'features' / 'wi-1'
    feature.mkdir(parents=True)
    for kind, time in [('run_start', start), ('run_end', end)]:
        assert lifecycle_store.journal_append(feature / 'lifecycle-journal.jsonl', {
            'kind': kind, 'workitem_id': 'wi-1', 'run_id': 'r', 'attempt_id': 'a',
            'timestamp': time, 'latency': 5,
        })['ok']
    report = workitem_trace.compute(tmp_path, 'wi-1')
    assert report['runs'][0]['attempts'][0]['duration_s'] is None
    assert 'SECRET' not in json.dumps(report)


def test_truncated_journal_tail_is_not_returned_as_complete(traced):
    root, feature = traced
    path = feature / 'lifecycle-journal.jsonl'
    path.write_text('\n'.join(path.read_text().splitlines()[:-1])+'\n')
    report = workitem_trace.compute(root, 'wi-1')
    assert 'journal:corrupt' in report['diagnostics']
    assert not any(e['source'] == 'journal' for e in report['events'])


def test_mismatched_workitem_records_and_unbound_report_are_excluded(traced):
    root, feature = traced
    (feature / 'usage-ledger.jsonl').write_text(json.dumps({'workitem_id': 'other', 'cost': 1})+'\n')
    (feature / 'run-report.json').write_text(json.dumps({'workitem_id': 'other', 'reviews': [{'status': 'pass'}]}))
    report = workitem_trace.compute(root, 'wi-1')
    assert {'usage:workitem-mismatch', 'report:corrupt-or-unbound'} <= set(report['diagnostics'])
    assert not any(e['kind'] in ('invocation', 'review') for e in report['events'])
    assert report['metrics']['cost_usd']['total'] is None


def test_free_text_in_identity_status_and_nested_fields_is_redacted(traced):
    root, feature = traced
    (feature / 'run-report.json').write_text(json.dumps({'workitem_id': 'wi-1', 'reviews': [
        {'gate': 'SECRET', 'run_id': 'SECRET', 'status': 'SECRET', 'evidence': ['SECRET']},
        {'gate': {'secret': 'SECRET'}, 'status': {'secret': 'SECRET'}},
    ]}))
    (feature / 'usage-ledger.jsonl').write_text(json.dumps({'run_id': 'SECRET', 'role': 'SECRET',
        'model': 'SECRET', 'provider': 'SECRET', 'prompt': 'SECRET', 'status': ['SECRET']})+'\n')
    report = workitem_trace.compute(root, 'wi-1')
    assert 'SECRET' not in json.dumps(report)
    assert 'SECRET' not in workitem_trace.format_text(report)


def test_cli_adds_workitem_trace_without_changing_default_report(traced, monkeypatch, capsys):
    import sys
    from ai_ops_kit.devtools import kit_observability
    root, _ = traced
    monkeypatch.setattr(sys, 'argv', ['kit_observability', str(root), '--workitem', 'wi-1', '--json'])
    assert kit_observability.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['kind'] == 'WorkItemTrace'
    monkeypatch.setattr(sys, 'argv', ['kit_observability', str(root), '--json'])
    assert kit_observability.main() == 0
    assert 'kit' in json.loads(capsys.readouterr().out)


def test_deleted_journal_with_durable_head_is_visible_loss(traced):
    root, feature = traced
    (feature / 'lifecycle-journal.jsonl').unlink()
    assert (feature / 'lifecycle-journal.jsonl.head').exists()
    report = workitem_trace.compute(root, 'wi-1')
    assert report['status'] == 'partial'
    assert 'journal:missing-with-head' in report['diagnostics']


@pytest.mark.parametrize('marker', ['SECRET', '{}', '{"kind":"journal-head","seq":true,"checksum":"x"}'])
def test_invalid_head_marker_is_not_a_complete_journal(traced, marker):
    root, feature = traced
    (feature / 'lifecycle-journal.jsonl.head').write_text(marker)
    report = workitem_trace.compute(root, 'wi-1')
    assert 'journal:corrupt' in report['diagnostics']
    assert not any(e['source'] == 'journal' for e in report['events'])
    assert 'SECRET' not in json.dumps(report)


@pytest.mark.parametrize('gates,reviews', [([], {}), ('SECRET', 1), ({'evaluated': [], 'unmet': None}, 'SECRET')])
def test_invalid_snapshot_sections_are_diagnosed(traced, gates, reviews):
    root, feature = traced
    (feature / 'run-report.json').write_text(json.dumps({'workitem_id': 'wi-1', 'gates': gates, 'reviews': reviews}))
    report = workitem_trace.compute(root, 'wi-1')
    assert {'report:invalid-gates', 'report:invalid-reviews'} <= set(report['diagnostics'])
    assert report['status'] == 'partial'
    assert report['metrics']['failed_gates']['total'] is None
    assert 'SECRET' not in json.dumps(report)


@pytest.mark.parametrize('values', [[1e20, 1.0], [1e308, 1e308]])
def test_cost_precision_loss_and_overflow_never_produce_complete_total(traced, values):
    root, feature = traced
    (feature / 'usage-ledger.jsonl').write_text('\n'.join(json.dumps({
        'run_id': 'r1', 'cost': cost, 'cost_status': 'measured', 'usage_status': 'unavailable',
    }) for cost in values)+'\n')
    report = workitem_trace.compute(root, 'wi-1')
    assert report['metrics']['cost_usd']['total'] is None
    assert report['metrics']['cost_usd']['status'] == 'unknown'
    assert 'usage:cost-precision-or-overflow' in report['diagnostics']


def test_conflicting_event_id_cannot_prove_any_attempt_duration(tmp_path):
    feature = tmp_path / 'features' / 'wi-1'
    feature.mkdir(parents=True)
    start = {'kind': 'run_start', 'run_id': 'r1', 'workitem_id': 'wi-1', 'attempt_id': 'a1',
             'event_id': 'e1', 'timestamp': '2026-11-01T10:00:00Z'}
    for event in [start, dict(start, timestamp='2026-11-01T10:00:02Z'),
                  dict(start, kind='run_end', event_id='e2', timestamp='2026-11-01T10:00:03Z')]:
        assert lifecycle_store.journal_append(feature / 'lifecycle-journal.jsonl', event)['ok']
    report = workitem_trace.compute(tmp_path, 'wi-1')
    assert 'journal:duplicate-conflict' in report['diagnostics']
    assert not report['runs']
    assert not report['events']


def test_null_snapshot_sections_are_valid_absence_not_corruption(traced):
    root, feature = traced
    (feature / 'run-report.json').write_text(json.dumps({'workitem_id': 'wi-1', 'gates': None, 'reviews': None}))
    report = workitem_trace.compute(root, 'wi-1')
    assert not any(d.startswith('report:invalid-') for d in report['diagnostics'])
    assert report['metrics']['failed_gates'] == {'known': None, 'total': None, 'status': 'unknown'}
    assert not any(e['kind'] in ('review', 'gate') for e in report['events'])


def test_head_checksum_must_match_actual_journal_tail(traced):
    root, feature = traced
    path = feature / 'lifecycle-journal.jsonl.head'
    marker = json.loads(path.read_text())
    assert len(marker['checksum']) == 16  # реальный producer, а не авторская форма receipt
    marker['checksum'] = '0' * 16
    path.write_text(json.dumps(marker))
    report = workitem_trace.compute(root, 'wi-1')
    assert 'journal:corrupt' in report['diagnostics']
    assert not any(e['source'] == 'journal' for e in report['events'])
