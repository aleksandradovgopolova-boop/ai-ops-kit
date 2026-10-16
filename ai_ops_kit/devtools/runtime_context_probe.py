"""Offline context/audit probe двух command-hook shapes; не native hook и не enforcement."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_ops_kit.providers.skill_context import (
    RUNTIMES, MAX_CONTEXT_BYTES, digest, text, context_response as _context_response, audit_events,
)

MAX_INPUT_BYTES = 262144


def context_response(runtime, stage, root):
    return _context_response(runtime, stage, root, max_context_bytes=MAX_CONTEXT_BYTES)



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
