"""Read-only проекция существующих локальных receipts одного WorkItem (#1411).

Не instrumentation и не OTel exporter. Порядок доказан внутри источника, связь
между источниками — только по явным id. Свободный текст никогда не копируется.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from ai_ops_kit.shared import lifecycle_store, usage_ledger

_KINDS = frozenset(('run_start', 'run_end', 'run_cost', 'fix_attempt', 'package_end',
                    'ready_for_delivery', 'delivery_intent', 'delivery_receipt',
                    'delivery', 'delivery_outcome_unknown', 'delivery_reconciled', 'delivery_stale'))
_STATUSES = frozenset(('pass', 'fail', 'warn', 'skip', 'ready', 'not-ready', 'error',
                       'blocked', 'needs-changes', 'unknown', 'unavailable'))


def _ref(value):
    """Псевдонимизация id: не переносим секрет, даже если он попал в поле идентификатора."""
    if not isinstance(value, (str, int)) or isinstance(value, bool) or value == '':
        return None
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:24]


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _duration(start, end):
    a, b = _timestamp(start), _timestamp(end)
    return (b-a).total_seconds() if a and b and b >= a else None


def _source(feature, filename, label, diagnostics):
    path = feature / filename
    # Отказываем всем symlink-компонентам, включая каталог features и сам WorkItem.
    if any(p.is_symlink() for p in (path, *path.parents)):
        diagnostics.append(label + ':unsafe-path')
        return None
    return path


def _read_usage(path, diagnostics):
    if path is None or not path.exists():
        return [], False
    rows, clean = [], True
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError
                rows.append(row)
            except ValueError:
                clean = False
    except (OSError, UnicodeError):
        clean = False
    if not clean:
        diagnostics.append('usage:corrupt')
    return rows, clean


def _read_journal(path, diagnostics):
    if path is None:
        return []
    head = Path(str(path) + '.head')
    if head.is_symlink():
        diagnostics.append('journal:unsafe-path')
        return []
    if not path.exists():
        if head.exists():
            diagnostics.append('journal:missing-with-head')
        return []
    try:
        marker = None
        if head.exists():
            marker = json.loads(head.read_text(encoding='utf-8'))
            if (not isinstance(marker, dict) or marker.get('kind') != 'journal-head'
                    or type(marker.get('seq')) is not int or marker['seq'] < 0
                    or not isinstance(marker.get('checksum'), str)
                    or not marker['checksum']):
                raise ValueError
        result = lifecycle_store.journal_read(path)
        if not result['ok']:
            diagnostics.append('journal:corrupt')
            return []  # не публикуем непроверенный prefix повреждённой цепочки
        rows = result['events']
        if marker is not None and not any(
                row.get('seq') == marker['seq'] and row.get('checksum') == marker['checksum']
                for row in rows):
            raise ValueError
        if lifecycle_store.validate_trace(rows):
            diagnostics.append('journal:invalid-links')
        seen, output = {}, []
        for row in rows:
            event_id = _ref(row.get('event_id'))
            payload = {k: v for k, v in row.items() if k not in ('seq', 'checksum', 'prev_checksum')}
            if event_id and event_id in seen:
                if seen[event_id] != payload:
                    diagnostics.append('journal:duplicate-conflict')
                    return []  # ни одна из конфликтующих версий не подтверждает timing
                continue
            if event_id:
                seen[event_id] = payload
            output.append(row)
        return output
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        diagnostics.append('journal:corrupt')
        return []


def _read_report(path, wid, diagnostics):
    if path is None or not path.exists():
        return {}
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(report, dict) or str(report.get('workitem_id')) != wid:
            raise ValueError
        return report
    except (OSError, UnicodeError, ValueError):
        diagnostics.append('report:corrupt-or-unbound')
        return {}


def _event(kind, source, ordinal, row):
    return {'id': f'{source}:{ordinal}', 'kind': kind, 'source': source,
            'source_order': ordinal, 'run_id': _ref(row.get('run_id')),
            'attempt_id': _ref(row.get('attempt_id')), 'package_id': _ref(row.get('package_id')),
            'status': row.get('status') if isinstance(row.get('status'), str) and row['status'] in _STATUSES else None,
            'duration_s': _duration(row.get('started_at'), row.get('ended_at'))}


def _journal_events(rows, wid, diagnostics):
    events, runs = [], {}
    for i, row in enumerate(rows):
        if row.get('workitem_id') is not None and str(row['workitem_id']) != wid:
            diagnostics.append('journal:workitem-mismatch')
            continue
        kind = row.get('kind')
        if not isinstance(kind, str) or kind not in _KINDS:
            diagnostics.append('journal:unsupported-event')
            continue
        event = _event(kind, 'journal', i, row)
        events.append(event)
        run = event['run_id']
        if run is None:
            diagnostics.append('journal:missing-run')
            continue
        attempts = runs.setdefault(run, {})
        attempt = event['attempt_id']
        if attempt is not None and kind in ('run_start', 'run_end'):
            state = attempts.setdefault(attempt, {'starts': [], 'ends': []})
            state['starts' if kind == 'run_start' else 'ends'].append(row.get('timestamp'))
    output = []
    for run, attempts in runs.items():
        items = []
        for attempt, state in attempts.items():
            starts, ends = state['starts'], state['ends']
            duration = _duration(starts[0], ends[0]) if len(starts) == len(ends) == 1 else None
            items.append({'id': attempt, 'duration_s': duration,
                          'timing_status': 'known' if duration is not None else 'unknown'})
        output.append({'id': run, 'attempts': items})
    return events, output


def _metric(values, complete=False):
    known = None
    if values:
        try:
            known = math.fsum(values) if any(isinstance(v, float) for v in values) else sum(values)
        except OverflowError:
            complete = False
        if isinstance(known, float) and not math.isfinite(known):
            known, complete = None, False
    return {'known': known, 'total': known if complete else None,
            'status': 'known' if complete and known is not None else 'unknown'}


def _usage_events(rows, clean, wid, diagnostics):
    events, costs, inputs, outputs, retries = [], [], [], [], []
    for i, row in enumerate(rows):
        if row.get('workitem_id') is not None and str(row['workitem_id']) != wid:
            diagnostics.append('usage:workitem-mismatch')
            clean = False
            continue
        event = _event('invocation', 'usage', i, row)
        if event['run_id'] is None:
            diagnostics.append('usage:missing-run')
        attrs = {}
        for field, values in [('input_tokens', inputs), ('output_tokens', outputs)]:
            value = row.get(field)
            if (row.get('usage_status') in ('measured', 'estimated')
                    and isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                values.append(value)
                attrs['gen_ai.usage.' + field] = value
        price = usage_ledger.cost_value(row.get('cost'))
        if price is not None and row.get('cost_status') in ('measured', 'estimated'):
            costs.append(price)
        trigger = row.get('trigger')
        if trigger in usage_ledger.TRIGGERS:
            retries.append(int(trigger == 'retry'))
        event['attributes'] = attrs
        events.append(event)
    count = len(events)
    metrics = {'invocations': _metric([count] if rows else [], clean and bool(rows))}
    for key, values in [('cost_usd', costs), ('input_tokens', inputs),
                        ('output_tokens', outputs), ('retries', retries)]:
        metrics[key] = _metric(values, clean and count > 0 and len(values) == count)
    cost_check = usage_ledger.aggregate([{'cost': value, 'cost_status': 'measured',
                                         'usage_status': 'unavailable'} for value in costs])
    if cost_check['cost_precision_lost'] or cost_check['cost_overflow']:
        metrics['cost_usd'].update(total=None, status='unknown')
        diagnostics.append('usage:cost-precision-or-overflow')
    return events, metrics


def _snapshot_events(report, diagnostics):
    events = []
    gates = report.get('gates')
    if gates is not None and not isinstance(gates, dict):
        diagnostics.append('report:invalid-gates')
    if isinstance(gates, dict):
        evaluated, unmet = gates.get('evaluated'), gates.get('unmet')
        if not isinstance(evaluated, list) or not isinstance(unmet, list):
            diagnostics.append('report:invalid-gates')
        if isinstance(evaluated, list) and isinstance(unmet, list):
            for i, gate in enumerate(evaluated):
                if not isinstance(gate, str):
                    diagnostics.append('report:invalid-gate')
                    continue
                event = _event('gate', 'report', i, {})
                # Отсутствие в unmet само по себе не доказывает pass (warn/skip существуют).
                event.update(gate_id=_ref(gate), status='fail' if gate in unmet else None,
                             scope='latest-snapshot')
                events.append(event)
    reviews = report.get('reviews')
    if reviews is not None and not isinstance(reviews, list):
        diagnostics.append('report:invalid-reviews')
    if isinstance(reviews, list):
        for i, review in enumerate(reviews):
            if not isinstance(review, dict):
                diagnostics.append('report:invalid-review')
                continue
            event = _event('review', 'report-review', i, review)
            event.update(gate_id=_ref(review.get('gate')), scope='latest-snapshot')
            events.append(event)
    return events


def _history_directories(feature, directory, diagnostics):
    safe = _source(feature, directory.relative_to(feature), 'package-history', diagnostics)
    if safe is None or not safe.exists():
        return []
    try:
        return [p for p in sorted(safe.iterdir())
                if _source(feature, p.relative_to(feature), 'package-history', diagnostics) is not None
                and p.is_dir()]
    except OSError:
        diagnostics.append('package-history:unreadable-directory')
        return []


def _package_paths(feature, diagnostics):
    paths = []
    for package in _history_directories(feature, feature / 'work-packages', diagnostics):
        archived = []
        for attempt in _history_directories(feature, package / 'attempts', diagnostics):
            if re.fullmatch(r'attempt-[1-9][0-9]{0,8}', attempt.name):
                archived.append((int(attempt.name[8:]), attempt / 'report.json'))
            else:
                diagnostics.append('package-history:invalid-attempt-directory')
        paths += [(package.name, n, path) for n, path in sorted(archived)]
        paths.append((package.name, None, package / 'report.json'))
    return paths


def _tool_attempts(report, diagnostics):
    loop = report.get('loop')
    if loop is None:
        return []
    if not isinstance(loop, dict):
        diagnostics.append('package-history:invalid-tool-metadata')
        return []
    metadata = loop.get('transcript')
    if metadata is None:
        return []
    if not isinstance(metadata, list) or len(metadata) > 40:
        diagnostics.append('package-history:invalid-tool-metadata')
        return []
    events, steps = [], set()
    for i, item in enumerate(metadata):
        if not isinstance(item, dict):
            diagnostics.append('package-history:invalid-tool-metadata')
            continue
        if item.get('done') is True and 'op' not in item:
            continue
        step = item.get('step')
        if type(step) is not int or step < 0 or type(item.get('allowed')) is not bool:
            diagnostics.append('package-history:invalid-tool-metadata')
            continue
        if step in steps:
            diagnostics.append('package-history:ambiguous-tool-steps')
            return []
        steps.add(step)
        op = item.get('op')
        if not isinstance(op, str) or op not in ('read', 'write', 'shell', 'git'):
            diagnostics.append('package-history:unsupported-tool-op')
            continue
        event = _event('tool_attempt', 'package-tool', i, {})
        event.update(step=step, operation=op, allowed=item['allowed'],
                     ok=item.get('ok') if type(item.get('ok')) is bool else None)
        events.append(event)
    return events


def _package_history(feature, wid, diagnostics):
    snapshots, events = [], []
    for package, number, candidate in _package_paths(feature, diagnostics):
        path = _source(feature, candidate.relative_to(feature), 'package-history', diagnostics)
        if path is None:
            continue
        if not path.is_file():
            if number is not None:
                diagnostics.append('package-history:missing-report')
            continue
        errors = []
        report = _read_report(path, wid, errors)
        if errors or report.get('kind') != 'execution-pipeline':
            diagnostics.append('package-history:corrupt-or-unbound')
            continue
        snapshot_id = _ref(candidate.relative_to(feature).as_posix())
        scope = 'current-package' if number is None else 'archived-package'
        context = {'snapshot_id': snapshot_id, 'package_id': _ref(package), 'scope': scope}
        observations = _snapshot_events(report, errors) + _tool_attempts(report, diagnostics)
        diagnostics.extend(e.replace('report:', 'package-history:') for e in errors)
        for event in observations:
            event.update(context, id=snapshot_id + ':' + event['id'], source='package-history',
                         run_id=None, attempt_id=None, duration_s=None)
        events.extend(observations)
        snapshots.append({'id': snapshot_id, 'package_id': _ref(package),
                          'scope': scope, 'storage_attempt': number})
    return snapshots, events


def compute(child_root: str | Path, workitem_id: str) -> dict:
    """Локальная частичная трасса; total относится к читаемому ledger, не ко всем реальным вызовам."""
    if not isinstance(workitem_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', workitem_id):
        raise ValueError('workitem id must be a single safe path component')
    root = Path(child_root).resolve()
    feature = root / 'features' / workitem_id
    diagnostics = []
    journal = _source(feature, 'lifecycle-journal.jsonl', 'journal', diagnostics)
    usage = _source(feature, 'usage-ledger.jsonl', 'usage', diagnostics)
    report_path = _source(feature, 'run-report.json', 'report', diagnostics)
    rows = _read_journal(journal, diagnostics)
    events, runs = _journal_events(rows, workitem_id, diagnostics)
    calls, clean = _read_usage(usage, diagnostics)
    invocations, metrics = _usage_events(calls, clean, workitem_id, diagnostics)
    for event in invocations:
        if event['run_id'] and not any(r['id'] == event['run_id'] for r in runs):
            runs.append({'id': event['run_id'], 'attempts': []})
    snapshot = _read_report(report_path, workitem_id, diagnostics)
    events += invocations + _snapshot_events(snapshot, diagnostics)
    failed = [e for e in events if e['kind'] == 'gate' and e['status'] == 'fail']
    metrics['failed_gates'] = _metric([len(failed)] if any(e['kind'] == 'gate' for e in events) else [])
    for name in ('tool_calls', 'human_interventions'):
        metrics[name] = _metric([])
    snapshots, history = _package_history(feature, workitem_id, diagnostics)
    events += history
    return {'kind': 'WorkItemTrace', 'schema_version': 1, 'workitem_id': _ref(workitem_id),
            'status': 'partial' if diagnostics else ('observed' if events else 'no-data'),
            'coverage': 'existing-local-records-only', 'order': 'within-source-only',
            'runs': runs, 'events': events, 'snapshots': snapshots, 'metrics': metrics,
            'diagnostics': sorted(set(diagnostics))}


def format_text(report: dict) -> str:
    """Детерминированный текст без raw полей источников."""
    lines = [f"WorkItem trace {report['workitem_id']} ({report['status']})",
             'Порядок: внутри источника; межисточниковое время unknown.']
    for run in report['runs']:
        lines.append('Run ' + run['id'])
        for attempt in run['attempts']:
            duration = attempt['duration_s']
            lines.append(f"  Attempt {attempt['id']}: {duration if duration is not None else 'unknown'} s")
    for snapshot in report.get('snapshots', []):
        storage = snapshot['storage_attempt']
        lines.append(f"Snapshot {snapshot['id']} {snapshot['scope']} package={snapshot['package_id']} "
                     f"storage_attempt={storage if storage is not None else 'unknown'}")
    for event in report['events']:
        lines.append(f"  {event['id']} {event['kind']} run={event['run_id'] or 'unknown'} "
                     f"attempt={event['attempt_id'] or 'unknown'} status={event['status'] or 'unknown'} "
                     f"package={event.get('package_id') or 'unknown'} snapshot={event.get('snapshot_id') or 'unknown'}")
        if event['kind'] == 'tool_attempt':
            result = event['ok'] if event['ok'] is not None else 'unknown'
            lines[-1] += (f" operation={event['operation']} step={event['step']}"
                          f" allowed={event['allowed']} ok={result}")
    for name, metric in report['metrics'].items():
        lines.append(f"{name}: {metric['total'] if metric['total'] is not None else 'unknown'} "
                     f"(known={metric['known'] if metric['known'] is not None else 'unknown'})")
    lines.extend(report['diagnostics'])
    return '\n'.join(lines)
