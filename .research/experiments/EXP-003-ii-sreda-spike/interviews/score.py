#!/usr/bin/env python3
"""Подсчёт стоп-сигнала по листам интервью EXP-003 (stdlib+pyyaml).

  python3 score.py            # по R*.yaml в этой директории
  python3 score.py --selftest
Правило (DP-107): засчитан = >=2 ценных артефакта; <3 засчитанных из 5 -> СТОП build-пути.
Прохождение порога build НЕ подтверждает (n=5 мал) — только не опровергает.
"""
import argparse
import glob
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def count(resp):
    tri = resp.get('triada') or {}
    arts = [k for k in ('spravka', 'presentation', 'dashboard')
            if (tri.get(k) or {}).get('valuable') is True]
    return arts, len(arts) >= 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        arts, ok = count({'triada': {'spravka': {'valuable': True},
                                     'presentation': {'valuable': True},
                                     'dashboard': {'valuable': False}}})
        assert ok and arts == ['spravka', 'presentation']
        _, ok2 = count({'triada': {'spravka': {'valuable': True}}})
        assert not ok2
        print('SELFTEST-OK')
        return 0

    files = sorted(glob.glob(os.path.join(HERE, 'R[0-9]*.yaml')))
    counted, verif_b, chat_suffice = 0, 0, 0
    for f in files:
        r = yaml.safe_load(open(f))
        if not (r.get('respondent') or {}).get('screened'):
            print(f'{os.path.basename(f)}: НЕ ПРОШЁЛ СКРИНИНГ — не засчитывается, нужен замен')
            continue
        arts, ok = count(r)
        counted += ok
        v = (r.get('verifiability') or {}).get('difference_matters')
        verif_b += 1 if v in ('yes', 'situational') else 0
        c = ((r.get('triada') or {}).get('chat_would_suffice') or {}).get('answer')
        chat_suffice += 1 if c == 'yes' else 0
        print(f'{os.path.basename(f)}: ценные={arts} засчитан={ok}')
    n = len(files)
    print(f'\nзасчитано {counted} из {n} (порог: <3 из 5 = СТОП build)')
    if n >= 5:
        print('ВЕРДИКТ: ' + ('СТОП-СИГНАЛ — build-путь пересмотреть (DP-108)' if counted < 3
                             else 'порог пройден — build НЕ опровергнут (и не подтверждён, n мал)'))
    else:
        print(f'интервью меньше пяти ({n}) — вердикт не выносится')
    print(f'verifiability важна (yes/situational): {verif_b}; «чата хватило бы»: {chat_suffice} '
          f'(много «хватило бы» — удар по триаде даже при прохождении порога)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
