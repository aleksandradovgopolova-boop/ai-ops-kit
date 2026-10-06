"""#1250: offline experiment выбора model/effort с живыми bounded JSON worker задачами."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ai_ops_kit.devtools import decision_eval as ev
from ai_ops_kit.providers import model_router

CHOICES = ['fast/low', 'balanced/medium', 'deep/high', 'strongest/high', 'human-required']


def floor(signals):
    required = signals.get('model_policy_floor', 'fast/low')
    if required not in CHOICES:
        raise ValueError('Неверный model_policy_floor')
    risk_floor = 'fast/low'
    if signals.get('human_approval_required') or signals.get('destructive') or signals.get('irreversible'):
        risk_floor = 'human-required'
    elif signals.get('risk') == 'critical' or signals.get('secret_boundary'):
        risk_floor = 'strongest/high'
    elif signals.get('risk') == 'high':
        risk_floor = 'deep/high'
    return CHOICES[max(CHOICES.index(required), CHOICES.index(risk_floor))]


def baseline(signals):
    tier = model_router.writer_tier(signals)['tier']
    choice = 'balanced/medium' if tier == 'cheap-api' else 'deep/high'
    return CHOICES[max(CHOICES.index(choice), CHOICES.index(floor(signals)))]


def select(req, proposal, workers, threshold):
    ev.number(threshold, 'threshold', 1)
    if req['options'] != CHOICES:
        raise ValueError('Неверная шкала model choices')
    raw = proposal.get('decision')
    if raw is not None and raw not in CHOICES:
        raise ValueError('Неограниченное решение')
    confidence = proposal.get('confidence')
    if confidence is not None:
        ev.number(confidence, 'confidence', 1)
    required = floor(req['signals'])
    fallback = raw is None or confidence is None or confidence < threshold
    chosen = baseline(req['signals']) if fallback else raw
    chosen = CHOICES[max(CHOICES.index(chosen), CHOICES.index(required))]
    unavailable = chosen != 'human-required' and workers.get(chosen) is None
    if unavailable:
        chosen = 'human-required'
    return {'raw_decision': raw, 'raw_confidence': confidence, 'decision': chosen,
            'policy_floor': required, 'fallback': fallback, 'worker_unavailable': unavailable,
            'policy_overrode': chosen != raw,
            'independent_review_required': bool(req['signals'].get('independent_review_required'))}


def invoke_worker(execution, worker, runner=subprocess.run, binary=None):
    binary = binary or shutil.which('codex')
    if not binary:
        raise ValueError('Нет Codex CLI')
    # Oracle и routing expected не попадают в prompt.
    public = {k: execution[k] for k in ('instruction', 'input', 'answer_schema')}
    prompt = 'Выполните только вычисление по заданию и верните JSON. Не используйте инструменты.\n' + json.dumps(public, ensure_ascii=False)
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='model-worker-') as cwd:
        schema = Path(cwd) / 'schema.json'
        schema.write_text(json.dumps(public['answer_schema']), encoding='utf-8')
        cmd = [binary, 'exec', '--model', worker['model'], '--sandbox', 'read-only', '--skip-git-repo-check',
               '--ephemeral', '--json', '--output-schema', str(schema), '-c', 'features.shell_tool=false',
               '-c', 'features.multi_agent=false', '-c', 'web_search="disabled"', '-c', 'mcp_servers={}',
               '-c', 'model_reasoning_effort=' + json.dumps(worker['effort'])]
        try:
            result = runner(cmd, input=prompt, text=True, capture_output=True, cwd=cwd, timeout=120)
        except subprocess.TimeoutExpired:
            return {'model': worker['model'], 'effort': worker['effort'], 'actual_revision': None,
                    'latency_ms': (time.perf_counter() - start) * 1000, 'answer': None,
                    'error': 'runtime_timeout', 'raw_events': [], 'context_bytes': len(prompt.encode()),
                    'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}

    row = {'runtime_returncode': result.returncode, 'model': worker['model'], 'effort': worker['effort'], 'actual_revision': None,
           'latency_ms': (time.perf_counter() - start) * 1000, 'raw_events': [],
           'context_bytes': len(prompt.encode()), 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
    try:
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        row['raw_events'] = events
        if any(not isinstance(e, dict) or ('item' in e and not isinstance(e['item'], dict)) for e in events):
            raise ValueError('invalid event structure')
        turns = [e for e in events if e.get('type') == 'turn.completed']
        if len(turns) == 1:
            row['usage'] = turns[0].get('usage', {})
            if not isinstance(row['usage'], dict):
                raise ValueError('invalid usage')
            for k in ('input_tokens', 'output_tokens'):
                if k in row['usage']:
                    ev.number(row['usage'][k], k)
                    row[k] = row['usage'][k]
    except (ValueError, TypeError):
        return {**row, 'answer': None, 'error': 'invalid_runtime_result'}
    items = [e['item'] for e in events if isinstance(e.get('item'), dict)]
    messages = [e['item'].get('text') for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
    if (result.returncode or any(e.get('type') in ('error', 'turn.failed') for e in events)
            or any(i.get('type') not in ('agent_message', 'reasoning', 'error') for i in items)
            or len(messages) != 1 or len(turns) != 1):
        return {**row, 'answer': None, 'error': 'invalid_runtime_result'}
    try:
        answer = json.loads(messages[0])
        if not isinstance(answer, dict):
            raise ValueError('worker должен вернуть object')
    except (ValueError, TypeError):
        return {**row, 'answer': None, 'error': 'invalid_json_answer'}
    return {**row, 'answer': answer}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def run(data, captures, config, call=invoke_worker):
    experiment_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # Проверяет dataset identity, полноту и исходные bounded ответы ДО применения policy.
    raw_report = ev.run(data, captures)
    if any(c['point'] != 'model_effort' for c in data['cases']):
        raise ValueError('Нужен model-only dataset')
    if set(config['workers']) != set(CHOICES):
        raise ValueError('Неполная экспериментальная worker map')
    for worker in config['workers'].values():
        if worker is not None and (not worker.get('model') or worker.get('effort') not in ('low', 'medium', 'high')):
            raise ValueError('Неверный worker')
    providers = [p for p in captures['providers'] if p['id'] == 'jev']
    if len(providers) != 1:
        raise ValueError('Нужен один raw Jev provider')
    by_id = {r['case_id']: r for r in providers[0]['responses']}
    rows, executions = [], []
    for case in data['cases']:
        req = ev.request(case)
        original = by_id[case['id']]
        chosen = select(req, original, config['workers'], config['confidence_threshold'])
        base = select(req, {'decision': baseline(case['signals']), 'confidence': 1}, config['workers'], 0)
        observed = {}
        for path, selection in (('baseline', base), ('jev', chosen)):
            route = selection['decision']
            stopped = route == 'human-required'
            worker = config['workers'].get(route)
            key = canonical(worker) if worker is not None else None
            reused = key in observed if key is not None else False
            if not stopped and not reused:
                started = time.perf_counter()
                try:
                    result = call(case['execution'], worker)
                    # Доказательство результата: answer сохранён до oracle comparison.
                    canonical(result.get('answer'))
                except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
                    result = {'answer': None, 'error': type(exc).__name__, 'latency_ms': (time.perf_counter() - started) * 1000}
                observed[key] = result
                executions.append({'case_id': case['id'], 'worker': worker, **result})
            result = observed.get(key, {}) if not stopped else {}
            actual_answer = result.get('answer')
            correct = not stopped and not result.get('error') and canonical(actual_answer) == canonical(case['execution']['expected_answer'])
            router_ms = original.get('latency_ms') if path == 'jev' else 0
            row = {'case_id': case['id'], 'split': case['split'], 'path': path, **selection,
                   'stopped_for_human': stopped, 'shared_worker_result': reused,
                   'downstream_correct': correct, 'answer': actual_answer,
                   'unsafe_downgrade': CHOICES.index(route) < CHOICES.index(selection['policy_floor']),
                   'error': result.get('error'), 'worker_latency_ms': result.get('latency_ms'),
                   'router_latency_ms': router_ms,
                   'total_latency_ms': (router_ms + result['latency_ms']) if router_ms is not None and result.get('latency_ms') is not None else None,
                   'input_tokens': result.get('input_tokens'), 'output_tokens': result.get('output_tokens'),
                   'router_input_tokens': original.get('input_tokens') if path == 'jev' else 0,
                   'router_output_tokens': original.get('output_tokens') if path == 'jev' else 0}
            if row['input_tokens'] is not None and row['router_input_tokens'] is not None:
                row['total_input_tokens'] = row['input_tokens'] + row['router_input_tokens']
            if row['output_tokens'] is not None and row['router_output_tokens'] is not None:
                row['total_output_tokens'] = row['output_tokens'] + row['router_output_tokens']
            rows.append(row)
    metrics = {}
    for split in ('development', 'held_out'):
        common_ids = {r['case_id'] for r in rows if r['split'] == split and r['path'] == 'baseline' and not r['stopped_for_human']} & {r['case_id'] for r in rows if r['split'] == split and r['path'] == 'jev' and not r['stopped_for_human']}
        metrics[split] = {}
        for path in ('baseline', 'jev'):
            selected = [r for r in rows if r['split'] == split and r['path'] == path]
            paired = [r for r in selected if r['case_id'] in common_ids]
            def mean(field, measured=paired):
                values = [r.get(field) for r in measured]
                return sum(values) / len(values) if values and all(x is not None for x in values) else None
            latencies = [r['total_latency_ms'] for r in paired if r['total_latency_ms'] is not None]
            metrics[split][path] = {'total': len(selected), 'paired_executed': len(paired),
                                    'paired_correct': sum(r['downstream_correct'] for r in paired),
                                    'human_stops': sum(r['stopped_for_human'] for r in selected),
                                    'fallback_count': sum(r['fallback'] for r in selected),
                                    'unsafe_downgrade_count': sum(r['unsafe_downgrade'] for r in selected),
                                    'mean_total_input_tokens': mean('total_input_tokens'),
                                    'mean_total_output_tokens': mean('total_output_tokens'),
                                    'mean_total_latency_ms': mean('total_latency_ms'),
                                    'p50_total_latency_ms': ev.percentile(latencies, .5),
                                    'p95_total_latency_ms': ev.percentile(latencies, .95),
                                    'actual_cost_usd': None}
    b, j = metrics['held_out']['baseline'], metrics['held_out']['jev']
    if j['unsafe_downgrade_count'] or j['paired_correct'] < b['paired_correct'] or j['human_stops'] > b['human_stops']:
        verdict = 'reject'
    elif (b['paired_executed'] and j['paired_correct'] == b['paired_correct']
          and b['mean_total_latency_ms'] is not None and j['mean_total_latency_ms'] is not None
          and j['mean_total_latency_ms'] >= b['mean_total_latency_ms']
          and b['mean_total_input_tokens'] is not None and j['mean_total_input_tokens'] is not None
          and j['mean_total_input_tokens'] >= b['mean_total_input_tokens']):
        verdict = 'park'
    else:
        verdict = 'continue experiment'
    return {'dataset_sha256': raw_report['dataset_sha256'], 'config': config,
            'config_sha256': hashlib.sha256(canonical(config).encode()).hexdigest(),
            'raw_router_metrics': raw_report['metrics'].get('jev'), 'raw_router_cases': [r for r in raw_report['cases'] if r['provider'] == 'jev'],
            'source': ev.source_identity(), 'experiment_source_sha256': experiment_source_sha256, 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'cases': rows, 'executions': executions, 'metrics': metrics, 'verdict': verdict,
            'limitations': 'Малый синтетический reasoning JSON benchmark, не квалификация writer. Shared same-worker outputs; стоимость подписки неизвестна; обязательный review не удаляется, product changes не выполняются.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--responses', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        report = run(ev.load_dataset(args.dataset), json.loads(Path(args.responses).read_text()), json.loads(Path(args.config).read_text()))
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'Эксперимент не выполнен: {exc}\n')
    print(report['verdict'])
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
