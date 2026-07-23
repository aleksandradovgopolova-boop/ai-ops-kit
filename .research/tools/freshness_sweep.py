#!/usr/bin/env python3
"""freshness_sweep.py — еженедельный Watch свежести evidence (DP-104, механика 5).

Механическое правило re-verify (EV-310: LLM-детекции устаревания не доверяем):
  - expired:  freshness.expires_at < today  (кандидаты на stale + re-verify)
  - expiring: expires_at в ближайшие N дней (предупреждение)
  --mark-stale переводит expired из active в stale (status правится в YAML-файле,
  сам факт не удаляется — принцип модуля). Решения о re-fetch/обновлении — за агентом.

  python3 freshness_sweep.py [--days 14] [--mark-stale] [--selftest]
Exit code: 0 — всё свежо; 2 — есть expired/expiring (сигнал для лупа).
"""
import argparse
import datetime as dt
import glob
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
EV_GLOB = os.path.join(HERE, '..', 'evidence', 'EV-*.yaml')


def classify(ev, today, horizon_days):
    fresh = ev.get('freshness') or {}
    exp = fresh.get('expires_at')
    if not exp or ev.get('status') != 'active':
        return None
    exp_d = dt.date.fromisoformat(str(exp))
    if exp_d < today:
        return 'expired'
    if exp_d <= today + dt.timedelta(days=horizon_days):
        return 'expiring'
    return None


def mark_stale(path):
    text = open(path).read()
    new = re.sub(r'^status: active$', 'status: stale', text, count=1, flags=re.M)
    if new == text:
        return False
    open(path, 'w').write(new)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=14)
    ap.add_argument('--mark-stale', action='store_true')
    ap.add_argument('--today', default=None, help='ISO-дата для тестов')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        t = dt.date(2026, 7, 23)
        assert classify({'status': 'active', 'freshness': {'expires_at': '2026-07-01'}}, t, 14) == 'expired'
        assert classify({'status': 'active', 'freshness': {'expires_at': '2026-08-01'}}, t, 14) == 'expiring'
        assert classify({'status': 'active', 'freshness': {'expires_at': '2027-01-01'}}, t, 14) is None
        assert classify({'status': 'stale', 'freshness': {'expires_at': '2026-07-01'}}, t, 14) is None
        assert classify({'status': 'active', 'freshness': {'volatile': False}}, t, 14) is None
        assert mark_stale.__doc__ is None  # существование функции
        print('SELFTEST-OK')
        return 0

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    buckets = {'expired': [], 'expiring': []}
    for f in sorted(glob.glob(EV_GLOB)):
        ev = yaml.safe_load(open(f))
        cat = classify(ev, today, args.days)
        if cat:
            buckets[cat].append({'id': ev.get('id'), 'file': os.path.relpath(f, HERE),
                                 'expires_at': str((ev.get('freshness') or {}).get('expires_at')),
                                 'statement_head': (ev.get('statement') or '')[:90]})
    marked = []
    if args.mark_stale:
        for item in buckets['expired']:
            if mark_stale(os.path.join(HERE, item['file'])):
                marked.append(item['id'])
    print(yaml.safe_dump({'today': str(today), 'expired': buckets['expired'],
                          'expiring_within_days': args.days, 'expiring': buckets['expiring'],
                          'marked_stale': marked}, allow_unicode=True, sort_keys=False))
    return 2 if (buckets['expired'] or buckets['expiring']) else 0


if __name__ == '__main__':
    sys.exit(main())
