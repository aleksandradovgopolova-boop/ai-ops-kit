"""Охват доказательства называется, а не подразумевается (v3.34).

`./scripts/check-full.sh` означает «весь pytest на ТОМ интерпретаторе, что стоит у запускающего»,
а не «поддерживаемая матрица целиком». PR #38 написал «полный контур зелёный» — и джоба
python39-compat опровергла это в том же релизе, потому что новый тест импортировал `tomllib`
при объявленном поле 3.9.

Дефект здесь не в тексте PR, а в отсутствии словаря: пока «полный» не имеет величины, заявление
шире полученного делается без единой ошибки. `registry/release-claims.yaml` объявляет два охвата,
`validate_release_claims` требует, чтобы оба существовали и чтобы заявление о полноте называло,
какой из них получен.

Три обязательных теста на capability (AGENTS.md):
  * positive     — реальный реестр объявляет оба охвата и проходит проверку;
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

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "validation"))

import validate_release_claims as vrc  # noqa: E402

SCRIPT = PKG / "scripts" / "check-full.sh"


@pytest.fixture(scope="module")
def claims():
    return yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


def test_both_scopes_are_declared(claims):
    """positive: словарь существует, и в нём именно два различаемых охвата."""
    assert not vrc.evidence_scope_errors(claims), vrc.evidence_scope_errors(claims)
    scopes = claims["evidence_scopes"]
    for name in vrc.REQUIRED_SCOPES:
        assert str(scopes[name]["does_not_cover"]).strip(), (
            f"{name} без границы — охват, который «покрывает всё», это снова «полный»")


def test_full_claim_without_a_scope_is_caught(claims):
    """fail-closed: ровно то заявление, которое сделал PR #38, обязано краснеть."""
    errors = vrc.evidence_scope_errors(
        dict(claims, patch_note="3.34 — полный контур зелёный, релиз готов."))
    assert any("не называя охват" in e for e in errors), errors


def test_scoped_claim_passes(claims):
    """То же заявление с названным охватом проходит: проверка бьёт по подмене, не по слову."""
    ok = dict(claims, patch_note="3.34 — охват full-current-python зелёный целиком.")
    assert not vrc.evidence_scope_errors(ok), vrc.evidence_scope_errors(ok)


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


def test_script_announces_the_scope_it_actually_gives():
    """side-effect: доказать, что охват РЕАЛЬНО печатается, прежде чем считать его объявленным.

    Реестр может сколько угодно объявлять словарь — увидит его тот, кто запускает проверку, и
    только если скрипт говорит это сам. Прогон с `--collect-only` даёт настоящий запуск скрипта
    без четырёх минут тестов.
    """
    env = {**os.environ, "PYTHON": sys.executable}
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"],
                       cwd=str(PKG), capture_output=True, text=True, timeout=300, env=env)
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
                       env={**os.environ, "PYTHON": str(fake)})
    assert r.returncode == 2, (r.returncode, (r.stdout + r.stderr)[-600:])
    assert "pytest в нём нет" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-600:]


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
                       env={**os.environ, "PYTHON": str(wrapper)})
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
