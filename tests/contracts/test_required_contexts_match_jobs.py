"""Обязательные статусы защиты ветки сверяются с реальными CI-джобами.

Работа `required-contexts-match-jobs`, цель `checks-that-run`.

ЗАМЕР 20.08.2026 (docs/parallel-execution-retro.md §1 п.5): удаление джобы python39-compat
не убрало её из обязательных контекстов — ВСЕ PR зависли BLOCKED навсегда.

РЕШЕНИЕ: quality/required-contexts.yaml декларирует обязательные контексты; валидатор
(validate_required_contexts.py) сверяет декларацию с реальными джобами в CI-workflows.
Рассинхрон — красное в CI.

Три invariant-проверки:
  * declared contexts file существует и валиден;
  * все declared contexts имеют соответствующие джобы в workflows;
  * валидатор ловит рассинхрон (мутация «объявили несуществующую джобу» краснеет).
"""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.contract, pytest.mark.critical_path]


@pytest.fixture(scope="module")
def validator():
    """Загрузить валидатор как модуль."""
    spec = importlib.util.spec_from_file_location(
        "_validate_required_contexts",
        KIT / "ai_ops_kit" / "validation" / "validate_required_contexts.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDeclaredContextsFileExists:
    """Файл декларации обязательных контекстов существует и валиден."""

    def test_required_contexts_file_exists(self):
        """quality/required-contexts.yaml существует — иначе проверка не работает."""
        ctx_file = KIT / "quality" / "required-contexts.yaml"
        assert ctx_file.exists(), (
            "quality/required-contexts.yaml не найден. "
            "Файл декларирует обязательные контексты защиты ветки; без него валидатор "
            "не может сверить объявленное с реальным (required-contexts-match-jobs)."
        )

    def test_required_contexts_file_is_valid_yaml(self):
        """Файл парсится как YAML и имеет поле contexts."""
        ctx_file = KIT / "quality" / "required-contexts.yaml"
        doc = yaml.safe_load(ctx_file.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), "required-contexts.yaml не словарь"
        assert "contexts" in doc, "required-contexts.yaml не имеет поля 'contexts'"
        assert isinstance(doc["contexts"], list), "contexts не список"
        assert len(doc["contexts"]) > 0, "contexts пуст — защита ветки не работает"


class TestDeclaredContextsMatchJobs:
    """Все объявленные контексты имеют соответствующие джобы в workflows."""

    def test_no_declared_context_without_a_job(self, validator):
        """Главная проверка: если контекст объявлен, джоба ОБЯЗАНА существовать.

        Это ловит капкан: объявили контекст в защите ветки, но джобы нет (удалили,
        переименовали) — PR зависают BLOCKED навсегда.
        """
        result = validator.validate(KIT)
        assert result["declared"] is not None, "required-contexts.yaml не прочитан"
        assert result["workflow_ok"], (
            f"Объявленные контексты не имеют соответствующих джоб:\n"
            + "\n".join(f"  - {ctx}" for ctx in result["missing_jobs"])
            + "\n\nЭто повесит очередь: PR будут BLOCKED навсегда. "
            "Удалите контекст из quality/required-contexts.yaml или восстановите джобу."
        )

    def test_all_workflows_are_parsed(self, validator):
        """Валидатор видит все workflow-файлы."""
        wf_dir = KIT / ".github" / "workflows"
        expected_files = {f.stem for pattern in ("*.yml", "*.yaml") for f in wf_dir.glob(pattern)}
        jobs_by_wf = validator.extract_jobs_from_workflows(wf_dir)
        assert set(jobs_by_wf.keys()) == expected_files, (
            f"Валидатор не видит workflows: {expected_files - set(jobs_by_wf.keys())}"
        )


class TestValidatorCatchesDesync:
    """Валидатор ловит рассинхрон между декларацией и реальностью."""

    def test_fake_context_is_caught(self, validator, tmp_path):
        """Мутация: объявили несуществующую джобу — валидатор краснеет."""
        # Создаём фейковый репозиторий
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "test.yml").write_text(
            "name: test\njobs:\n  real-job:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )

        # Декларация с несуществующей джобой
        ctx_dir = tmp_path / "quality"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "required-contexts.yaml").write_text(
            "contexts:\n  - test / real-job\n  - test / fake-job\n",
            encoding="utf-8",
        )

        result = validator.validate(tmp_path)
        assert not result["ok"], "валидатор не поймал несуществующую джобу"
        assert "test / fake-job" in result["missing_jobs"]

    def test_undeclared_job_is_warning_not_error(self, validator, tmp_path):
        """Джоба есть, но не объявлена — это WARNING, не ошибка."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "test.yml").write_text(
            "name: test\njobs:\n  real-job:\n    runs-on: ubuntu-latest\n  extra-job:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )

        ctx_dir = tmp_path / "quality"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "required-contexts.yaml").write_text(
            "contexts:\n  - test / real-job\n",
            encoding="utf-8",
        )

        result = validator.validate(tmp_path)
        assert result["workflow_ok"], "undeclared job не должен красить проверку"
        assert "test / extra-job" in result["undeclared_jobs"]


@pytest.fixture
def repo(tmp_path):
    workflows = tmp_path / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    (workflows / 'test.yml').write_text('jobs:\n  real-job:\n    runs-on: ubuntu-latest\n')
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality' / 'required-contexts.yaml').write_text('contexts: [test / real-job]\n')
    return tmp_path


def snapshot(contexts, *, status=200):
    return {
        'repository': 'owner/repo', 'branch': 'main',
        'protection_response': {'status': status, 'body': {
            'required_status_checks': {'contexts': contexts}}},
    }


def test_exact_protection_match_passes(validator, repo):
    result = validator.validate(repo, github_snapshot=snapshot(['real-job']))
    assert result['workflow_ok']
    assert result['protection']['status'] == 'pass'
    assert result['ok'] and result['status'] == 'pass'


def test_offline_is_unknown_not_pass(validator, repo):
    result = validator.validate(repo)
    assert result['workflow_ok']
    assert result['status'] == 'unknown'
    assert not result['ok']
    assert 'Result: unknown' in validator.format_report(result)


def test_snapshot_mutation_proves_missing_required(validator, repo):
    evidence = snapshot(['real-job'])
    assert validator.validate(repo, github_snapshot=evidence)['ok']
    evidence['protection_response']['body']['required_status_checks']['contexts'].clear()
    assert evidence['protection_response']['body']['required_status_checks']['contexts'] == []
    result = validator.validate(repo, github_snapshot=evidence)
    assert result['status'] == 'fail' and not result['ok']
    assert result['protection']['missing_required'] == ['test / real-job']


def test_required_job_removed_from_workflow_is_detected(validator, repo):
    (repo / '.github/workflows/test.yml').write_text('jobs:\n  other-job: {}\n')
    assert 'real-job' not in (repo / '.github/workflows/test.yml').read_text()
    result = validator.validate(repo, github_snapshot=snapshot(['real-job']))
    assert not result['workflow_ok'] and not result['ok']
    assert result['missing_jobs'] == ['test / real-job']
    assert result['protection']['unresolved_required'] == ['real-job']


def test_undeclared_required_job_is_drift(validator, repo):
    with (repo / '.github/workflows/test.yml').open('a') as output:
        output.write('  extra-job: {}\n')
    result = validator.validate(repo, github_snapshot=snapshot(['real-job', 'extra-job']))
    assert result['protection']['unexpected_required'] == ['test / extra-job']
    assert result['status'] == 'fail'


def test_summary_drift_survives_admin_403_as_unknown(validator, repo):
    evidence = snapshot([], status=403)
    evidence['branch_response'] = {'status': 200, 'body': {
        'protection': {'required_status_checks': {'contexts': []}}}}
    result = validator.validate(repo, github_snapshot=evidence)
    assert result['status'] == 'unknown' and not result['ok']
    assert result['protection']['drift_detected']
    assert result['protection']['missing_required'] == ['test / real-job']


@pytest.mark.parametrize('response', [
    None, {'status': 403}, {'status': 404}, {'status': 200, 'body': {}},
    {'status': 200, 'body': {'required_status_checks': {}}},
    {'status': 200, 'body': {'required_status_checks': {'contexts': 'real-job'}}},
    {'status': 200, 'body': {'required_status_checks': {'checks': [{}]}}},
])
def test_unavailable_or_malformed_protection_is_unknown(validator, repo, response):
    evidence = snapshot([])
    evidence['protection_response'] = response
    result = validator.validate(repo, github_snapshot=evidence)
    assert result['status'] == 'unknown' and not result['ok']


def test_checks_array_contexts_are_used(validator, repo):
    evidence = snapshot([])
    evidence['protection_response']['body']['required_status_checks'] = {
        'checks': [{'context': 'real-job', 'app_id': 15368}]}
    assert validator.validate(repo, github_snapshot=evidence)['ok']


def test_disagreeing_api_reads_are_unknown(validator, repo):
    evidence = snapshot(['real-job'])
    evidence['branch_response'] = {'status': 200, 'body': {
        'protection': {'required_status_checks': {'contexts': []}}}}
    result = validator.validate(repo, github_snapshot=evidence)
    assert result['status'] == 'unknown' and not result['ok']


@pytest.mark.parametrize('content', ['', 'contexts: []', 'contexts: nope', 'contexts: [12]',
                                     'contexts: [test / real-job, test / real-job]', '[invalid'])
def test_bad_declaration_is_not_success(validator, repo, content):
    (repo / 'quality/required-contexts.yaml').write_text(content)
    result = validator.validate(repo, github_snapshot=snapshot(['real-job']))
    assert result['status'] == 'fail' and not result['workflow_ok'] and not result['ok']


def test_missing_declaration_is_not_success(validator, repo):
    (repo / 'quality/required-contexts.yaml').unlink()
    assert not validator.validate(repo)['ok']


def test_matrix_full_name_resolves_legacy_group_without_losing_script(validator, repo):
    (repo / '.github/workflows/test.yml').write_text('''jobs:
  quality:
    strategy:
      matrix:
        include:
          - group: contracts
            script: .github/ci-groups/contracts.sh
''')
    (repo / 'quality/required-contexts.yaml').write_text('contexts: [test / quality (contracts)]')
    context = 'quality (contracts, .github/ci-groups/contracts.sh)'
    result = validator.validate(repo, github_snapshot=snapshot([context]))
    assert result['actual'] == [f'test / {context}']
    assert result['ok']
    stale = validator.validate(repo, github_snapshot=snapshot(['quality (contracts)']))
    # A legacy declaration is an alias; an API context must be an exact emitted name.
    assert not stale['ok']


def test_explicit_job_name_and_multiaxis_matrix(validator, repo):
    (repo / '.github/workflows/test.yml').unlink()
    (repo / '.github/workflows/renamed.yaml').write_text('''jobs:
  check:
    name: check ${{ matrix.os }} / ${{ matrix.python }}
    strategy:
      matrix:
        os: [macos, ubuntu]
        python: ['3.12', '3.13']
        exclude:
          - os: macos
            python: '3.13'
''')
    assert validator.extract_jobs_from_workflows(repo / '.github/workflows') == {
        'renamed': ['check macos / 3.12', 'check ubuntu / 3.12', 'check ubuntu / 3.13']}


def test_ambiguous_bare_protection_context_fails(validator, repo):
    (repo / '.github/workflows/other.yml').write_text('jobs:\n  real-job: {}\n')
    result = validator.validate(repo, github_snapshot=snapshot(['real-job']))
    assert result['protection']['unresolved_required'] == ['real-job']
    assert not result['ok']


def test_unresolved_workflow_is_not_silently_skipped(validator, repo):
    (repo / '.github/workflows/test.yml').write_text('jobs:\n  real-job:\n    name: ${{ needs.x.outputs.name }}\n')
    result = validator.validate(repo, github_snapshot=snapshot(['real-job']))
    assert result['workflow_errors'] and not result['ok']


def test_github_reader_is_bounded_get_only(validator, monkeypatch):
    import subprocess
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, '{"required_status_checks": null}', '')

    monkeypatch.setattr(validator.subprocess, 'run', run)
    evidence = validator.read_github_snapshot('owner/repo', 'release/test')
    assert len(commands) == 2
    assert [c[0] for c in commands] == [
        ['gh', 'api', '--method', 'GET', 'repos/owner/repo/branches/release%2Ftest'],
        ['gh', 'api', '--method', 'GET', 'repos/owner/repo/branches/release%2Ftest/protection']]
    assert all(c[1]['timeout'] == 30 for c in commands)
    assert evidence['protection_response']['status'] == 200


@pytest.mark.parametrize('failure', ['403', 'timeout', 'missing-gh', 'invalid-json'])
def test_github_reader_failure_is_unknown(validator, monkeypatch, repo, failure):
    import subprocess

    def run(command, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 30)
        if failure == 'missing-gh':
            raise FileNotFoundError('gh')
        if failure == 'invalid-json':
            return subprocess.CompletedProcess(command, 0, 'not json', '')
        return subprocess.CompletedProcess(command, 1, '', 'gh: denied (HTTP 403)')

    monkeypatch.setattr(validator.subprocess, 'run', run)
    result = validator.validate(repo, github_snapshot=validator.read_github_snapshot('owner/repo'))
    assert result['status'] == 'unknown' and not result['ok']


@pytest.mark.parametrize(('evidence', 'exit_code'), [(None, 2), (['real-job'], 0), ([], 1)])
def test_cli_native_saved_evidence_exit_codes(validator, repo, tmp_path, evidence, exit_code):
    import json
    import subprocess
    command = [sys.executable, str(Path(validator.__file__)), '--root', str(repo), '--json']
    if evidence is not None:
        path = tmp_path / 'snapshot.json'
        path.write_text(json.dumps(snapshot(evidence)))
        command.extend(['--github-snapshot', str(path)])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert completed.returncode == exit_code, completed.stderr
    result = json.loads(completed.stdout)
    assert result['ok'] is (exit_code == 0)


def test_cli_missing_snapshot_is_unknown(validator, repo, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['validator', '--root', str(repo), '--github-snapshot',
                                     str(repo / 'absent.json'), '--json'])
    assert validator.main() == 2
    import json
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'unknown' and not result['ok']


def test_copied_validator_runs_from_another_directory(validator, repo):
    import json
    import shutil
    import subprocess
    copied = repo / 'validator.py'
    shutil.copyfile(validator.__file__, copied)
    result = subprocess.run([sys.executable, str(copied), '--json'], cwd=repo,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stderr
    body = json.loads(result.stdout)
    assert body['workflow_ok'] and body['status'] == 'unknown' and not body['ok']


def test_matrix_include_can_restore_an_excluded_combination(validator):
    assert validator._matrix_combinations({
        'os': ['macos', 'ubuntu'], 'exclude': [{'os': 'macos'}],
        'include': [{'os': 'macos', 'extra': 'value'}],
    }) == [{'os': 'ubuntu'}, {'os': 'macos', 'extra': 'value'}]


def test_ambiguous_legacy_matrix_declaration_fails(validator, repo):
    (repo / '.github/workflows/test.yml').write_text('''jobs:
  quality:
    strategy:
      matrix:
        include:
          - {group: contracts, script: one.sh}
          - {group: contracts, script: two.sh}
''')
    (repo / 'quality/required-contexts.yaml').write_text('contexts: [test / quality (contracts)]')
    result = validator.validate(repo, github_snapshot=snapshot(['quality (contracts, one.sh)']))
    assert result['ambiguous_jobs'] == ['test / quality (contracts)']
    assert not result['workflow_ok'] and not result['ok']


def test_cli_wrong_branch_snapshot_is_unknown(validator, repo, monkeypatch, capsys):
    import json
    path = repo / 'snapshot.json'
    evidence = snapshot(['real-job'])
    evidence['branch'] = 'other'
    path.write_text(json.dumps(evidence))
    monkeypatch.setattr(sys, 'argv', ['validator', '--root', str(repo), '--github-snapshot',
                                     str(path), '--json'])
    assert validator.main() == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'unknown'


def test_internal_qualified_api_name_is_not_an_emitted_context(validator, repo):
    evidence = snapshot(['test / real-job'])
    assert evidence['protection_response']['body']['required_status_checks']['contexts'] == ['test / real-job']
    assert validator.extract_jobs_from_workflows(repo / '.github/workflows') == {'test': ['real-job']}
    result = validator.validate(repo, github_snapshot=evidence)
    assert result['status'] == 'fail' and not result['ok']
    assert result['protection']['unresolved_required'] == ['test / real-job']
    assert result['protection']['missing_required'] == ['test / real-job']


def test_qualified_api_aliases_cannot_pass_current_repository(validator):
    declared = validator.load_declared_contexts(KIT)
    assert declared and all(' / ' in context for context in declared)
    evidence = snapshot(list(declared))
    result = validator.validate(KIT, github_snapshot=evidence)
    assert result['workflow_ok']
    assert not result['ok'] and result['status'] == 'fail'
    assert result['protection']['unresolved_required'] == sorted(declared)


def test_literal_separator_in_emitted_job_name_is_preserved(validator, repo):
    (repo / '.github/workflows/test.yml').write_text('jobs:\n  real-job:\n    name: literal / context\n')
    (repo / 'quality/required-contexts.yaml').write_text('contexts: [test / literal / context]\n')
    result = validator.validate(repo, github_snapshot=snapshot(['literal / context']))
    assert result['actual'] == ['test / literal / context']
    assert result['ok']
    wrong = validator.validate(repo, github_snapshot=snapshot(['test / literal / context']))
    assert wrong['status'] == 'fail' and not wrong['ok']
