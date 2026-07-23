#!/usr/bin/env python3
"""ev_scaffold.py — генерация EV-файлов из EV-ready вывода разведчика (stdlib+pyyaml).

Устраняет двойной проход данных «отчёт разведчика → ручная переписка в EV»:
разведчик отдаёт records (см. формат ниже), скрипт раскладывает их в evidence/EV-*.yaml
со следующими свободными номерами серии и всем boilerplate. Writer после этого
редактирует statements/reliability, а не печатает YAML с нуля.

Формат входа (yaml-файл или stdin):
  request_id: RR-007
  series: 500                # база номеров серии (EV-501, EV-502, ...)
  captured_by: "scout-agent (…)"
  records:
    - statement: "..."
      evidence_type: documented_fact
      source: {title: "...", url: "...", type: official_documentation, is_primary: true}
      locator: "..."
      quote: "..."           # optional
      volatile: true         # -> expires_at = captured_at + 3 месяца
      reliability: medium
      reliability_rationale: "..."

  python3 ev_scaffold.py input.yaml [--dry-run] [--selftest]
"""
import argparse
import datetime as dt
import glob
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
EV_DIR = os.path.join(HERE, '..', 'evidence')


def next_free(series_base, existing_ids):
    n = series_base + 1
    while f'EV-{n}' in existing_ids:
        n += 1
    return n


def build_ev(rec, ev_id, request_id, captured_by, today):
    src = rec['source']
    volatile = bool(rec.get('volatile', True))
    expires = (today + dt.timedelta(days=92)).isoformat() if volatile else None
    ev = {
        'schema_version': 1,
        'kind': 'research.evidence',
        'id': ev_id,
        'request_id': request_id,
        'statement': rec['statement'],
        'evidence_type': rec.get('evidence_type', 'documented_fact'),
        'source': {
            'title': src['title'], 'url': src.get('url', ''),
            'type': src.get('type', 'other'),
            'published_at': src.get('published_at'),
            'is_primary': bool(src.get('is_primary', False)),
        },
        'citation': {'locator': rec.get('locator', 'уточнить при редактуре')},
        'captured_at': today.isoformat(),
        'captured_by': captured_by,
        'freshness': {'volatile': volatile, 'expires_at': expires},
        'reliability': {
            'level': rec.get('reliability', 'medium'),
            'rationale': rec.get('reliability_rationale',
                                 'Собрано агентом-разведчиком с первичной страницы; отредактировать.'),
        },
        'status': 'active',
        'superseded_by': None,
    }
    if rec.get('quote'):
        ev['citation']['quote'] = rec['quote']
    if rec.get('derived_from'):
        ev['derived_from'] = rec['derived_from']
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', nargs='?')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        today = dt.date(2026, 7, 23)
        ev = build_ev({'statement': 'x' * 20,
                       'source': {'title': 'T', 'url': 'https://e', 'type': 'official_documentation', 'is_primary': True},
                       'quote': 'verbatim quote here', 'volatile': True}, 'EV-501', 'RR-007', 'scout', today)
        assert ev['id'] == 'EV-501' and ev['citation']['quote'] == 'verbatim quote here'
        assert ev['freshness']['expires_at'] == '2026-10-23'
        ev2 = build_ev({'statement': 'y' * 20, 'evidence_type': 'inference', 'derived_from': ['EV-501'],
                        'source': {'title': 'T'}, 'volatile': False}, 'EV-502', 'RR-007', 'me', today)
        assert ev2['derived_from'] == ['EV-501'] and ev2['freshness']['expires_at'] is None
        assert next_free(500, {'EV-501', 'EV-502'}) == 503
        print('SELFTEST-OK')
        return 0

    data = yaml.safe_load(open(args.input) if args.input else sys.stdin)
    existing = set()
    for f in glob.glob(os.path.join(EV_DIR, 'EV-*.yaml')):
        m = re.match(r'(EV-\d+)', os.path.basename(f))
        if m:
            existing.add(m.group(1))
    today = dt.date.today()
    made = []
    for rec in data['records']:
        n = next_free(data['series'], existing)
        ev_id = f'EV-{n}'
        existing.add(ev_id)
        ev = build_ev(rec, ev_id, data['request_id'], data.get('captured_by', 'scout-agent'), today)
        path = os.path.join(EV_DIR, f'{ev_id}.yaml')
        if args.dry_run:
            print(f'-- would write {path}')
        else:
            with open(path, 'w') as f:
                yaml.safe_dump(ev, f, allow_unicode=True, sort_keys=False)
        made.append(ev_id)
    print(f'создано: {", ".join(made)}' + (' (dry-run)' if args.dry_run else
          '; отредактируй statements/reliability и прогони check_research.py'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
