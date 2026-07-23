#!/usr/bin/env python3
"""verify_quotes.py — механическая проверка quote-grounding (DP-104, механика 1).

Для каждого EV в .research/evidence/:
  - source.url пуст / internal_data -> skip (внутренние данные не фетчатся);
  - re-fetch источника (stdlib urllib, таймаут, UA);
  - раздельный учёт: fetch_ok / fetch_fail (страница умерла, JS, анти-бот — конфаундер);
  - при наличии citation.quote: нормализованный substring, затем difflib-скольжение
    (порог 0.85) -> quote_match / quote_mismatch;
  - без quote -> no_quote (поле optional в v0.2).

Порог полезности механики (DP-104): quote_mismatch при успешном fetch >= 10%.
Использование: python3 verify_quotes.py [--selftest] [--only EV-103 EV-209]
"""
import argparse
import difflib
import glob
import html
import os
import re
import sys
import urllib.request
import urllib.error

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
EV_GLOB = os.path.join(HERE, '..', 'evidence', 'EV-*.yaml')
UA = 'Mozilla/5.0 (research-module verify_quotes; +ai-ops-kit)'


def normalize(text):
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)          # грубое снятие тегов
    text = re.sub(r'[\s ]+', ' ', text)      # пробелы/nbsp
    return text.strip().lower()


def quote_in_text(quote, text, threshold=0.85):
    nq, nt = normalize(quote), normalize(text)
    if nq in nt:
        return True, 1.0
    # difflib-скольжение окном длины цитаты
    step = max(1, len(nq) // 2)
    best = 0.0
    for i in range(0, max(1, len(nt) - len(nq) + 1), step):
        r = difflib.SequenceMatcher(None, nq, nt[i:i + len(nq) * 2]).ratio()
        if r > best:
            best = r
            if best >= threshold:
                return True, best
    return best >= threshold, best


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--only', nargs='*', default=None)
    args = ap.parse_args()

    if args.selftest:
        ok, score = quote_in_text('Apache License', '<h1>Apache  License</h1> Version 2.0')
        assert ok, 'substring после нормализации'
        ok, _ = quote_in_text('совсем другой текст про яблоки', 'страница о лицензиях и версиях ПО')
        assert not ok, 'несовпадение должно отклоняться'
        ok, _ = quote_in_text('Prices exclude applicable taxes',
                              'NOTE: prices exclude applicable  taxes.')
        assert ok, 'регистронезависимость и пробелы'
        print('SELFTEST-OK')
        return 0

    counts = {'skip_internal': 0, 'fetch_fail': 0, 'no_quote': 0,
              'quote_match': 0, 'quote_mismatch': 0}
    rows = []
    for f in sorted(glob.glob(EV_GLOB)):
        ev = yaml.safe_load(open(f))
        evid = ev.get('id', os.path.basename(f))
        if args.only and evid not in args.only:
            continue
        url = (ev.get('source') or {}).get('url') or ''
        stype = (ev.get('source') or {}).get('type')
        if not url or stype == 'internal_data':
            counts['skip_internal'] += 1
            rows.append((evid, 'skip_internal', ''))
            continue
        try:
            text = fetch(url)
        except Exception as e:
            counts['fetch_fail'] += 1
            rows.append((evid, 'fetch_fail', f'{type(e).__name__}: {e}'[:80]))
            continue
        quote = (ev.get('citation') or {}).get('quote')
        if not quote:
            counts['no_quote'] += 1
            rows.append((evid, 'fetch_ok/no_quote', f'{len(text)} bytes'))
            continue
        ok, score = quote_in_text(quote, text)
        key = 'quote_match' if ok else 'quote_mismatch'
        counts[key] += 1
        rows.append((evid, key, f'score={score:.2f}'))

    for evid, status, note in rows:
        print(f'{evid:8s} {status:20s} {note}')
    checked = counts['quote_match'] + counts['quote_mismatch']
    print('\nИТОГО:', ', '.join(f'{k}={v}' for k, v in counts.items()))
    if checked:
        rate = counts['quote_mismatch'] / checked * 100
        print(f'quote_mismatch при успешном fetch: {rate:.0f}% (порог полезности DP-104: >=10%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
