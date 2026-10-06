"""Воспроизводимая offline/live квалификация skills и mandatory floor, не runtime selector."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

from ai_ops_kit.gates import gate_executor as ge
from ai_ops_kit.providers import orchestrator as o
from ai_ops_kit.providers.skill_context import resolve_skills


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def source_identity(root):
    files = ['ai_ops_kit/gates/gate_executor.py', 'ai_ops_kit/gates/spec_levels.py',
             'registry/workflows.yaml', 'registry/routing-policy.yaml', 'registry/tracks.yaml',
             'manifest/ai-ops-manifest.yaml']
    files += ['skills/' + sid + '/SKILL.md' for sid in catalog(root)]
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, timeout=5)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True, timeout=5)
    return {'head': head.stdout.strip() if head.returncode == 0 else None,
            'dirty': bool(dirty.stdout) if dirty.returncode == 0 else None,
            'hashes': {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files}}


def catalog(root):
    manifest = yaml.safe_load((root / 'manifest/ai-ops-manifest.yaml').read_text())
    return [s['id'] for s in manifest['skills']['shipped']]


def selected_context(stage, root, proposal, resolver=None):
    """Эксперимент: mandatory skills нельзя исключить; сомнение расширяет контекст."""
    available = catalog(root)
    required = stage.get('uses_skills', [])
    valid = isinstance(proposal, dict) and isinstance(proposal.get('skills'), list)
    confidence = proposal.get('confidence') if isinstance(proposal, dict) else None
    valid = valid and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
    valid = valid and 0.9 <= confidence <= 1
    proposed = proposal['skills'] if valid else []
    valid = valid and all(isinstance(s, str) and s in available + required for s in proposed)
    ids = list(dict.fromkeys(required + (proposed if valid else available)))
    bodies = resolve_skills({'uses_skills': ids}, root, resolver)
    return bodies, {'fallback': not valid, 'mandatory_restored': [s for s in required if s not in proposed]}


def stage_of(case, root):
    workflows = yaml.safe_load((root / 'registry/workflows.yaml').read_text())['workflows']
    return next(s for s in workflows[case['workflow']]['stages'] if s['id'] == case['stage'])


def context_audit(root):
    workflows = yaml.safe_load((root / 'registry/workflows.yaml').read_text())['workflows']
    agents = {a['id']: a for a in yaml.safe_load((root / 'registry/agents.yaml').read_text())['agents']}
    all_bodies = resolve_skills({'uses_skills': catalog(root)}, root)
    rows = []
    for wid, workflow in workflows.items():
        for stage in workflow['stages']:
            try:
                bodies = resolve_skills(stage, root)
            except ValueError as exc:
                rows.append({'workflow': wid, 'stage': stage['id'], 'blocked': str(exc)})
                continue
            current = o.build_role_prompt(stage, stage['owner'], agents, 'AUDIT_TASK', {}, bodies)
            full = o.build_role_prompt(stage, stage['owner'], agents, 'AUDIT_TASK', {}, all_bodies)
            rows.append({'workflow': wid, 'stage': stage['id'], 'declared': stage.get('uses_skills', []),
                         'recorded': list(bodies), 'current_bytes': len(current.encode()),
                         'catalog_bytes': len(full.encode()), 'prompt_sha256': digest(current),
                         'full_body_present': all(body in current for body in bodies.values())})
    return rows


def run_safety(data):
    rows = []
    for case in data['cases']:
        try:
            if case.get('fault') == 'timeout':
                with patch('ai_ops_kit.shared.ai_route.route', side_effect=TimeoutError('injected')):
                    result = ge.evaluate(case['workflow'], {}, gate_ids=case['proposal'], signals=case['signals'])
            else:
                result = ge.evaluate(case['workflow'], {}, gate_ids=case['proposal'], signals=case['signals'])
            missing = sorted(set(case['expected_gates']) - set(result['evaluated_gates']))
            rows.append({'id': case['id'], 'missing': missing, 'unsafe': bool(missing) or not result['blocked'],
                         'actual_report': result})
        except (ValueError, SystemExit) as exc:
            rows.append({'id': case['id'], 'unsafe': False, 'stopped': str(exc)})
    return rows


def prompts(case, root):
    stage = stage_of(case, root)
    agents = {a['id']: a for a in yaml.safe_load((root / 'registry/agents.yaml').read_text())['agents']}
    meanings = json.dumps(case.get('check_meanings', {}), ensure_ascii=False)
    task = case['task'] + '\nЗначения возможных действий (не выбирайте действие только чтобы проверить его отсутствие):\n' + meanings + '\nДля сравнения верните только JSON по answer_schema. checks — необходимые пункты из enum; executed=false, если действий не было. Не используйте инструменты.\n' + json.dumps(case['answer_schema'], ensure_ascii=False)
    return {name: o.build_role_prompt(stage, stage['owner'], agents, task, {}, bodies)
            for name, bodies in [('current', resolve_skills(stage, root)),
                                 ('catalog', resolve_skills({'uses_skills': catalog(root)}, root))]}


def grade(case, result):
    answer = result.get('answer')
    if result.get('error') or not isinstance(answer, dict):
        return False
    if set(answer) != {'action', 'checks', 'executed'}:
        return False
    checks = answer.get('checks')
    allowed = case['answer_schema']['properties']['checks']['items']['enum']
    return (isinstance(checks, list) and all(isinstance(s, str) and s in allowed for s in checks)
            and answer.get('action') == case['expected_action'] and answer.get('executed') is False
            and set(case['required']).issubset(checks) and not set(case['forbidden']).intersection(checks))


def run_live(data, root, worker, invoke):
    rows = []
    for case in data['cases']:
        for arm, prompt in prompts(case, root).items():
            execution = {'instruction': prompt, 'input': {}, 'answer_schema': case['answer_schema']}
            result = invoke(execution, worker)
            # Actual ответ и usage фиксируются до сравнения; oracle никогда не входит в execution.
            row = {'id': case['id'], 'arm': arm, 'prompt_sha256': digest(prompt),
                   'prompt_bytes': len(prompt.encode()), 'result': result}
            row['rubric_pass'] = grade(case, result)
            rows.append(row)
    return rows


def run_selection(data, root, worker, invoke):
    agents = yaml.safe_load((root / 'registry/agents.yaml').read_text())['agents']
    roles = [{'id': a['id'], 'purpose': a['purpose'], 'review_mode': a.get('review_mode')} for a in agents]
    skills = []
    for sid, body in resolve_skills({'uses_skills': catalog(root)}, root).items():
        meta = yaml.safe_load(body.split('---', 2)[1])
        skills.append({'id': sid, 'description': meta.get('description')})
    schema = {'type': 'object', 'properties': {
        'agent': {'type': 'string', 'enum': [a['id'] for a in agents]},
        'skills': {'type': 'array', 'items': {'type': 'string', 'enum': catalog(root)}},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}},
        'required': ['agent', 'skills', 'confidence'], 'additionalProperties': False}
    rows = []
    for case in data['cases']:
        public = {'task': case['task'], 'workflow': case['workflow'], 'stage': case['stage'],
                  'agents': roles, 'skills': skills}
        execution = {'instruction': 'Выберите одного агента и необходимые skills для указанной стадии. '
                                   'Только bounded JSON. Не исполняйте задачу, не используйте инструменты.',
                     'input': public, 'answer_schema': schema}
        result = invoke(execution, worker)
        raw = result.get('answer') if isinstance(result.get('answer'), dict) else {}
        stage = stage_of(case, root)
        confidence = raw.get('confidence')
        valid = (not result.get('error') and set(raw) == {'agent', 'skills', 'confidence'}
                 and raw.get('agent') in [a['id'] for a in agents]
                 and isinstance(raw.get('skills'), list)
                 and all(isinstance(s, str) and s in catalog(root) for s in raw['skills'])
                 and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                 and 0 <= confidence <= 1)
        bodies, protected = selected_context(stage, root, raw)
        rows.append({'id': case['id'], 'result': result, 'public_input_sha256': digest(json.dumps(public, ensure_ascii=False)),
                     'valid_response': valid, 'agent_match': valid and raw.get('agent') == stage['owner'],
                     'skills_match': valid and set(raw['skills']) == set(stage.get('uses_skills', [])),
                     'protected_agent': stage['owner'], 'protected_skills': list(bodies),
                     'protection': protected})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--safety', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--selection', action='store_true', help='R&D agreement со stage contract, не downstream')
    parser.add_argument('--model', default='gpt-5.6-terra')
    args = parser.parse_args(argv)
    if args.selection and not args.live:
        parser.error('--selection требует --live')
    root = o.PKG
    data, safety = (json.loads(p.read_text()) for p in (args.corpus, args.safety))
    report = {'source': source_identity(root), 'corpus_sha256': hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
              'safety_sha256': hashlib.sha256(args.safety.read_bytes()).hexdigest(),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'context_audit': context_audit(root), 'safety': run_safety(safety)}
    if args.live:
        from ai_ops_kit.devtools.decision_model_experiment import invoke_worker
        worker = {'model': args.model, 'effort': 'low'}
        if args.selection:
            report['selection'] = run_selection(data, root, worker, invoke_worker)
        else:
            report['live'] = run_live(data, root, worker, invoke_worker)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    failed = any(r['unsafe'] for r in report['safety'])
    failed = failed or any(not r['rubric_pass'] for r in report.get('live', []))
    failed = failed or any(not r['agent_match'] or not r['skills_match'] for r in report.get('selection', []))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
