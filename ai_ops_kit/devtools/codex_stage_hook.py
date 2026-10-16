"""Private command hook одной text-only стадии; не общий security broker."""
import json
import shlex
import sys
from pathlib import Path

from ai_ops_kit.providers.skill_context import digest


def hook_config(control, package_root):
    command = shlex.join([sys.executable, str(control / 'hook.py'),
                          str(package_root), str(control)])
    return {'hooks': {event: [{'hooks': [{'type': 'command', 'command': command,
                                         'timeout': 10, 'additionalContextLimit': 32768}]}]
                      for event in ('SessionStart', 'PreToolUse', 'PostToolUse')}}


def handle(control, payload):
    event = payload.get('hook_event_name')
    # Payload остаётся только в private temp; наружу выходит hash-only audit.
    with (control / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + '\n')
    if event == 'SessionStart':
        output = json.loads((control / 'context.json').read_text(encoding='utf-8'))
        (control / 'ack.json').write_text(json.dumps({'output_sha256': digest(output)}))
        return output
    if event == 'PreToolUse':
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': 'Эта стадия возвращает только текст; инструменты запрещены.'}}
    return {}


def main(argv=None):
    control = Path((sys.argv[1:] if argv is None else argv)[0])
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ValueError('hook payload превышает бюджет')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('hook payload должен быть object')
    sys.stdout.write(json.dumps(handle(control, payload), ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
