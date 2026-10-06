"""Экспериментальный LLM baseline через установленный Codex CLI, без API-ключа в коде."""
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

from ai_ops_kit.devtools import decision_capture as jev
from ai_ops_kit.devtools import decision_eval as ev


class InvalidResponse(ValueError):
    def __init__(self, evidence):
        super().__init__("Невалидный LLM ответ")
        self.evidence = evidence


def one(req, model, runner=subprocess.run, binary=None):
    binary = binary or shutil.which('codex')
    if not binary:
        raise ValueError('Codex CLI не найден')
    # Те же state / instructions / criteria; wire model не является входом классификации.
    question = jev.payload(req, model)
    prompt = ('Выберите решение по state и questions. Используйте только данный вход, без инструментов. '
              'Верните JSON decision (один из вариантов criteria), confidence (0..1).\n' +
              json.dumps({k: question[k] for k in ('state', 'questions')}, ensure_ascii=False))
    schema = {'type': 'object', 'properties': {'decision': {'type': 'string', 'enum': req['options']},
                                             'confidence': {'type': 'number'}},
              'required': ['decision', 'confidence'], 'additionalProperties': False}
    with tempfile.TemporaryDirectory(prefix='decision-llm-') as cwd:
        path = Path(cwd) / 'schema.json'
        path.write_text(json.dumps(schema), encoding='utf-8')
        command = [binary, 'exec', '--model', model, '--sandbox', 'read-only', '--skip-git-repo-check',
                   '--ephemeral', '--json', '--output-schema', str(path),
                   '-c', 'features.shell_tool=false', '-c', 'features.multi_agent=false',
                   '-c', 'web_search="disabled"', '-c', 'mcp_servers={}', '-c', 'model_reasoning_effort="low"']
        result = runner(command, input=prompt, text=True, capture_output=True, cwd=cwd, timeout=60)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or any(e.get('type') in ('error', 'turn.failed') for e in events):
        raise ValueError('LLM runtime отказал; ответ не измерен')
    turns = [e for e in events if e.get('type') == 'turn.completed']
    evidence = {'context_bytes': len(prompt.encode()),
                'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'raw_events': events}
    if len(turns) == 1:
        usage = turns[0].get('usage', {})
        for field in ('input_tokens', 'output_tokens'):
            if usage.get(field) is not None:
                ev.number(usage[field], field)
                evidence[field] = usage[field]
        evidence['usage'] = usage
    try:
        all_items = [e['item'] for e in events if isinstance(e.get('item'), dict)]
        if any(i.get('type') not in ('agent_message', 'reasoning') for i in all_items):
            raise ValueError('LLM использовал инструменты')
        messages = [e['item']['text'] for e in events
                    if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
        if len(messages) != 1 or len(turns) != 1:
            raise ValueError('Неполный LLM результат')
        answer = json.loads(messages[0])
        ev.number(answer['confidence'], 'confidence', 1)
        if answer['decision'] not in req['options']:
            raise ValueError('LLM решение вне options')
        if 'input_tokens' not in evidence or 'output_tokens' not in evidence:
            raise ValueError('LLM не сообщил usage')
    except (ValueError, KeyError, TypeError):
        raise InvalidResponse(evidence) from None
    return {**evidence, 'decision': answer['decision'], 'confidence': answer['confidence'],
            'abstain': False, 'fallback': False}


def capture(data, model, call=one):
    rows = []
    for case in data['cases']:
        start = time.perf_counter()
        try:
            row = call(ev.request(case), model)
            ev.evaluate(case, row)
        except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            row = {**getattr(exc, 'evidence', {}), 'decision': None, 'confidence': None,
                   'abstain': True, 'fallback': False, 'error': type(exc).__name__}
        row.update(case_id=case['id'], latency_ms=(time.perf_counter() - start) * 1000)
        rows.append(row)
    return {'dataset_sha256': ev.run(data)['dataset_sha256'], 'providers': [
        {'id': 'llm', 'kind': 'live', 'revision': model, 'requested_model': model,
         'effort': 'low', 'actual_model_revision': None, 'runtime': 'codex exec',
         'provenance': 'Codex CLI tool-free; ' + datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'limitations': 'Alias revision не сообщается CLI; стоимость подписки неизвестна; wall latency включает запуск процесса, input tokens включают системный контекст CLI.',
         'responses': rows}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        result = capture(ev.load_dataset(args.dataset), args.model)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'Прогон не выполнен: {exc}\n')
    return 1 if any(r.get('error') for r in result['providers'][0]['responses']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
