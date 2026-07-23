#!/usr/bin/env python3
"""EXP-001: генерация глав Personal Cosmic Book тремя моделями (stdlib + pyyaml).

Использование:
  python3 generate.py --dry-run                 # план вызовов и оценка стоимости, без сети
  python3 generate.py --limit 2                 # smoke: первые 2 главы каждой моделью
  python3 generate.py                           # все 20 глав x все модели
  python3 generate.py --models kimi-k3          # только одна модель
  python3 generate.py --selftest                # проверка логики без сети

Ключи — из env (см. config.yaml: env_key). Уже сгенерированные главы пропускаются (resume).
Результат: chapters/<model>/<ch-id>.md + runs.jsonl (usage и фактическая стоимость).
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def load_cfg():
    with open(os.path.join(HERE, 'config.yaml')) as f:
        cfg = yaml.safe_load(f)
    with open(os.path.join(HERE, 'briefs.yaml')) as f:
        briefs = yaml.safe_load(f)
    return cfg, briefs


def chapter_prompt(ch):
    return (
        f"Напиши главу «{ch['title']}».\n\n"
        f"Бриф главы: {ch['brief']}\n\n"
        "Верни только текст главы (с заголовком первой строкой), без преамбул и пояснений."
    )


def call_model(model_cfg, gen_cfg, system_prompt, user_prompt):
    key = os.environ.get(model_cfg['env_key'], '')
    if not key:
        raise RuntimeError(f"нет ключа в env {model_cfg['env_key']}")
    url = model_cfg['base_url'].rstrip('/') + '/chat/completions'
    body = json.dumps({
        'model': model_cfg['model'],
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': gen_cfg['temperature'],
        'max_tokens': gen_cfg['max_tokens'],
        'stream': False,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    })
    last_err = None
    for attempt in range(gen_cfg['retries'] + 1):
        try:
            with urllib.request.urlopen(req, timeout=gen_cfg['timeout_s']) as resp:
                data = json.loads(resp.read().decode())
            text = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            return text, usage
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            detail = ''
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = e.read().decode()[:300]
                except Exception:
                    pass
            print(f"    попытка {attempt + 1} не удалась: {e} {detail}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"все попытки исчерпаны: {last_err}")


def cost_usd(usage, model_cfg):
    pin = usage.get('prompt_tokens', 0) / 1e6 * model_cfg['price_in']
    pout = usage.get('completion_tokens', 0) / 1e6 * model_cfg['price_out']
    return round(pin + pout, 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=None, help='первые N глав')
    ap.add_argument('--models', nargs='*', default=None, help='подмножество model id')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    cfg, briefs = load_cfg()
    models = [m for m in cfg['models'] if not args.models or m['id'] in args.models]
    chapters = briefs['chapters'][:args.limit] if args.limit else briefs['chapters']
    system_prompt = briefs['system_prompt']

    if args.selftest:
        assert len(cfg['models']) == 3 and len(briefs['chapters']) == 20
        assert all(m['price_out'] > 0 for m in cfg['models'])
        assert 'Мира' in system_prompt
        p = chapter_prompt(briefs['chapters'][0])
        assert 'Пролог' in p and 'Бриф' in p
        assert cost_usd({'prompt_tokens': 1_000_000, 'completion_tokens': 1_000_000},
                        {'price_in': 1.0, 'price_out': 2.0}) == 3.0
        print('SELFTEST-OK')
        return 0

    plan, todo = [], []
    for m in models:
        outdir = os.path.join(HERE, 'chapters', m['id'])
        for ch in chapters:
            path = os.path.join(outdir, f"{ch['id']}.md")
            done = os.path.exists(path)
            plan.append((m, ch, path, done))
            if not done:
                todo.append((m, ch, path))

    # оценка стоимости: ~1.2K токенов входа (system+brief) и ~2.2K выхода на главу
    est = sum(1.2e3 / 1e6 * m['price_in'] + 2.2e3 / 1e6 * m['price_out'] for m, _, _ in todo)
    print(f"план: {len(plan)} глав всего, к генерации {len(todo)} (resume пропускает готовые); "
          f"оценка стоимости ~${est:.2f}")
    if args.dry_run:
        for m, ch, path in todo:
            print(f"  {m['id']:18s} {ch['id']}  -> {os.path.relpath(path, HERE)}")
        missing = {m['env_key'] for m, _, _ in todo if not os.environ.get(m['env_key'])}
        if missing:
            print(f"нет ключей: {', '.join(sorted(missing))}")
        return 0

    runs_path = os.path.join(HERE, 'runs.jsonl')
    failures = 0
    for m, ch, path in todo:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(f"{m['id']} {ch['id']} …", flush=True)
        t0 = time.time()
        try:
            text, usage = call_model(m, cfg['generation'], system_prompt, chapter_prompt(ch))
        except RuntimeError as e:
            failures += 1
            print(f"  FAIL: {e}", file=sys.stderr)
            continue
        with open(path, 'w') as f:
            f.write(text)
        rec = {
            'model': m['id'], 'chapter': ch['id'],
            'prompt_tokens': usage.get('prompt_tokens'),
            'completion_tokens': usage.get('completion_tokens'),
            'cost_usd': cost_usd(usage, m),
            'seconds': round(time.time() - t0, 1),
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        with open(runs_path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(f"  ok: {rec['completion_tokens']} ток. выхода, ${rec['cost_usd']}, {rec['seconds']}s")
    print(f"готово; ошибок: {failures}")
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
