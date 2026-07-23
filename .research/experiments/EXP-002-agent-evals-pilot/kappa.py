#!/usr/bin/env python3
"""EXP-002: метрики качества судьи по golden-set с seeded defects (stdlib).

Вход: golden.yaml — [{id, truth: defect|clean, judge: defect|clean}].
Выход: recall, precision (по классу defect), raw agreement, Cohen's kappa.

  python3 kappa.py --selftest
  python3 kappa.py golden.yaml
"""
import argparse
import sys

import yaml


def metrics(rows):
    tp = sum(1 for r in rows if r['truth'] == 'defect' and r['judge'] == 'defect')
    fp = sum(1 for r in rows if r['truth'] == 'clean' and r['judge'] == 'defect')
    fn = sum(1 for r in rows if r['truth'] == 'defect' and r['judge'] == 'clean')
    tn = sum(1 for r in rows if r['truth'] == 'clean' and r['judge'] == 'clean')
    n = tp + fp + fn + tn
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    po = (tp + tn) / n if n else 0.0
    p_yes = ((tp + fp) / n) * ((tp + fn) / n) if n else 0.0
    p_no = ((fn + tn) / n) * ((fp + tn) / n) if n else 0.0
    pe = p_yes + p_no
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return {'n': n, 'recall': recall, 'precision': precision,
            'agreement': po, 'kappa': kappa}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('golden', nargs='?')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        perfect = [{'truth': t, 'judge': t} for t in ['defect'] * 5 + ['clean'] * 5]
        m = metrics(perfect)
        assert m['kappa'] == 1.0 and m['recall'] == 1.0
        # судья говорит defect всегда: agreement 0.5, kappa 0 (не лучше случайности)
        always = [{'truth': t, 'judge': 'defect'} for t in ['defect'] * 5 + ['clean'] * 5]
        m = metrics(always)
        assert m['agreement'] == 0.5 and abs(m['kappa']) < 1e-9, m
        print('SELFTEST-OK')
        return 0

    rows = yaml.safe_load(open(args.golden))
    m = metrics(rows)
    print(f"n={m['n']}  recall={m['recall']:.2f}  precision={m['precision']:.2f}  "
          f"raw_agreement={m['agreement']:.2f}  cohens_kappa={m['kappa']:.2f}")
    print("памятка: сырой agreement завышает качество (EV-332) — порог ставить по kappa")
    return 0


if __name__ == '__main__':
    sys.exit(main())
