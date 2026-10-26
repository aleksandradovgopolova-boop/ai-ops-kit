"""Охват доказательства называется, а не подразумевается (v3.34).

`./scripts/check-full.sh` означает «весь pytest на ТОМ интерпретаторе, что стоит у запускающего»,
а не «поддерживаемая матрица целиком». PR #38 написал «полный контур зелёный» — и джоба
python39-compat опровергла это в том же релизе, потому что новый тест импортировал `tomllib`
при объявленном поле 3.9.

Дефект здесь не в тексте PR, а в отсутствии словаря: пока «полный» не имеет величины, заявление
шире полученного делается без единой ошибки. `registry/release-claims.yaml` объявляет именованные охваты,
`validate_release_claims` требует, чтобы оба существовали и чтобы заявление о полноте называло,
какой из них получен.

Три обязательных теста на capability (AGENTS.md):
  * positive     — реальный реестр объявляет обязательные охваты и проходит проверку;
  * fail-closed  — заявление о полноте без имени охвата краснеет; стёртый или неполный
                   evidence_scopes краснеет, а не читается как «ограничений нет»;
  * side-effect  — скрипт РЕАЛЬНО печатает свой охват (и он именно тот, что объявлен в реестре),
                   прежде чем верить, что запускающий его увидит.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import host_resource_cli as host_resources

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "validation"))

import validate_release_claims as vrc  # noqa: E402

SCRIPT = PKG / "scripts" / "check-full.sh"


@pytest.fixture(scope="module")
def claims():
    return yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


def test_required_scopes_are_declared(claims):
    """positive: словарь существует, и в нём различаемые охваты."""
    assert not vrc.evidence_scope_errors(claims), vrc.evidence_scope_errors(claims)
    scopes = claims["evidence_scopes"]
    for name in vrc.REQUIRED_SCOPES:
        assert str(scopes[name]["does_not_cover"]).strip(), (
            f"{name} без границы — охват, который «покрывает всё», это снова «полный»")


def _pkg_with_note(tmp_path, claims, note, version=None):
    """Копия пакета, где релизная проза — та, что нужна тесту. -> корень.

    ПРОЗА ПЕРЕЕХАЛА В СВОЙ ФАЙЛ (20.08.2026, `release-claims-stays-in-the-kit`): 61 336 Б — 75%
    release-claims.yaml — ехали в каждую дочку, где их не читает ни одна строка кода. Тесты поэтому
    больше не подсовывают `patch_note` в словарь: проверка читает ФАЙЛ, и подмена словарём проверяла
    бы путь, которого больше нет. Заодно это честнее — прогоняется тот же код, что в релизе.
    """
    (tmp_path / "registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / "registry" / "release-notes.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "registry_type": "release-notes",
                        "version": version if version is not None else claims["version"],
                        "patch_note": note}, allow_unicode=True), encoding="utf-8")
    # `obtained_by` со ссылкой на файл проверяется по этому же корню — стаб нужен, иначе тест ловил бы
    # отсутствие файла вместо предмета проверки.
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "check-full.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return tmp_path


def test_full_claim_without_a_scope_is_caught(claims, tmp_path):
    """fail-closed: ровно то заявление, которое сделал PR #38, обязано краснеть."""
    pkg = _pkg_with_note(tmp_path, claims, "3.34 — полный контур зелёный, релиз готов.")
    errors = vrc.evidence_scope_errors(claims, pkg=pkg)
    assert any("не называя охват" in e for e in errors), errors


def test_scoped_claim_passes(claims, tmp_path):
    """То же заявление с названным охватом проходит: проверка бьёт по подмене, не по слову."""
    pkg = _pkg_with_note(tmp_path, claims, "3.34 — охват full-current-python зелёный целиком.")
    assert not vrc.evidence_scope_errors(claims, pkg=pkg), \
        vrc.evidence_scope_errors(claims, pkg=pkg)


def test_prose_in_the_claims_file_is_refused(claims, tmp_path):
    """Два места для одного текста разъедутся молча — поэтому старый адрес объявлен ошибкой."""
    pkg = _pkg_with_note(tmp_path, claims, "3.34 — охват full-current-python зелёный целиком.")
    errors = vrc.evidence_scope_errors(dict(claims, patch_note="что-то"), pkg=pkg)
    assert any("остался в release-claims" in e for e in errors), errors


def test_note_for_another_release_is_refused(claims, tmp_path):
    """Версия дублируется намеренно и обязана сверяться: иначе проза относится к другому выпуску."""
    pkg = _pkg_with_note(tmp_path, claims, "охват full-current-python зелёный", version="0.0.1")
    errors = vrc.evidence_scope_errors(claims, pkg=pkg)
    assert any("другому выпуску" in e for e in errors), errors


def test_missing_note_file_is_an_error_not_a_pass(claims, tmp_path):
    """«Нечего проверять» на месте заявления о выпуске — это и было бы ослаблением правила."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "check-full.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    errors = vrc.evidence_scope_errors(claims, pkg=tmp_path)
    assert any("отсутствует" in e for e in errors), errors


@pytest.mark.parametrize("broken,expect", [
    ({}, "не объявлен"),
    (None, "отсутствует"),
    ({"full-current-python": {"obtained_by": "x", "covers": "y", "does_not_cover": "z"}},
     "compatibility-matrix"),
    ({**{n: {"obtained_by": "x", "covers": "y", "does_not_cover": ""}
         for n in vrc.REQUIRED_SCOPES}}, "does_not_cover"),
    ({**{n: {"obtained_by": "./scripts/nonexistent.sh", "covers": "y", "does_not_cover": "z"}
         for n in vrc.REQUIRED_SCOPES}}, "файла нет"),
])
def test_broken_scope_declaration_is_not_green(claims, broken, expect):
    """fail-closed: стереть словарь не значит снять ограничение.

    Ровно так опустошённый registry/tracks.yaml проходил молча до #39: реестр, отсутствие
    которого никто не замечает, ничего не гарантирует.
    """
    errors = vrc.evidence_scope_errors(dict(claims, evidence_scopes=broken))
    assert any(expect in e for e in errors), (broken, errors)


@pytest.mark.slow  # поднимает подпроцесс check-full.sh (ruff по репо + сбор всего pytest), ~20 c — #465
def test_script_announces_the_scope_it_actually_gives():
    """side-effect: доказать, что охват РЕАЛЬНО печатается, прежде чем считать его объявленным.

    Реестр может сколько угодно объявлять словарь — увидит его тот, кто запускает проверку, и
    только если скрипт говорит это сам. Прогон с `--collect-only` даёт настоящий запуск скрипта
    без четырёх минут тестов.
    """
    env = {**os.environ, "PYTHON": sys.executable}
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"],
                       cwd=str(PKG), capture_output=True, text=True, timeout=300, env=env,
                       **host_resources.subprocess_kwargs(env))
    out = r.stdout + r.stderr
    assert "full-current-python" in out, out[-800:]
    assert "compatibility-matrix" in out, out[-800:]
    # СРАВНИВАЕМ С ТЕМ ИНТЕРПРЕТАТОРОМ, КОТОРЫМ СКРИПТ РЕАЛЬНО ПОЙДЁТ, а не со своим. Прежде тест
    # брал `sys.version_info`, а скрипт — `python3` из PATH; на машине владельца это разные
    # интерпретаторы, и тест краснел ВСЕГДА, ничего при этом не проверяя.
    assert f"{sys.version_info.major}.{sys.version_info.minor}" in out, (
        "охват назван, но без версии интерпретатора — то есть снова без величины")


def test_script_refuses_an_interpreter_without_pytest(tmp_path):
    """fail-closed: интерпретатор без pytest — НАЗВАННЫЙ отказ, а не `No module named pytest`.

    Замер 19.08.2026: на машине владельца `python3` это homebrew без pytest, и документированная
    точка входа «полный контур» падала трассировкой модуля. Отказ обязан говорить, что делать."""
    fake = tmp_path / "python-without-pytest"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-c" ] && [[ "$2" == *"import pytest"* ]]; then exit 1; fi\n'
        f'exec {sys.executable} "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": str(fake)}, **host_resources.subprocess_kwargs())
    assert r.returncode == 2, (r.returncode, (r.stdout + r.stderr)[-600:])
    assert "pytest в нём нет" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-600:]


@pytest.mark.slow  # поднимает подпроцесс check-full.sh (ruff по репо + сбор всего pytest), ~20 c — #465
def test_pytest_runs_on_the_interpreter_that_was_announced(tmp_path):
    """ШОВ, найденный собственной пробой: объявить охват одним интерпретатором, а гонять другим —
    это ровно «заявление шире полученного», против которого словарь охватов и заведён.

    Проверяется не текстом, а фактом вызова: `$PYTHON` подменяется обёрткой, которая записывает
    каждый свой запуск. В журнале обязан быть запуск `-m pytest`."""
    log = tmp_path / "calls.log"
    wrapper = tmp_path / "python-logging"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> {log}\n'
        f'exec {sys.executable} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=300,
                       env={**os.environ, "PYTHON": str(wrapper)}, **host_resources.subprocess_kwargs())
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    calls = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "-m pytest" in calls, (
        "объявленный интерпретатор не тот, которым идут тесты — охват назван, а получен другой:\n"
        f"{calls[-400:]}")


def test_script_scope_name_matches_the_registry(claims):
    """Словарь один. Скрипт и реестр, разошедшиеся в именах, снова разрешают путаницу."""
    text = SCRIPT.read_text(encoding="utf-8")
    for name in vrc.REQUIRED_SCOPES:
        assert name in text, f"{name} объявлен в реестре, но скрипт им не пользуется"


def _tiny_scope_script(tmp_path):
    import shlex
    import shutil
    root = tmp_path / "pkg"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts/check-full.sh")
    # Fixture содержит настоящий runner и его runtime dependency, как обычный Kit checkout.
    for relative in ("ai_ops_kit/devtools/host_resource_cli.py",):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PKG / relative, target)
    (root / "scripts/warn-path-belt.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "scripts/warn-path-belt.sh").chmod(0o755)
    (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.0.0"\nrequires-python=">=3.12"\n')
    (root / "pytest.ini").write_text('[pytest]\naddopts=-m "not release_gate"\nmarkers=\n slow: slow\n nightly: nightly\n release_gate: release\n')
    (root / "tests").mkdir()
    (root / "tests/test_fixture.py").write_text('''import os
from pathlib import Path
import pytest
def record(name):
    with Path(os.environ["SCOPE_LOG"]).open("a") as stream: stream.write(name+"\\n")
def test_fast(): record("fast")
@pytest.mark.slow
def test_slow():
    record("slow")
    assert os.environ.get("FAIL_SLOW") != "1"
@pytest.mark.slow
@pytest.mark.nightly
def test_nightly(): record("nightly")
@pytest.mark.slow
@pytest.mark.release_gate
def test_release(): record("release")
''')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ruff").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "ruff").chmod(0o755)
    wrapper = bindir / "logged-python"
    wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYTHON_CALLS"\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    wrapper.chmod(0o755)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "PYTHON": str(wrapper), "PYTEST_XDIST_AUTO_NUM_WORKERS": "1",
           "PYTHON_CALLS": str(tmp_path / "python-calls"), "SCOPE_LOG": str(tmp_path / "scope-log")}
    env.pop("PYTEST_ADDOPTS", None)
    return root, env


def _run_tiny_scope(root, env, *args):
    def execute(bound):
        return subprocess.run(["bash", str(root / "scripts/check-full.sh"), *args], cwd=root,
                              env=bound, capture_output=True, text=True, timeout=120,
                              **host_resources.subprocess_kwargs(bound))
    if host_resources.inherited_slot(environment=env) is not None:
        return execute(env)
    # Собственный fixture-slot изолирует маленький проверочный corpus от реальных host jobs.
    path = root.parent / "fixture-heavy.lock"
    with host_resources.host_slot("scope-fixture", "local", path=path) as fd:
        return execute({**env, "AI_OPS_HOST_SLOT_FD": str(fd), "AI_OPS_HOST_SLOT_PATH": str(path)})


def _scope_ids(env):
    path = Path(env["SCOPE_LOG"])
    return sorted(path.read_text().splitlines()) if path.exists() else []


@pytest.mark.parametrize("args,ids,scope", [
    ((), ["fast", "nightly", "slow"], "full-current-python"),
    (("--pr", "-n", "1", "--durations=3"), ["fast", "slow"], "pr-current-python"),
])
def test_real_script_dispatches_exact_named_scope(tmp_path, args, ids, scope):
    root, env = _tiny_scope_script(tmp_path)
    result = _run_tiny_scope(root, env, *args)
    assert _scope_ids(env) == ids, result.stdout + result.stderr
    assert result.returncode == 0 and f"ЗЕЛЁНЫЙ ОХВАТ: {scope}" in result.stdout
    assert "-m pytest" in Path(env["PYTHON_CALLS"]).read_text()


def test_pr_profile_executes_and_refuses_red_ordinary_slow_test(tmp_path):
    root, env = _tiny_scope_script(tmp_path)
    result = _run_tiny_scope(root, {**env, "FAIL_SLOW": "1"}, "--pr", "-n1")
    assert _scope_ids(env) == ["fast", "slow"], result.stdout + result.stderr
    assert result.returncode != 0 and "ЗЕЛЁНЫЙ ОХВАТ" not in result.stdout


def test_nested_scope_preserves_parent_slot_without_reacquiring(tmp_path):
    root, env = _tiny_scope_script(tmp_path)
    path = tmp_path / "parent-heavy.lock"
    with host_resources.host_slot("parent-suite", "local", path=path) as fd:
        before = path.read_bytes()
        result = _run_tiny_scope(root, {**env, "AI_OPS_HOST_SLOT_FD": str(fd),
                                       "AI_OPS_HOST_SLOT_PATH": str(path)}, "--pr", "-n1")
        assert _scope_ids(env) == ["fast", "slow"], result.stdout + result.stderr
        assert result.returncode == 0 and path.read_bytes() == before
        # Попытка взять тот же slot новым open-file-description всё ещё блокируется.
        with pytest.raises(host_resources.ResourceBlocked, match="занят"):
            with host_resources.host_slot("foreign", "self_hosted_ci", path=path):
                pytest.fail("parent slot must remain held after nested check")


@pytest.mark.parametrize("args,extra_env", [
    (("--pr", "-m", "nightly"), {}), (("--pr", "-k", "fast"), {}),
    (("--pr", "--collect-only"), {}), (("--pr", "--co"), {}),
    (("--pr", "--ignore=tests"), {}), (("--pr", "tests/test_fixture.py"), {}),
    (("--pr", "-o", "addopts=-m nightly"), {}), (("--pr", "--unknown"), {}),
    (("--pr", "-n"), {}), (("--pr",), {"PYTEST_ADDOPTS": "-k fast"}),
])
def test_pr_scope_refuses_selection_before_any_python(tmp_path, args, extra_env):
    root, env = _tiny_scope_script(tmp_path)
    result = _run_tiny_scope(root, {**env, **extra_env}, *args)
    assert not Path(env["PYTHON_CALLS"]).exists(), result.stdout + result.stderr
    assert _scope_ids(env) == [] and result.returncode == 2
    assert "ЗЕЛЁНЫЙ ОХВАТ" not in result.stdout


@pytest.mark.parametrize("args,ids,label", [
    (("-m", "nightly"), ["nightly"], "custom-current-python"),
    (("--collect-only",), [], "collection-only"),
])
def test_default_selection_override_is_named_without_full_success(tmp_path, args, ids, label):
    root, env = _tiny_scope_script(tmp_path)
    result = _run_tiny_scope(root, env, *args)
    assert _scope_ids(env) == ids, result.stdout + result.stderr
    assert result.returncode == 0 and label in result.stdout
    assert "ЗЕЛЁНЫЙ ОХВАТ: full-current-python" not in result.stdout


def test_pr_scope_is_declared_and_cannot_replace_exact_release_gate(claims):
    assert "pr-current-python" in vrc.REQUIRED_SCOPES
    scoped = claims["evidence_scopes"]["pr-current-python"]
    assert "nightly" in scoped["does_not_cover"] and "release" in scoped["does_not_cover"]
    release = yaml.safe_load((PKG / ".github/workflows/release.yml").read_text())
    job = release["jobs"]["release"]
    steps = job["steps"]
    mutation = next(i for i, step in enumerate(steps) if "test_mutation_probe.py" in step.get("run", ""))
    tag = next(i for i, step in enumerate(steps) if "gh release create" in step.get("run", ""))
    assert mutation < tag and "-m nightly" in steps[mutation]["run"]
    # #1376: финальный полный гейт перенесён в release (триггер push в main, а не workflow_run);
    # гейты гонятся на ТОЧНОМ релизном SHA — github.sha, т.е. merge-коммите. Вся джоба release
    # условна на нужде выпуска, поэтому per-step `if` заменён условием джобы.
    assert steps[0]["with"]["ref"] == "${{ github.sha }}"
    assert "needs.check.outputs.needed == 'true'" in str(job.get("if"))


@pytest.mark.parametrize("mutation_exit", [0, 7])
def test_actual_release_commands_never_tag_after_mutation_failure(tmp_path, mutation_exit):
    """Реальные run-блоки workflow; внешние tools заменены записью действий, сеть не нужна."""
    steps = yaml.safe_load((PKG / ".github/workflows/release.yml").read_text())["jobs"]["release"]["steps"]
    first = next(i for i, step in enumerate(steps) if "test_mutation_probe.py" in step.get("run", ""))
    last = next(i for i, step in enumerate(steps) if "gh release create" in step.get("run", ""))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    events = tmp_path / "events"
    fake_python = bindir / "python3"
    fake_python.write_text(f'''#!{sys.executable}
import os,sys
from pathlib import Path
a=sys.argv[1:]
name="mutation" if any("test_mutation_probe.py" in v for v in a) else "release_gate" if "pytest" in a else "notes"
with Path(os.environ["EVENTS"]).open("a") as stream: stream.write(name+"\\n")
if name=="mutation": raise SystemExit(int(os.environ["MUTATION_EXIT"]))
if name=="notes": print("fixture owner notes")
''')
    fake_python.chmod(0o755)
    (bindir / "pip").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "pip").chmod(0o755)
    fake_gh = bindir / "gh"
    fake_gh.write_text(f'''#!{sys.executable}
import os,sys
from pathlib import Path
assert sys.argv[1:3]==["release","create"]
assert sys.argv[sys.argv.index("--target")+1]==os.environ["HEAD_SHA"]
with Path(os.environ["EVENTS"]).open("a") as stream: stream.write("tag\\n")
''')
    fake_gh.chmod(0o755)
    commands = "\n".join(step.get("run", "") for step in steps[first:last+1])
    commands = commands.replace("/tmp/notes.md", str(tmp_path / "notes.md"))
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "EVENTS": str(events), "MUTATION_EXIT": str(mutation_exit), "VERSION": "0.0.1",
           "TAG": "v0.0.1", "HEAD_SHA": "a" * 40, "GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_REPOSITORY": "fixture/repo"}
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", commands], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=20)
    actual = events.read_text().splitlines()
    assert actual[0] == "mutation", result.stdout + result.stderr
    if mutation_exit:
        assert actual == ["mutation"] and result.returncode == mutation_exit
    else:
        assert actual == ["mutation", "release_gate", "release_gate", "notes", "tag"]
        assert result.returncode == 0 and (tmp_path / "notes.md").read_text().strip()


@pytest.mark.parametrize("args", [("-x",), ("--maxfail", "1"), ("--maxfail=1",)])
def test_pr_profile_refuses_early_exit_before_process(tmp_path, args):
    root, env = _tiny_scope_script(tmp_path)
    result = _run_tiny_scope(root, env, "--pr", *args)
    assert not Path(env["PYTHON_CALLS"]).exists(), result.stdout + result.stderr
    assert _scope_ids(env) == [] and result.returncode == 2
