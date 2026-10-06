"""Бесплатный живой эксперимент Jev через classifier.dev; без production-проводки."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ai_ops_kit.devtools import decision_eval as ev

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
FREE_ENDPOINT = 'https://classifier.dev/v1/systemone'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def payload(req, model):
    descriptions = {'0': 'L0 QUICK: малое локальное изменение',
                    '1': 'L1 ENGINEERING: инженерное изменение или исследование',
                    '2': 'L2 PRODUCT: изменение продукта и измеримого поведения',
                    '3': 'L3 CRITICAL: высокий риск, необратимость, инциденты или граница секретов',
                    'cheap-api/low': 'Дешёвый qualified writer, low reasoning effort: простая задача',
                    'strong-executor/high': 'Сильный executor, high reasoning effort: сложная или критическая задача'}
    descriptions.update({'fast/low': 'Минимальный быстрый исполнитель: простая механическая задача, low effort',
                         'balanced/medium': 'Обычная локальная инженерная задача, medium effort',
                         'deep/high': 'Сложная логика, архитектура или миграция, high effort',
                         'strongest/high': 'Критичная безопасность: сильнейший допущенный исполнитель, high effort и обязательный независимый review',
                         'human-required': 'Требуется решение или разрешение человека; не выполнять автоматически'})
    return {'model': model, 'state': req,
            'questions': {'route': {'type': 'choice',
                           'instructions': 'Выберите подходящее ограниченное решение для point с учётом task и signals. Обязательные сигналы риска нельзя понижать.',
                           'criteria': {x: descriptions.get(x, x) for x in req['options']}}}}


def capture(data, key, model, timeout=30, post=None, input_price=None, service='typesafe'):
    if service not in ('typesafe', 'classifier-free'):
        raise ValueError('Неизвестный service')
    endpoint = FREE_ENDPOINT if service == 'classifier-free' else ENDPOINT
    if service == 'classifier-free':
        key = 'unused'  # Никогда не пересылать TypeSafe credentials стороннему прокси.
    if not key:
        raise ValueError('Не настроен TYPESAFE_API_KEY; ключ в файлы и отчёт не записывается')
    if input_price is not None:
        ev.number(input_price, 'input_price')
    ev.number(timeout, 'timeout')
    if timeout == 0 or not model:
        raise ValueError('Нужны model и положительный timeout')
    opener = urllib.request.build_opener(NoRedirect())
    if post is None:
        def post(body):
            req = urllib.request.Request(endpoint, data=body,
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with opener.open(req, timeout=timeout) as response:
                return json.load(response)
    rows, models = [], set()
    for case in data['cases']:
        body = json.dumps(payload(ev.request(case), model), ensure_ascii=False, allow_nan=False).encode()
        start = time.perf_counter()
        row = {'case_id': case['id'], 'context_bytes': len(body), 'fallback': False}
        try:
            raw = post(body)
            answer = raw['answers']['route']
            if answer['type'] != 'choice' or not isinstance(raw['model'], str) or not raw['model']:
                raise ValueError('invalid schema')
            usage = raw['usage']
            for field in ('input_tokens', 'output_tokens'):
                if isinstance(usage[field], bool) or not isinstance(usage[field], int):
                    raise ValueError('invalid token count')
                ev.number(usage[field], field)
            row.update(input_tokens=usage['input_tokens'], output_tokens=usage['output_tokens'],
                       response_model=raw['model'], raw_response=raw,
                       estimated_cost_usd=usage['input_tokens'] * input_price / 1_000_000 if input_price is not None else None)
            models.add(raw['model'])
            ev.number(answer['confidence'], 'confidence', 1)
            row.update(decision=answer['choice'], confidence=answer['confidence'], abstain=False)
            ev.evaluate(case, row)
            if service == 'classifier-free':
                row['actual_cost_usd'] = 0
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            # Не печатаем серверное тело, исключение или headers: там могут быть данные авторизации.
            row.pop('raw_response', None)
            row.update(decision=None, confidence=None, abstain=True, error=type(exc).__name__)
        row['latency_ms'] = (time.perf_counter() - start) * 1000
        rows.append(row)
    return {'dataset_sha256': ev.run(data)['dataset_sha256'], 'providers': [
        {'id': 'jev', 'kind': 'live', 'revision': ','.join(sorted(models)) or model,
         'requested_model': model, 'endpoint': endpoint, 'service': service,
         'provenance': service + ' API; ' + datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'input_price_usd_per_million': input_price, 'responses': rows}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', required=True, help='Имя из GET /v1/models; для воспроизводимости закрепите revision')
    parser.add_argument('--service', choices=['classifier-free'], default='classifier-free')
    parser.add_argument('--key-env', default='TYPESAFE_API_KEY')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--input-price-usd-per-million', type=float)
    args = parser.parse_args(argv)
    try:
        data = ev.load_dataset(args.dataset)
        result = capture(data, os.environ.get(args.key_env), args.model, args.timeout,
                         input_price=args.input_price_usd_per_million, service=args.service)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'Прогон не выполнен: {exc}\n')
    return 1 if any(r.get('error') for r in result['providers'][0]['responses']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
