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
        self.main_ref = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': BASE}}
        self.second_head = None
        self.reads = 0

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == 'pr':
            return ''
        path = args[1]
        if path == f'repos/{REPO}/git/ref/heads/main':
            return self.main_ref
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
    responses[f'repos/{REPO}/git/ref/heads/main'] = forge.main_ref
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
    assert len(recorded) == 8 and all(c[0] == 'api' for c in recorded)


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


def test_stale_pr_base_rejected_despite_green_ci_and_matching_review(receipt):
    forge = Forge()
    forge.main_ref['object']['sha'] = 'c' * 40
    with pytest.raises(premerge.AdmissionError, match='target branch'):
        invoke(forge, receipt)
    assert forge.calls[-1] == ['api', f'repos/{REPO}/git/ref/heads/main']


def test_target_advances_during_final_admission_preserves_main(receipt):
    forge = Forge()
    def call(args):
        value = forge(args)
        if forge.reads == 2 and '/jobs?' in args[1]:
            forge.main_ref['object']['sha'] = 'c' * 40
        return value

    with pytest.raises(premerge.AdmissionError, match='target branch'):
        premerge.execute(REPO, 7, SHA, receipt, hashlib.sha256(receipt.read_bytes()).hexdigest(),
                         POLICY, call, merge=True)
    assert forge.reads == 2
    assert forge.main_ref['object']['sha'] != BASE
    assert not any(args[0] == 'pr' for args in forge.calls)


@pytest.fixture
def wait_clock(monkeypatch):
    elapsed = []
    monkeypatch.setattr(premerge.time, 'monotonic', lambda: sum(elapsed))
    monkeypatch.setattr(premerge.time, 'sleep', elapsed.append)
    return elapsed


@pytest.mark.parametrize('pending', ['workflow', 'job', 'connection', 'mergeability', 'no_run'])
def test_wait_discards_partial_second_admission(receipt, wait_clock, pending):
    forge = Forge()

    def call(args):
        value = forge(args)
        if forge.reads != 2:
            return value
        if pending == 'connection' and '/jobs?' in args[1]:
            raise premerge.PendingAdmission('GitHub connection unavailable')
        if pending == 'mergeability' and '/pulls/' in args[1]:
            return dict(value, mergeable=None)
        if pending == 'no_run' and 'workflow_runs' in value:
            return {'total_count': 0, 'workflow_runs': []}
        if pending == 'workflow' and 'workflow_runs' in value:
            value['workflow_runs'][0].update(status='in_progress', conclusion=None)
        if pending == 'job' and 'jobs' in value:
            return dict(value, jobs=[dict(j, status='in_progress', conclusion='success') for j in value['jobs']])
        return value

    assert invoke(call, receipt, merge=True, wait_seconds=60)['status'] == 'merge-command-succeeded'
    assert wait_clock == [15] and forge.reads == 4
    assert [c for c in forge.calls if c[0] == 'pr'] == [forge.calls[-1]]


def test_deadline_caps_read_timeout_and_sleep(receipt, monkeypatch, wait_clock):
    timeouts = []

    def stalled(args, *, timeout, **kwargs):
        timeouts.append(timeout)
        wait_clock.append(3)
        raise premerge.subprocess.TimeoutExpired(args, 3)

    monkeypatch.setattr(premerge.subprocess, 'run', stalled)
    with pytest.raises(premerge.AdmissionError, match='deadline expired'):
        invoke(None, receipt, merge=True, wait_seconds=7)
    assert timeouts == [7] and wait_clock == [3, 4]


@pytest.mark.parametrize('reason', ['failure', 'base', 'access'])
def test_wait_stops_on_terminal_result_without_writing(receipt, wait_clock, reason):
    forge = Forge()

    def call(args):
        value = forge(args)
        if '/pulls/' in args[1]:
            if forge.reads == 1:
                raise premerge.PendingAdmission('temporary read timeout')
            if reason == 'base':
                value['base']['sha'] = 'c' * 40
            if reason == 'access':
                raise premerge.AdmissionError('GitHub read failed')
        if reason == 'failure' and 'workflow_runs' in value:
            value['workflow_runs'][0]['conclusion'] = 'failure'
        return value

    with pytest.raises(premerge.AdmissionError):
        invoke(call, receipt, merge=True, wait_seconds=60)
    assert forge.reads == 2 and wait_clock == [15] and all(c[0] == 'api' for c in forge.calls)


@pytest.mark.parametrize('error', [premerge.PendingAdmission('connection unavailable'), KeyboardInterrupt()])
def test_wait_does_not_repeat_uncertain_merge(receipt, wait_clock, error):
    forge = Forge()

    def call(args):
        value = forge(args)
        if args[0] == 'pr':
            raise error
        return value

    with pytest.raises(type(error)):
        invoke(call, receipt, merge=True, wait_seconds=60)
    assert forge.reads == 2 and not wait_clock
    assert len([c for c in forge.calls if c[0] == 'pr']) == 1


@pytest.mark.parametrize('operation,stderr,retryable', [
    ('api', 'error connecting to api.github.com\ncheck your internet connection', True),
    ('api', 'gh: HTTP 403: Forbidden', False),
    ('pr', 'error connecting to api.github.com', False),
])
def test_gh_classifies_only_transient_reads(monkeypatch, operation, stderr, retryable):
    result = premerge.subprocess.CompletedProcess([], 1, '', stderr)
    monkeypatch.setattr(premerge.subprocess, 'run', lambda *args, **kwargs: result)
    with pytest.raises(premerge.AdmissionError) as exc:
        premerge.gh([operation])
    assert isinstance(exc.value, premerge.PendingAdmission) == retryable


@pytest.mark.parametrize('seconds', [-1, 3601, True])
def test_invalid_wait_has_no_effect(receipt, seconds):
    forge = Forge()
    with pytest.raises(premerge.AdmissionError, match='wait must'):
        invoke(forge, receipt, merge=True, wait_seconds=seconds)
    assert not forge.calls


@pytest.mark.parametrize('terminal', ['next_workflow', 'same_workflow_job', 'target'])
def test_pending_cannot_mask_observable_refusal(receipt, wait_clock, terminal):
    forge = Forge()
    forge.pr['mergeable'] = None

    def call(args):
        value = forge(args)
        if 'workflow_runs' in value:
            run = value['workflow_runs'][0]
            run.update(status='in_progress', conclusion=None)
            if terminal == 'next_workflow' and forge.workflow == 'quality.yml':
                run.update(status='completed', conclusion='failure')
        if 'jobs' in value:
            if terminal == 'same_workflow_job' and forge.workflow == 'quality.yml':
                value['jobs'][0].update(status='in_progress', conclusion=None)
                value['jobs'][1]['conclusion'] = 'failure'
            else:
                return {'total_count': 0, 'jobs': []}
        if terminal == 'target' and '/git/ref/' in args[1]:
            value['object']['sha'] = 'c' * 40
        return value

    with pytest.raises(premerge.AdmissionError, match='target branch|CI not successful'):
        invoke(call, receipt, merge=True, wait_seconds=60)
    assert not wait_clock and forge.reads == 1 and all(c[0] == 'api' for c in forge.calls)
