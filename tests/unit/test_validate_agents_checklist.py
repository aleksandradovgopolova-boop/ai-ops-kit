"""Инвариант pytest-only — новая роль validate_agents_checklist (v3.30).

Прежде валидатор ловил дрейф между списком команд чеклиста и командами CI. Списка больше нет:
201 команда переехала в pytest. Валидатор перенаправлен на инвариант, который этот переезд
защищает — CI не запускает проверки в обход pytest. За одну сессию дубль возвращался трижды,
поэтому охранять его должна машина.

Три обязательных теста на capability (AGENTS.md):
 * positive — в реальном репозитории нарушений нет; разрешённые формы не считаются;
 * fail-closed — прямой запуск валидатора в workflow обнаруживается;
 * side-effect — вердикт отражён в коде возврата и в --json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import validate_agents_checklist as vac

PKG = Path(__file__).resolve().parents[2]


def _fake_repo(tmp_path, run_body):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "x.yml").write_text(
        textwrap.dedent(
            f"""\
            name: x
            on: {{push: {{branches: [main]}}}}
            jobs:
              j:
                runs-on: ubuntu-latest
                steps:
                  - run: |
                      {run_body}
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------- positive ---


@pytest.mark.unit
def test_real_repo_has_no_offenders():
    assert vac.offending_commands() == [], "в CI есть проверки мимо pytest"


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    [
        "python3 -m pytest tests/ -q",
        "bash .github/ci-groups/fast.sh",
        "pip install pyyaml pytest",
        "./scripts/check-full.sh",
    ],
)
def test_allowed_forms_are_not_flagged(tmp_path, line):
    assert vac.offending_commands(_fake_repo(tmp_path, line)) == [], line


# ------------------------------------------------------------- fail-closed ---


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    [
        "python3 validation/validate_ai_first_registry.py",
        "python3 tools/security_scan.py --selftest",
        "python .research/tools/verify_quotes.py --selftest",
    ],
)
def test_direct_check_is_detected(tmp_path, line):
    bad = vac.offending_commands(_fake_repo(tmp_path, line))
    assert bad, f"прямой запуск проверки не обнаружен: {line}"
    assert line in bad[0][1]


@pytest.mark.unit
def test_unreadable_workflow_is_reported(tmp_path):
    """Нечитаемый workflow не запускается вовсе — молчать об этом нельзя."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "broken.yml").write_text("jobs: [не: закрыто\n", encoding="utf-8")
    assert vac.offending_commands(tmp_path), "битый workflow пропущен молча"


# -------------------------------------------------------- side-effect proof ---


@pytest.mark.unit
def test_exit_code_and_json_reflect_the_verdict():
    r = subprocess.run(
        [
            sys.executable,
            str(PKG / "ai_ops_kit" / "validation" / "validate_agents_checklist.py"),
            "--json",
        ],
        cwd=PKG,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["offending"] == []


# ------------------------------------------------ ручной операционный workflow ---


def _named_workflow(tmp_path, name, triggers):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / name).write_text(
        f"name: x\non: {triggers}\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python3 -m ai_ops_kit.devtools.host_resource_cli --owner x -- bash m.sh\n",
        encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_manual_measurement_workflow_is_exempt_while_manual_only(tmp_path):
    """Ручной замер производит данные, а не вердикт: пока запуск только ручной, он не нарушение."""
    root = _named_workflow(tmp_path, "performance-baseline.yml", "{workflow_dispatch: {}}")
    assert vac.offending_commands(root) == []


@pytest.mark.unit
@pytest.mark.parametrize("triggers", [
    "{workflow_dispatch: {}, pull_request: {}}",
    "{workflow_dispatch: {}, schedule: [{cron: '0 4 * * 0'}]}",
    "{push: {branches: [main]}}",
])
def test_exemption_ends_with_any_automatic_trigger(tmp_path, triggers):
    """Fail-closed: с автоматическим запуском тот же workflow — проверка мимо pytest."""
    root = _named_workflow(tmp_path, "performance-baseline.yml", triggers)
    bad = vac.offending_commands(root)
    assert [w for w, _ in bad] == ["performance-baseline.yml"], bad


@pytest.mark.unit
def test_exemption_is_by_name_not_by_being_manual(tmp_path):
    """Ручной запуск сам по себе не освобождает: список поимённый."""
    root = _named_workflow(tmp_path, "other-manual.yml", "{workflow_dispatch: {}}")
    assert [w for w, _ in vac.offending_commands(root)] == ["other-manual.yml"]
