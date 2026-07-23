#!/usr/bin/env python3
"""EXP-002: минимальный stdlib-раннер eval-кейсов формата promptfoo-style (vars+assert).

Режим fixture: выходы агента лежат в outputs/<test-index>.md (пилот без API-ключей).
Механические assert'ы (contains/not-contains/regex) исполняются немедленно;
llm-rubric собираются в rubric_checklist.yaml для судьи-LLM, его вердикты
подаются обратно через --rubric-verdicts (yaml: [{test, rubric_index, pass}]).

  python3 runner.py --selftest
  python3 runner.py cases/code-reviewer.cases.yaml --outputs outputs/
  python3 runner.py cases/... --outputs outputs/ --rubric-verdicts verdicts.yaml
Exit code 1 при любом провале (CI-совместимо).
"""
import argparse
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def run_assert(a, output):
    t = a['type']
    if t == 'contains':
        return a['value'].lower() in output.lower()
    if t == 'not-contains':
        return a['value'].lower() not in output.lower()
    if t == 'regex':
        return re.search(a['value'], output) is not None
    if t == 'llm-rubric':
        return None  # решает судья
    raise ValueError(f'неизвестный тип assert: {t}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cases', nargs='?')
    ap.add_argument('--outputs', default=os.path.join(HERE, 'outputs'))
    ap.add_argument('--rubric-verdicts', default=None)
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        assert run_assert({'type': 'contains', 'value': 'BLOCKER'}, 'найден blocker: ...') is True
        assert run_assert({'type': 'not-contains', 'value': 'одобрено'}, 'вердикт: BLOCKED') is True
        assert run_assert({'type': 'regex', 'value': 'BLOCKER|MAJOR'}, 'MAJOR: подавление ошибок') is True
        assert run_assert({'type': 'llm-rubric', 'value': 'x'}, 'y') is None
        print('SELFTEST-OK')
        return 0

    spec = yaml.safe_load(open(args.cases))
    verdicts = {}
    if args.rubric_verdicts:
        for v in yaml.safe_load(open(args.rubric_verdicts)) or []:
            verdicts[(v['test'], v['rubric_index'])] = bool(v['pass'])

    rubric_checklist, failures, results = [], 0, []
    for ti, test in enumerate(spec['tests']):
        out_path = os.path.join(args.outputs, f'{ti}.md')
        if not os.path.exists(out_path):
            print(f'test[{ti}] SKIP: нет output-фикстуры {out_path}')
            continue
        output = open(out_path).read()
        ri = 0
        for a in test['assert']:
            res = run_assert(a, output)
            if res is None:
                key = (ti, ri)
                if key in verdicts:
                    res = verdicts[key]
                else:
                    rubric_checklist.append({'test': ti, 'rubric_index': ri,
                                             'rubric': a['value'], 'output_file': out_path})
                    ri += 1
                    continue
                ri += 1
            label = 'PASS' if res else 'FAIL'
            if not res:
                failures += 1
            results.append(f'test[{ti}] {a["type"]:12s} {label}')
    print('\n'.join(results))
    if rubric_checklist:
        cl_path = os.path.join(HERE, 'rubric_checklist.yaml')
        with open(cl_path, 'w') as f:
            yaml.safe_dump(rubric_checklist, f, allow_unicode=True)
        print(f'\nllm-rubric: {len(rubric_checklist)} проверок ждут судью -> {cl_path}')
    print(f'механических провалов: {failures}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
