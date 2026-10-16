"""Opt-in внутренний запуск одной PRODUCT.specification; не завершение workflow."""
import argparse
import json
import sys
import subprocess
from pathlib import Path

from ai_ops_kit.devtools.codex_stage import run_specification


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--codex-bin', default='codex')
    parser.add_argument('--auth-file', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.input.read_text(encoding='utf-8'))
        report = run_specification(value['task'], value['published'], args.output_dir,
                                   model=args.model, binary=args.codex_bin,
                                   auth_file=args.auth_file, timeout=args.timeout)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(f'Не исполнено: {type(exc).__name__}. Результат стадии не подтверждён.', file=sys.stderr)
        return 2
    except (TimeoutError, subprocess.TimeoutExpired):
        print('Не исполнено: native timeout.', file=sys.stderr)
        return 2
    print(json.dumps({'stage_status': report['stage_status'],
                      'workflow_status': report['workflow_status']}, ensure_ascii=False))
    return 1  # исполнялась одна стадия; весь workflow ещё не готов


if __name__ == '__main__':
    sys.exit(main())
