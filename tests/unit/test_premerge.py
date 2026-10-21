"""Допуск к merge: fixture transport никогда не вызывает настоящий gh."""
import copy
import hashlib
import json

import pytest

from ai_ops_kit.devtools import premerge

SHA = 'a' * 40
BASE = 'b' * 40
REPO = 'owner/kit'
POLICY = {'docs.yml': ['build'], 'quality.yml': ['lint', 'quality (fast)']}


class Forge:
    def __init__(self):
        self.calls = []
        self.pr = dict(state='open', draft=False, merged=False, mergeable=True,
                       number=7, user={'login': 'writer'},
                       head={'sha': SHA, 'repo': {'full_name': REPO}},
                       base={'sha': BASE, 'ref': 'main', 'repo': {'full_name': REPO}})
        self.run = dict(id=20, run_attempt=2, head_sha=SHA, event='pull_request',
                        status='completed', conclusion='success', pull_requests=[{'number': 7, 'head': {'sha': SHA}, 'base': {'sha': BASE}}])
        self.jobs = {w: [dict(name=n, status='completed', conclusion='success')
                         for n in names] for w, names in POLICY.items()}
        self.second_head = None
        self.reads = 0

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == 'pr':
            return ''
        path = args[1]
        if '/pulls/' in path:
            self.reads += 1
            value = copy.deepcopy(self.pr)
            if self.reads > 1 and self.second_head:
                value['head']['sha'] = self.second_head
            return value
        if '/workflows/' in path:
            self.workflow = path.split('/workflows/')[1].split('/')[0]
            return {'total_count': 1, 'workflow_runs': [dict(self.run, path='.github/workflows/' + self.workflow)]}
        return {'total_count': len(self.jobs[self.workflow]), 'jobs': self.jobs[self.workflow]}


@pytest.fixture
def receipt(tmp_path):
    data = dict(schema_version=1, repository=REPO, pr=7, head=SHA, base=BASE,
                author='writer', reviewer='independent-session', scope='entire-delta',
                status='pass', findings=[], blockers=[], evidence='review session receipt')
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(data))
    return path


def invoke(forge, receipt, **kwargs):
    return premerge.execute(REPO, 7, SHA, receipt,
                            hashlib.sha256(receipt.read_bytes()).hexdigest(),
                            POLICY, forge, **kwargs)


def test_positive_read_only_never_merges(receipt):
    forge = Forge()
    assert invoke(forge, receipt)['status'] == 'admitted'
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_explicit_merge_records_only_match_head_normal_command(receipt):
    forge = Forge()
    assert invoke(forge, receipt, merge=True)['status'] == 'merge-command-succeeded'
    assert forge.calls[-1] == ['pr', 'merge', '7', '--repo', REPO, '--squash', '--match-head-commit', SHA]
    assert forge.reads == 2


@pytest.mark.parametrize('status,conclusion', [('queued', None), ('in_progress', None),
    ('completed', 'skipped'), ('completed', 'cancelled'), ('completed', 'failure'),
    ('completed', 'neutral'), ('completed', None)])
def test_non_success_job_proven_present_blocks_merge(receipt, status, conclusion):
    forge = Forge()
    forge.jobs['quality.yml'][0].update(status=status, conclusion=conclusion)
    assert forge.jobs['quality.yml'][0]['name'] == 'lint'
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_missing_and_duplicate_required_job_rejected(receipt):
    for jobs in [[], [dict(name='build', status='completed', conclusion='success')] * 2]:
        forge = Forge()
        forge.jobs['docs.yml'] = jobs
        with pytest.raises(premerge.AdmissionError):
            invoke(forge, receipt)


@pytest.mark.parametrize('field,value', [('head', 'c'*40), ('base', 'c'*40),
    ('repository', 'wrong/repo'), ('pr', 8), ('reviewer', 'writer'), ('reviewer', ' WRITER '), ('reviewer', ''),
    ('scope', 'partial'), ('status', 'fail'), ('findings', ['bug']), ('blockers', ['unknown']),
    ('author', 'other'), ('evidence', '')])
def test_unusable_review_rejected(receipt, field, value):
    data = json.loads(receipt.read_text()); data[field] = value
    receipt.write_text(json.dumps(data))
    forge = Forge()
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_wrong_receipt_digest_fails_before_network(receipt):
    forge = Forge()
    with pytest.raises(premerge.AdmissionError):
        premerge.execute(REPO, 7, SHA, receipt, '0'*64, POLICY, forge)
    assert forge.calls == []


@pytest.mark.parametrize('field,value', [('head_sha', 'c'*40), ('status', 'in_progress'),
    ('conclusion', 'skipped'), ('event', 'push'), ('pull_requests', [{'number': 8}])])
def test_wrong_or_incomplete_latest_run_rejected(receipt, field, value):
    forge = Forge(); forge.run[field] = value
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)


def test_head_changed_after_first_admission_never_merges(receipt):
    forge = Forge(); forge.second_head = 'c'*40
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)
    assert forge.reads == 2
    assert not any(c[0] == 'pr' for c in forge.calls)


@pytest.mark.parametrize('changes', [dict(draft=True), dict(state='closed'), dict(merged=True),
                                    dict(mergeable=None), dict(mergeable=False)])
def test_unready_pr_rejected(receipt, changes):
    forge = Forge(); forge.pr.update(changes)
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)


def test_old_success_cannot_hide_new_pending_run(receipt):
    forge = Forge()

    def call(args):
        value = forge(args)
        if 'workflow_runs' in value:
            old = dict(value['workflow_runs'][0], id=19)
            pending = dict(old, id=21, status='queued', conclusion=None)
            return {'total_count': 2, 'workflow_runs': [pending, old]}
        return value

    with pytest.raises(premerge.AdmissionError):
        premerge.execute(REPO, 7, SHA, receipt, hashlib.sha256(receipt.read_bytes()).hexdigest(), POLICY, call)
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_job_from_wrong_workflow_cannot_supply_missing_check(receipt):
    forge = Forge()
    forge.jobs['docs.yml'].append(dict(name='lint', status='completed', conclusion='success'))
    forge.jobs['quality.yml'] = [j for j in forge.jobs['quality.yml'] if j['name'] != 'lint']
    assert any(j['name'] == 'lint' for j in forge.jobs['docs.yml'])
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt)


def test_jobs_endpoint_selects_exact_latest_attempt(receipt):
    forge = Forge()
    invoke(forge, receipt)
    jobs_calls = [c for c in forge.calls if '/jobs?' in c[1]]
    assert jobs_calls and all('/runs/20/attempts/2/jobs?' in c[1] for c in jobs_calls)


def test_pagination_fetches_all_pages_and_rejects_truncation():
    calls = []

    def call(args):
        calls.append(args)
        return {'total_count': 101, 'jobs': list(range(100)) if args[1].endswith('&page=1') else [100]}

    assert premerge.pages(call, 'repos/o/r/jobs?filter=all', 'jobs') == list(range(101))
    assert len(calls) == 2
    with pytest.raises(premerge.AdmissionError):
        premerge.pages(lambda _: {'total_count': 2, 'jobs': [1]}, 'jobs', 'jobs')


def test_ci_changed_on_second_admission_does_not_merge(receipt):
    forge = Forge()

    def call(args):
        value = forge(args)
        if forge.reads > 1 and isinstance(value, dict) and 'workflow_runs' in value:
            value['workflow_runs'][0]['id'] = 21
        return value

    with pytest.raises(premerge.AdmissionError):
        premerge.execute(REPO, 7, SHA, receipt, hashlib.sha256(receipt.read_bytes()).hexdigest(),
                         POLICY, call, merge=True)
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_policy_matches_every_current_pr_workflow_job():
    from pathlib import Path
    import itertools
    import yaml

    root = Path(__file__).resolve().parents[2]
    policy = json.loads((root / 'quality/premerge-checks.json').read_text())
    assert sum(map(len, policy.values())) == 17
    for filename, names in policy.items():
        workflow = yaml.safe_load((root / '.github/workflows' / filename).read_text())
        expanded = []
        for name, job in workflow['jobs'].items():
            matrix = job.get('strategy', {}).get('matrix')
            if not matrix:
                expanded.append(name)
            elif 'include' in matrix:
                expanded.extend(name + ' (' + ', '.join(str(v) for v in row.values()) + ')'
                                for row in matrix['include'])
            else:
                expanded.extend(name + ' (' + ', '.join(map(str, values)) + ')'
                                for values in itertools.product(*matrix.values()))
        assert set(names) == set(expanded), filename


def test_real_subprocess_cli_uses_fake_gh_and_defaults_to_reads(receipt, tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path

    forge = Forge()
    responses = {}
    policy = json.loads((Path(premerge.__file__).resolve().parents[2] / 'quality/premerge-checks.json').read_text())
    responses[f'repos/{REPO}/pulls/7'] = forge.pr
    for i, (workflow, names) in enumerate(policy.items(), 1):
        responses[f'repos/{REPO}/actions/workflows/{workflow}/runs?head_sha={SHA}&event=pull_request&per_page=100&page=1'] = {
            'total_count': 1, 'workflow_runs': [dict(forge.run, id=i, path='.github/workflows/' + workflow)]}
        responses[f'repos/{REPO}/actions/runs/{i}/attempts/2/jobs?per_page=100&page=1'] = {
            'total_count': len(names), 'jobs': [dict(name=n, status='completed', conclusion='success') for n in names]}
    fixture = tmp_path / 'responses.json'; fixture.write_text(json.dumps(responses))
    log = tmp_path / 'calls.jsonl'
    binary = tmp_path / 'gh'
    binary.write_text('#!' + sys.executable + '\n' +
                      'import json,sys\nfrom pathlib import Path\n' +
                      f'log=Path({str(log)!r})\n' +
                      'with log.open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n' +
                      'assert sys.argv[1]=="api", "real merge prohibited in smoke"\n' +
                      f'print(json.dumps(json.loads(Path({str(fixture)!r}).read_text())[sys.argv[2]]))\n')
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    result = subprocess.run([sys.executable, '-m', 'ai_ops_kit.devtools.premerge', '--repo', REPO,
                             '--pr', '7', '--head', SHA, '--review', str(receipt),
                             '--review-sha256', hashlib.sha256(receipt.read_bytes()).hexdigest()],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'admitted'
    recorded = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(recorded) == 7 and all(c[0] == 'api' for c in recorded)


def test_ci_for_previous_base_cannot_admit_new_delta(receipt):
    forge = Forge()
    forge.run['pull_requests'][0]['base']['sha'] = 'c' * 40
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt, merge=True)
    assert not any(c[0] == 'pr' for c in forge.calls)


def test_unassociated_run_is_not_assumed_to_belong_to_pr(receipt):
    forge = Forge(); forge.run['pull_requests'] = []
    with pytest.raises(premerge.AdmissionError):
        invoke(forge, receipt)


def test_transport_failure_cannot_fall_back_to_cached_evidence(receipt):
    forge = Forge()

    def call(args):
        if '/jobs?' in args[1]:
            raise premerge.AdmissionError('API failed')
        return forge(args)

    with pytest.raises(premerge.AdmissionError):
        premerge.execute(REPO, 7, SHA, receipt, hashlib.sha256(receipt.read_bytes()).hexdigest(),
                         POLICY, call, merge=True)
    assert not any(c[0] == 'pr' for c in forge.calls)
