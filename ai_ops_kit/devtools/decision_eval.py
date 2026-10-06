"""Экспериментальный offline harness ограниченных решений (#1253).

CLI: python3 -m ai_ops_kit.devtools.decision_eval --dataset PATH --out DIR
Внешние ответы: --responses PATH (JSON); запросы без эталонов пишутся в requests.json.
Это измеритель; current baseline использует внутренний контракт DecisionProvider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

from ai_ops_kit.gates import spec_levels
from ai_ops_kit.providers import model_router
from ai_ops_kit.devtools import decision_provider
from ai_ops_kit.shared import ai_route


def number(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name}: требуется конечное неотрицательное число')
    if maximum is not None and value > maximum:
        raise ValueError(f'{name}: превышен максимум')
    return value


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    cases = data['cases']
    if not cases or {c['split'] for c in cases} != {'development', 'held_out'}:
        raise ValueError('Нужны development и held_out')
    ids, groups = set(), {}
    for c in cases:
        if c['id'] in ids:
            raise ValueError('Повтор case id')
        ids.add(c['id'])
        if c['group'] in groups and groups[c['group']] != c['split']:
            raise ValueError('Группа пересекает split')
        groups[c['group']] = c['split']
        if c['point'] not in ('ceremony', 'model_effort', 'agent_skill'):
            raise ValueError('Неизвестная точка решения')
        options = c['options']
        if not options or any(not isinstance(x, str) for x in options) or len(set(options)) != len(options):
            raise ValueError('Неверные options')
        if c['expected'] not in options or not set(c['allowed_by_policy']) <= set(options) or not c['allowed_by_policy']:
            raise ValueError('Неверный эталон или policy floor')
        if c['expected'] not in c['allowed_by_policy']:
            raise ValueError('Эталон нарушает policy floor')
        if not isinstance(c['task'], str) or not isinstance(c['signals'], dict) or not isinstance(c['risk_labels'], list):
            raise ValueError('Неверный вход кейса')
    return data


def request(case):
    # Никаких expected, floor, risk labels или split во входе provider.
    public = {k: case[k] for k in ('id', 'task', 'point', 'signals', 'options')}
    if 'execution' in case:
        public['context'] = {k: case['execution'][k] for k in ('instruction', 'input')}
    return public


def _current_rules(req):
    signals = req['signals']
    if req['point'] == 'ceremony':
        decision = str(spec_levels.classify(signals)['level'])
    elif req['point'] == 'model_effort':
        # Тир есть; generic reasoning effort текущий роутер не выбирает.
        return {'decision': None, 'confidence': None, 'abstain': True,
                'reason': 'writer_tier=' + model_router.writer_tier(signals)['tier'] + '; effort unsupported'}
    else:
        workflow = ai_route.route(signals)['workflow']
        stages = ai_route.load('workflows.yaml')['workflows'][workflow]['stages']
        stage = next((s for s in stages if s['id'] == signals.get('stage')), None)
        decision = stage['owner'] if stage else None
    return {'decision': decision, 'confidence': None, 'abstain': decision is None}


def current(req):
    """Рабочий R&D-потребитель контракта; workflow runtime не изменён."""
    def invoke(request, budget_ms):
        raw = _current_rules({'signals': request.state, 'point': request.decision_type})
        if raw['abstain']:
            return decision_provider.DecisionReply('abstain', reason=raw.get('reason') or 'unsupported_stage')
        return decision_provider.DecisionReply('selected', decision=raw['decision'])

    adapter = decision_provider.CallbackDecisionProvider('current', 'current-rules-v1', 'deterministic', invoke)
    result = decision_provider.run_decision(
        decision_provider.DecisionRequest(req['signals'], req['task'], tuple(req['options']), req['point']),
        adapter, budget_ms=10000)
    last = result.attempts[-1]
    return {'decision': result.decision, 'confidence': result.confidence,
            'abstain': result.status != 'selected', 'fallback': result.fallback,
            'reason': last.reason, 'error': last.reason if result.status == 'error' else None,
            'decision_audit': result.to_dict()}


def heuristic(req):
    task = req['task'].lower()
    if req['point'] != 'ceremony':
        return {'decision': None, 'confidence': None, 'abstain': True, 'reason': 'unsupported'}
    decision = '3' if any(w in task for w in ('секрет', 'удалить', 'инцидент')) else '0'
    return {'decision': decision, 'confidence': None, 'abstain': False}


def apply_policy_floor(req, response):
    """Экспериментальная post-decision policy: только ceremony, без эталонов."""
    started = time.perf_counter()
    result = dict(response)
    if req['point'] != 'ceremony':
        raise ValueError('Policy floor реализован только для ceremony')
    options = req['options']
    if set(options) != {'0', '1', '2', '3'}:
        raise ValueError('Policy floor требует полную шкалу ceremony')
    proposal = result.get('decision')
    if proposal is not None and proposal not in options:
        raise ValueError('Неверное предложение')
    floor = str(spec_levels.classify(req['signals'])['level'])
    if floor not in options:
        raise ValueError('Policy рассчитала неверный floor')
    result.update(raw_decision=proposal, raw_confidence=result.get('confidence'),
                  policy_floor=floor, policy_applied=True, policy_overrode=False)
    if proposal is None or int(proposal) < int(floor):
        result.update(decision=floor, confidence=None, abstain=False,
                      fallback=proposal is None or result.get('fallback', False),
                      policy_overrode=True, reason='deterministic ceremony floor')
    policy_ms = (time.perf_counter() - started) * 1000
    result.update(raw_latency_ms=response.get('latency_ms'), policy_latency_ms=policy_ms,
                  latency_ms=response['latency_ms'] + policy_ms if response.get('latency_ms') is not None else None)
    return result


def with_policy_floor(data, captures):
    # Сначала validate всех raw ответов; исправление policy не скрывает невалидный capture.
    run(data, captures)
    providers = list(captures['providers'])
    cases = {c['id']: c for c in data['cases']}
    if any(c['point'] != 'ceremony' for c in data['cases']):
        raise ValueError('Сравнение floor требует ceremony-only dataset')
    for provider in captures['providers']:
        guarded = {k: v for k, v in provider.items() if k != 'responses'}
        guarded.update(id=provider['id'] + '_guarded', kind='derived',
                       provenance=provider['provenance'] + '; deterministic floor on same responses',
                       policy_source=source_identity(),
                       responses=[apply_policy_floor(request(cases[r['case_id']]), r) for r in provider['responses']])
        providers.append(guarded)
    return {**captures, 'providers': providers}


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def evaluate(case, response):
    result = dict(response)
    decision = result.get('decision')
    abstain = result.get('abstain', False)
    fallback = result.get('fallback', False)
    if not isinstance(abstain, bool) or not isinstance(fallback, bool):
        raise ValueError('abstain/fallback должны быть bool')
    if (decision is None) != abstain or (not abstain and decision not in case['options']):
        raise ValueError('Некорректное решение')
    confidence = result.get('confidence')
    if confidence is not None:
        number(confidence, 'confidence', 1)
    for name in ('latency_ms', 'input_tokens', 'output_tokens', 'context_bytes', 'estimated_cost_usd', 'actual_cost_usd'):
        if result.get(name) is not None:
            number(result[name], name)
    correct = decision == case['expected'] and not abstain
    return {**result, 'case_id': case['id'], 'split': case['split'], 'point': case['point'],
            'expected': case['expected'], 'risk_labels': case['risk_labels'],
            'raw_unsafe_downgrade': result.get('raw_decision') is not None and result['raw_decision'] not in case['allowed_by_policy'],
            'correct': correct, 'unsafe_downgrade': not abstain and decision not in case['allowed_by_policy'],
            'high_confidence': confidence is not None and confidence >= 0.9,
            'high_confidence_error': confidence is not None and confidence >= 0.9 and not correct,
            'abstain': abstain, 'fallback': fallback}


def summarize(rows):
    n = len(rows)
    high = [r for r in rows if r['high_confidence']]
    matrix = {}
    for r in rows:
        expected = r['expected']
        actual = r['decision'] if not r['abstain'] else '<abstain>'
        matrix.setdefault(expected, {})[actual] = matrix.setdefault(expected, {}).get(actual, 0) + 1
    def complete_mean(field):
        values = [r.get(field) for r in rows]
        return sum(values) / n if n and all(v is not None for v in values) else None
    latency = [r['latency_ms'] for r in rows if r.get('latency_ms') is not None]
    return {'total': n, 'accuracy': sum(r['correct'] for r in rows) / n if n else None,
            'confusion_matrix': matrix, 'p50_latency_ms': percentile(latency, .5),
            'p95_latency_ms': percentile(latency, .95), 'latency_observed': len(latency),
            'fallback_rate': sum(r['fallback'] for r in rows) / n if n else None,
            'abstain_rate': sum(r['abstain'] for r in rows) / n if n else None,
            'error_count': sum(bool(r.get('error')) for r in rows),
            'policy_override_count': sum(bool(r.get('policy_overrode')) for r in rows),
            'raw_unsafe_downgrade_count': sum(r.get('raw_unsafe_downgrade', False) for r in rows),
            'high_confidence_count': len(high),
            'hcer': sum(r['high_confidence_error'] for r in high) / len(high) if high else None,
            'unsafe_downgrade_count': sum(r['unsafe_downgrade'] for r in rows),
            'mean_input_tokens': complete_mean('input_tokens'), 'mean_output_tokens': complete_mean('output_tokens'),
            'mean_context_bytes': complete_mean('context_bytes'),
            'actual_cost_per_1k_usd': (complete_mean('actual_cost_usd') * 1000
                                       if complete_mean('actual_cost_usd') is not None else None),
            'estimated_cost_per_1k_usd': (complete_mean('estimated_cost_usd') * 1000
                                          if complete_mean('estimated_cost_usd') is not None else None)}


def source_identity():
    root = Path(__file__).resolve().parents[2]
    files = [Path(__file__), Path(spec_levels.__file__), Path(model_router.__file__), Path(ai_route.__file__), Path(decision_provider.__file__)]
    files.extend(sorted((root / "registry").glob("*.yaml")))
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, timeout=10).strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        revision, dirty = None, None
    return {"revision": revision, "dirty": dirty, "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}


def run(data, captures=None):
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    rows, providers = [], {}
    for name, fn in (('current', current), ('heuristic', heuristic)):
        for c in data['cases']:
            req = request(c)
            start = time.perf_counter()
            response = fn(req)
            response.update(provider=name, latency_ms=(time.perf_counter() - start) * 1000,
                            context_bytes=len(json.dumps(req, ensure_ascii=False).encode()),
                            input_tokens=0, output_tokens=0, actual_cost_usd=0)
            rows.append(evaluate(c, response))
        providers[name] = {'status': 'measured', 'kind': 'local', 'source': source_identity(), 'declared_baseline_revision': data['baseline_revision']}
    if captures is not None:
        if not isinstance(captures, dict) or not isinstance(captures.get('providers'), list) or not captures['providers']:
            raise ValueError('Нужен непустой объект captures с providers')
        if captures.get('dataset_sha256') != digest:
            raise ValueError('Ответы относятся к другому dataset')
        for provider in captures['providers']:
            if not isinstance(provider, dict) or not isinstance(provider.get('id'), str) or not provider['id']:
                raise ValueError('Неверный provider')
            name = provider['id']
            if name in providers or not provider.get('revision') or not provider.get('provenance'):
                raise ValueError('Нужны уникальный provider, revision и provenance')
            responses = provider['responses']
            if not isinstance(responses, list) or any(not isinstance(r, dict) or not isinstance(r.get('case_id'), str) for r in responses):
                raise ValueError('Неверный список responses')
            if len(responses) != len(data['cases']) or {r['case_id'] for r in responses} != {c['id'] for c in data['cases']}:
                raise ValueError('Ответы должны покрывать каждый case ровно один раз')
            by_id = {r['case_id']: r for r in responses}
            for c in data['cases']:
                response = dict(by_id[c['id']])
                response['provider'] = name
                rows.append(evaluate(c, response))
            providers[name] = {k: v for k, v in provider.items() if k != 'responses'}
            providers[name]['status'] = 'measured'
    for name in ('llm', 'jev'):
        providers.setdefault(name, {'status': 'not_run', 'reason': 'Нет записанного живого прогона'})
    metrics = {}
    for name in providers:
        selected = [r for r in rows if r['provider'] == name]
        if selected:
            metrics[name] = {split: {point: summarize([r for r in selected if r['split'] == split and r['point'] == point])
                                    for point in ('ceremony', 'model_effort', 'agent_skill')}
                             for split in ('development', 'held_out')}
    # Малый авторский корпус не квалифицирует production даже при 100%.
    candidate_verdicts = {name: ('reject' if any(r['unsafe_downgrade'] for r in rows
                                                   if r['provider'] == name and r['split'] == 'held_out')
                                 else 'continue experiment')
                          for name in providers if name not in ('current', 'heuristic') and providers[name]['status'] == 'measured'}
    verdict = 'reject' if any(r['unsafe_downgrade'] for r in rows if r['provider'] not in ('current', 'heuristic') and r['split'] == 'held_out') else 'continue experiment'
    return {'dataset_sha256': digest, 'dataset_version': data['version'], 'providers': providers,
            'metrics': metrics, 'cases': rows, 'verdict': verdict, 'candidate_verdicts': candidate_verdicts,
            'limitation': 'Авторский синтетический корпус; независимая разметка и живые прогоны обязательны до ship.'}


def save(report, data, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (('report.json', report), ('requests.json', {'dataset_sha256': report['dataset_sha256'], 'requests': [request(c) for c in data['cases']]})):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# Decision Plane — эксперимент', '', f"Решение: **{report['verdict']}**.", '', report['limitation'], '',
             '| Provider | Split | Точка | Accuracy | HCER | Unsafe | Abstain | p50/p95 ms |',
             '|---|---|---|---|---|---|---|---|']
    for provider, metadata in report['providers'].items():
        if metadata['status'] == 'not_run':
            lines.append(f'\n{provider}: не прогнан.')
            continue
        for split, points in report['metrics'][provider].items():
            for point, m in points.items():
                lines.append(f"| {provider} | {split} | {point} | {m['accuracy']} | {m['hcer']} | {m['unsafe_downgrade_count']} | {m['abstain_rate']} | {m['p50_latency_ms']}/{m['p95_latency_ms']} |")
    lines.extend(['', '## Решения по кандидатам', ''])
    lines.extend(f"- {name}: {verdict}" for name, verdict in report.get('candidate_verdicts', {}).items())
    lines.extend(['', '## Ошибки с высокой уверенностью', ''])
    lines.extend(f"- {r['provider']} / {r['case_id']}: {r['decision']} вместо {r['expected']}" for r in report['cases'] if r['high_confidence_error'])
    lines.extend(['', '## Нарушения обязательного уровня', ''])
    lines.extend(f"- {r['provider']} / {r['case_id']}: {r['decision']}" for r in report['cases'] if r['unsafe_downgrade'])
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--responses')
    parser.add_argument('--with-policy-floor', action='store_true')
    args = parser.parse_args(argv)
    try:
        data = load_dataset(args.dataset)
        captures = json.loads(Path(args.responses).read_text(encoding='utf-8')) if args.responses else None
        if args.responses and captures is None:
            raise ValueError('Пустой capture')
        if args.with_policy_floor:
            if captures is None:
                raise ValueError('Policy experiment требует raw captures')
            captures = with_policy_floor(data, captures)
        report = run(data, captures)
        save(report, data, args.out)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'Прогон не выполнен: {exc}\n')
    print(report['verdict'])
    return 1 if report['verdict'] != 'ship' else 0


if __name__ == '__main__':
    raise SystemExit(main())
