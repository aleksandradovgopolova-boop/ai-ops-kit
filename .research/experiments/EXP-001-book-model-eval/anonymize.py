#!/usr/bin/env python3
"""EXP-001: подготовка слепого набора для ревью.

Собирает chapters/<model>/<ch>.md, присваивает случайные id вида S-07,
складывает в blind/ и пишет mapping.json (НЕ показывать судье до конца оценки).

  python3 anonymize.py            # собрать blind/
  python3 anonymize.py --reveal   # показать mapping после оценки
"""
import argparse
import glob
import json
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reveal', action='store_true')
    ap.add_argument('--seed', type=int, default=None, help='для воспроизводимости')
    args = ap.parse_args()

    mapping_path = os.path.join(HERE, 'mapping.json')
    if args.reveal:
        with open(mapping_path) as f:
            mapping = json.load(f)
        for blind_id, src in sorted(mapping.items()):
            print(f'{blind_id}  <-  {src}')
        return 0

    files = sorted(glob.glob(os.path.join(HERE, 'chapters', '*', '*.md')))
    if not files:
        print('нет сгенерированных глав в chapters/', file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    order = list(range(len(files)))
    rng.shuffle(order)

    blind_dir = os.path.join(HERE, 'blind')
    shutil.rmtree(blind_dir, ignore_errors=True)
    os.makedirs(blind_dir)
    mapping = {}
    for i, idx in enumerate(order, 1):
        src = files[idx]
        blind_id = f'S-{i:02d}'
        mapping[blind_id] = os.path.relpath(src, HERE)
        shutil.copy(src, os.path.join(blind_dir, f'{blind_id}.md'))
    with open(mapping_path, 'w') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f'blind/: {len(mapping)} образцов; mapping.json записан — судье не показывать')
    return 0


if __name__ == '__main__':
    sys.exit(main())
