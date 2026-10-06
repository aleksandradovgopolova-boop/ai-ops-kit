"""Разрешение явно объявленных skills перед вызовом исполнителя (#1251)."""
import hashlib
import json
from pathlib import Path

import yaml


class SkillUnavailable(ValueError):
    """Объявленный контекст не разрешён: стадию нельзя исполнять без него."""


def resolve_skills(stage, package_root, resolver=None):
    """Только uses_skills стадии; внешний skill требует явного runtime resolver."""
    ids = stage.get('uses_skills', [])
    if not isinstance(ids, list) or any(not isinstance(s, str) or not s for s in ids):
        raise SkillUnavailable('uses_skills должен быть списком непустых id')
    if not ids:
        return {}
    root = Path(package_root).resolve()
    try:
        manifest = yaml.safe_load((root / 'manifest/ai-ops-manifest.yaml').read_text(encoding='utf-8'))
        shipped = {s['id']: s['path'] for s in manifest['skills']['shipped']}
        bodies = {}
        for sid in dict.fromkeys(ids):
            if sid in shipped:
                path = (root / shipped[sid]).resolve()
                if not path.is_relative_to(root):
                    raise SkillUnavailable(f'{sid}: путь выходит за границу пакета')
                body = path.read_text(encoding='utf-8')
            else:
                try:
                    body = resolver(sid) if resolver else None
                except Exception as exc:  # noqa: BLE001 — внешний runtime отказал: provider не вызывается
                    raise SkillUnavailable(f'{sid}: resolver отказал ({type(exc).__name__})') from exc
            if not isinstance(body, str) or not body.strip():
                raise SkillUnavailable(f'{sid}: skill недоступен исполнителю')
            bodies[sid] = body
        return bodies
    except SkillUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise SkillUnavailable(f'не удалось разрешить skills: {exc}') from exc


def runtime_skill_resolver(child_root):
    """Skill-файлы, установленные для native runtime этой дочки; без фиктивных builtin bodies."""
    root = Path(child_root).resolve()
    def resolve(sid):
        if not isinstance(sid, str) or '/' in sid or '\\' in sid or '..' in sid:
            raise SkillUnavailable('недопустимый skill id')
        for directory in ('.claude/skills', '.agents/skills', '.codex/skills'):
            base = root / directory
            path = (base / sid / 'SKILL.md').resolve()
            if not path.is_relative_to(base.resolve()):
                raise SkillUnavailable('runtime skill path escape')
            if path.is_file():
                return path.read_text(encoding='utf-8')
        return None
    return resolve


RUNTIMES = ('claude-code', 'codex')
MAX_CONTEXT_BYTES = 32768


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field}: требуется непустая строка')
    return value


def context_response(runtime, stage, root, max_context_bytes=MAX_CONTEXT_BYTES):
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
    if size > max_context_bytes:
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
