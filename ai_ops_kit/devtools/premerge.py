"""Проверка текущего Kit merge-маршрута; локальный receipt не доказывает доверие.

Оператор проверяет происхождение review и передаёт его доверенный SHA256.
GitHub settings не меняются. Без --merge выполняются только read-only запросы.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path


class AdmissionError(ValueError):
    """Не хватает проверенного evidence: merge запрещён."""


class PendingAdmission(AdmissionError):
    """Повторное чтение может дать результат в пределах выделенного времени."""


def require(condition, message):
    if not condition:
        raise AdmissionError(message)


def gh(args, *, timeout=90):
    """Без shell, credentials в аргументы/вывод helper не копируются."""
    try:
        result = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if args[0] == 'api':
            raise PendingAdmission('GitHub read timed out') from exc
        raise AdmissionError('merge timed out; check PR state before retry') from exc
    except OSError as exc:
        raise AdmissionError('gh unavailable or timed out; outcome may be uncertain for merge') from exc
    if result.returncode and args[0] == 'api':
        if any(line.strip() == 'error connecting to api.github.com' for line in result.stderr.splitlines()):
            raise PendingAdmission('GitHub connection unavailable')
        raise AdmissionError('GitHub read failed')
    require(result.returncode == 0, 'gh failed; merge outcome must be checked before retry')
    return json.loads(result.stdout) if args[0] == 'api' else result.stdout


def pages(call, path, key):
    """Явная пагинация; усечение/изменение total_count не становится успехом."""
    rows = []
    total = None
    for page in range(1, 101):
        sep = '&' if '?' in path else '?'
        data = call(['api', f'{path}{sep}per_page=100&page={page}'])
        count = data['total_count']
        require(isinstance(count, int) and count >= 0, 'invalid total_count')
        require(total is None or total == count, 'pagination changed; retry read-only')
        total = count
        batch = data[key]
        require(isinstance(batch, list), 'invalid page')
        rows.extend(batch)
        if len(batch) < 100:
            require(len(rows) == total, 'incomplete pagination')
            return rows
    raise AdmissionError('pagination limit exceeded')


def review_receipt(path, digest):
    raw = Path(path).read_bytes()
    require(re.fullmatch(r'[0-9a-f]{64}', digest) is not None, 'invalid review digest')
    require(hashlib.sha256(raw).hexdigest() == digest, 'review digest mismatch')
    return json.loads(raw)


def validate_review(review, repo, number, head, pr):
    expected = dict(schema_version=1, repository=repo, pr=number, head=head,
                    base=pr['base']['sha'], author=pr['user']['login'],
                    scope='entire-delta', status='pass', findings=[], blockers=[])
    require(all(review.get(k) == v for k, v in expected.items()), 'review does not admit this delta')
    reviewer = review.get('reviewer')
    require(isinstance(reviewer, str) and bool(reviewer.strip()), 'missing independent reviewer')
    require(reviewer.strip().casefold() != pr['user']['login'].strip().casefold(), 'writer cannot judge')
    require(isinstance(review.get('evidence'), str) and bool(review['evidence'].strip()),
            'review provenance reference missing')


def check_success(record, label):
    status, conclusion = record['status'], record['conclusion']
    if status in ('queued', 'in_progress', 'requested', 'waiting', 'pending') and conclusion in (None, 'success'):
        raise PendingAdmission(f'CI pending: {label}')
    require(status == 'completed' and conclusion == 'success', f'CI not successful: {label}')


def admit(repo, number, head, review, policy, call):
    pr = call(['api', f'repos/{repo}/pulls/{number}'])
    require(pr['number'] == number and pr['base']['repo']['full_name'] == repo,
            'PR identity mismatch')
    require(pr['state'] == 'open' and pr['draft'] is False and pr['merged'] is False,
            'PR must be open and ready')
    require(pr['base']['ref'] == 'main' and pr['head']['sha'] == head, 'head/base mismatch')
    validate_review(review, repo, number, head, pr)
    if pr['mergeable'] is None:
        raise PendingAdmission('GitHub is calculating mergeability')
    require(pr['mergeable'] is True, 'PR cannot be merged')
    require(isinstance(policy, dict) and bool(policy), 'empty check policy')
    evidence = {}
    for workflow, names in policy.items():
        require(re.fullmatch(r'[\w-]+\.yml', workflow) is not None, 'invalid workflow')
        require(isinstance(names, list) and names and len(set(names)) == len(names), 'invalid checks')
        runs = pages(call, f'repos/{repo}/actions/workflows/{workflow}/runs?head_sha={head}&event=pull_request',
                     'workflow_runs')
        if not runs:
            raise PendingAdmission(f'waiting for workflow: {workflow}')
        run = max(runs, key=lambda r: (r['id'], r['run_attempt']))
        require(run['head_sha'] == head and run['event'] == 'pull_request'
                and run['path'] == f'.github/workflows/{workflow}'
                and any(p['number'] == number and p['head']['sha'] == head
                        and p['base']['sha'] == pr['base']['sha']
                        for p in run['pull_requests']), 'run identity mismatch')
        check_success(run, workflow)
        jobs = pages(call, f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", 'jobs')
        for name in names:
            matches = [j for j in jobs if j['name'] == name]
            require(len(matches) == 1, f'missing/ambiguous required check: {workflow}/{name}')
            check_success(matches[0], f'{workflow}/{name}')
        evidence[workflow] = dict(run_id=run['id'], attempt=run['run_attempt'], checks=names)
    # GitHub's PR snapshot can lag behind the actual target during parallel merges.
    target = call(['api', f'repos/{repo}/git/ref/heads/main'])
    require(target['ref'] == 'refs/heads/main' and target['object']['type'] == 'commit'
            and target['object']['sha'] == pr['base']['sha'], 'target branch differs from reviewed base')
    return dict(repository=repo, pr=number, head=head, base=pr['base']['sha'], checks=evidence)


def execute(repo, number, head, receipt, digest, policy, call=None, *, merge=False, wait_seconds=0):
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) is not None, 'invalid repository')
    require(type(number) is int and number > 0, 'invalid PR number')
    require(re.fullmatch(r'[0-9a-f]{40}', head) is not None, 'exact full head SHA required')
    require(type(wait_seconds) is int and 0 <= wait_seconds <= 3600, 'wait must be 0..3600 seconds')
    review = review_receipt(receipt, digest)
    deadline = time.monotonic() + wait_seconds if wait_seconds else None

    def remaining():
        if deadline is None:
            return 90
        left = deadline - time.monotonic()
        require(left > 0, 'admission wait deadline expired')
        return left

    def read(args):
        timeout = min(remaining(), 90)
        return gh(args, timeout=timeout) if call is None else call(args)

    last_pending = None
    while True:
        try:
            evidence = admit(repo, number, head, review, policy, read)
            if merge:
                fresh = admit(repo, number, head, review, policy, read)
                require(evidence == fresh, 'admission changed before merge; rerun read-only')
            remaining()
            break
        except PendingAdmission as exc:
            if deadline is None:
                raise
            if str(exc) != last_pending:
                last_pending = str(exc)
                print(last_pending, file=sys.stderr, flush=True)
            time.sleep(min(15, remaining()))

    if merge:
        write = gh if call is None else call
        write(['pr', 'merge', str(number), '--repo', repo, '--squash', '--match-head-commit', head])
    return dict(**evidence, review_sha256=digest,
                status='merge-command-succeeded' if merge else 'admitted')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--review-sha256', required=True)
    parser.add_argument('--wait-seconds', type=int, default=0,
                        help='ожидать CI и восстановление чтения GitHub до 3600 секунд')
    parser.add_argument('--merge', action='store_true')
    args = parser.parse_args(argv)
    try:
        policy = json.loads((Path(__file__).resolve().parents[2] / 'quality/premerge-checks.json').read_text())
        result = execute(args.repo, args.pr, args.head, args.review, args.review_sha256, policy,
                         merge=args.merge, wait_seconds=args.wait_seconds)
    except (AdmissionError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
