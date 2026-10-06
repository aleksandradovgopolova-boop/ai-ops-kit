"""Offline context/audit probe двух command-hook shapes; не native hook и не enforcement."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ai_ops_kit.providers.skill_context import resolve_skills

RUNTIMES = ('claude-code', 'codex')
MAX_INPUT_BYTES = 262144
MAX_CONTEXT_BYTES = 32768


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field}: требуется непустая строка')
    return value


def context_response(runtime, stage, root):
    """Сериализация по документам; это не ACK runtime или подтверждение соблюдения skills."""
    if runtime not in RUNTIMES or not isinstance(stage, dict):
        raise ValueError('неизвестный runtime или stage')
    sid = text(stage.get('id'), 'stage.id')
    owner = text(stage.get('owner'), 'stage.owner')
    mode = text(stage.get('review_mode'), 'stage.review_mode')
    if mode not in ('writer', 'read-only') or (mode == 'read-only' and stage.get('writer')):
        raise ValueError('review_mode или writer противоречит роли')
    bodies = resolve_skills(stage, root)
    binding = {'stage': sid, 'owner': owner, 'review_mode': mode,
               'skills': {key: hashlib.sha256(body.encode()).hexdigest()
                          for key, body in bodies.items()}}
    context = json.dumps(binding, ensure_ascii=False, sort_keys=True) + '\n'
    if mode == 'read-only':
        context += 'Роль read-only: возвращайте заключение, не изменяйте артефакты.\n'
    context += '\n'.join(f'## Skill: {key}\n{body}' for key, body in bodies.items())
    size = len(context.encode())
    if size > MAX_CONTEXT_BYTES:
        raise ValueError('обязательный контекст превышает бюджет probe; сокращение запрещено')
    output = {'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                     'additionalContext': context}}
    receipt = {'kind': 'FACT', 'claim': 'context_serialized', 'runtime': runtime,
               'binding': binding, 'context_sha256': hashlib.sha256(context.encode()).hexdigest(),
               'context_bytes': size, 'output_sha256': digest(output),
               'runtime_delivery_verified': False}
    return output, receipt


def audit_events(runtime, events):
    """Порядок локального replay, не глобальные часы; raw payloads не сохраняются."""
    if runtime not in RUNTIMES or not isinstance(events, list) or not events:
        raise ValueError('runtime/events невалидны')
    records, gaps, pending, completed, seen = [], [], {}, set(), set()
    session = None
    started = False
    for sequence, payload in enumerate(events, 1):
        if not isinstance(payload, dict):
            gaps.append({'sequence': sequence, 'reason': 'malformed_payload'})
            continue
        event = payload.get('hook_event_name')
        native_session = payload.get('session_id')
        call = payload.get('tool_use_id')
        turn = payload.get('turn_id') if runtime == 'codex' else None
        if (not isinstance(event, str) or not isinstance(native_session, str)
                or not native_session.strip() or (turn is not None and not isinstance(turn, str))):
            gaps.append({'sequence': sequence, 'reason': 'missing_or_invalid_identity'})
            continue
        fingerprint = digest(payload)
        records.append({'sequence': sequence, 'kind': 'FACT', 'claim': 'payload_observed',
                        'event': event if event in ('SessionStart', 'PreToolUse', 'PostToolUse') else 'unknown',
                        'session_id': native_session, 'turn_id': turn,
                        'call_id': call if isinstance(call, str) else None,
                        'payload_sha256': fingerprint})
        if fingerprint in seen:
            gaps.append({'sequence': sequence, 'reason': 'duplicate_payload'})
            continue
        seen.add(fingerprint)
        if session is None:
            session = native_session
        if native_session != session:
            gaps.append({'sequence': sequence, 'reason': 'session_mismatch'})
            continue
        if event == 'SessionStart':
            sources = ('startup', 'resume', 'clear', 'compact') + (('fork',) if runtime == 'claude-code' else ())
            if payload.get('source') not in sources:
                gaps.append({'sequence': sequence, 'reason': 'unknown_session_source'})
            if started or sequence != 1:
                gaps.append({'sequence': sequence, 'reason': 'unexpected_session_start'})
            started = True
        elif event in ('PreToolUse', 'PostToolUse'):
            if (not started or not isinstance(call, str) or not call.strip()
                    or (runtime == 'codex' and (not isinstance(turn, str) or not turn.strip()))):
                gaps.append({'sequence': sequence, 'reason': 'unbound_tool_event'})
                continue
            key = (turn, call)
            if not isinstance(payload.get('tool_name'), str) or not payload['tool_name'].strip() or 'tool_input' not in payload:
                gaps.append({'sequence': sequence, 'reason': 'missing_tool_shape'})
                continue
            action = digest({'tool': payload['tool_name'], 'input': payload['tool_input']})
            if event == 'PreToolUse':
                if key in pending or key in completed:
                    gaps.append({'sequence': sequence, 'reason': 'duplicate_call'})
                else:
                    pending[key] = action
            else:
                if 'tool_response' not in payload:
                    gaps.append({'sequence': sequence, 'reason': 'missing_response'})
                elif key not in pending:
                    gaps.append({'sequence': sequence, 'reason': 'orphan_result'})
                elif pending[key] != action:
                    gaps.append({'sequence': sequence, 'reason': 'action_mismatch'})
                else:
                    pending.pop(key)
                    completed.add(key)
        else:
            gaps.append({'sequence': sequence, 'reason': 'unsupported_event'})
    for turn, call in pending:
        gaps.append({'reason': 'missing_result', 'turn_id': turn, 'call_id': call})
    if not started:
        gaps.append({'reason': 'missing_session_start'})
    return {'status': 'degraded' if gaps else 'observed', 'records': records, 'gaps': gaps,
            'paired_calls': len(completed), 'native_coverage_verified': False,
            'side_effect_verified': False}


def probe(runtime, stage, events, root):
    output, receipt = context_response(runtime, stage, root)
    audit = audit_events(runtime, events)
    return {'scope': 'offline-replay', 'runtime': runtime, 'model_turns': 0,
            'live_runtime_runs': 0, 'context_output': output, 'context_receipt': receipt,
            'audit': audit}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, choices=RUNTIMES)
    parser.add_argument('--package-root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('вход превышает бюджет probe')
        data = json.loads(raw)
        result = probe(args.runtime, data['stage'], data['events'], args.package_root)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        # Не печатаем exception text: он может содержать путь или приватный skill id.
        print(json.dumps({'scope': 'offline-replay', 'status': 'error',
                          'error_type': type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result['audit']['status'] == 'degraded' else 0


if __name__ == '__main__':
    raise SystemExit(main())
