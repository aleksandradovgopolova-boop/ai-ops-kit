#!/usr/bin/env python3
"""Подсчёт стоп-сигнала по листам интервью EXP-003 (v2, stdlib+pyyaml).

  python3 score.py            # по R*.yaml в этой директории
  python3 score.py --selftest

Правила (DP-107 + методологическое ревью гайда):
- valuable засчитывается только при practice_confirmed И непустом would_stop_doing И valuable=true;
- enthusiasm_only и артефакты без практики в подсчёт не входят;
- reviewer-only респонденты не засчитываются (дыра скрининга v1);
- verifiability: yes с собственным эпизодом и weak_signal считаются раздельно;
- засчитан = >=2 валидных артефакта; <3 из 5 -> СТОП build (прохождение НЕ подтверждает build).
"""
import argparse
import glob
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ARTS = ('spravka', 'presentation', 'dashboard')


def valid_arts(resp):
    tri = resp.get('triada') or {}
    out = []
    for a in ARTS:
        e = tri.get(a) or {}
        if (e.get('practice_confirmed') is True and e.get('valuable') is True
                and str(e.get('would_stop_doing') or '').strip()
                and e.get('enthusiasm_only') is not True):
            out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        ok = valid_arts({'triada': {
            'spravka': {'practice_confirmed': True, 'valuable': True,
                        'would_stop_doing': 'перестану сверять руками', 'enthusiasm_only': False},
            'presentation': {'practice_confirmed': True, 'valuable': True,
                             'would_stop_doing': '', 'enthusiasm_only': False},   # нет цитаты -> нет
            'dashboard': {'practice_confirmed': False, 'valuable': True,
                          'would_stop_doing': 'вау', 'enthusiasm_only': True}}})  # Катя-кейс -> нет
        assert ok == ['spravka'], ok
        print('SELFTEST-OK')
        return 0

    files = sorted(glob.glob(os.path.join(HERE, 'R[0-9]*.yaml')))
    counted = verif_strong = verif_weak = chat_suffice = commits = 0
    usable = 0
    for f in files:
        r = yaml.safe_load(open(f))
        rid = os.path.basename(f)
        rsp = r.get('respondent') or {}
        if rsp.get('role') == 'reviewer':
            print(f'{rid}: role=reviewer — НЕ засчитывается (дыра скрининга v1), нужен замен')
            continue
        if not rsp.get('screened'):
            print(f'{rid}: не прошёл скрининг — заменить')
            continue
        usable += 1
        arts = valid_arts(r)
        ok = len(arts) >= 2
        counted += ok
        ver = r.get('verifiability') or {}
        if ver.get('tradeoff_choice') == 'B':
            if ver.get('weak_signal') is True or not str(ver.get('error_episode') or '').strip():
                verif_weak += 1
            else:
                verif_strong += 1
        chat = ((r.get('triada') or {}).get('chat_control') or {}).get('suffice')
        chat_suffice += 1 if chat == 'yes' else 0
        commits += 1 if (r.get('procurement') or {}).get('behavioral_commitment') == 'yes' else 0
        second = (r.get('scoring') or {}).get('recoded_by_second_person')
        tag = '' if second else '  [!] ждёт пере-кодирования вторым человеком'
        print(f'{rid}: валидные={arts} засчитан={ok}{tag}')

    print(f'\nзасчитано {counted} из {usable} пригодных (порог: <3 из 5 = СТОП build)')
    if usable >= 5:
        print('ВЕРДИКТ: ' + ('СТОП-СИГНАЛ — build-путь пересмотреть (DP-108)' if counted < 3
                             else 'порог пройден — build НЕ опровергнут (и не подтверждён, n мал)'))
    else:
        print(f'пригодных интервью меньше пяти ({usable}) — вердикт не выносится')
    print(f'verifiability: Б с собственным эпизодом={verif_strong}, Б weak_signal={verif_weak} (раздельно!)')
    print(f'«чата хватило бы»: {chat_suffice} (много — удар по триаде даже при прохождении порога)')
    print(f'behavioral commitment (готовы принести задачу на тест): {commits}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
