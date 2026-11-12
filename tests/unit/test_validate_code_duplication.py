"""Проверка дублей функций в ПРОЕКТЕ (CODE-003 у дочки, #1512).

Эффект проверяется на настоящем дереве проекта во временном каталоге и настоящим процессом
валидатора: база создаётся и читается с диска, новая группа сверх неё видна с адресом, проект без
Python слышит «не проверяется», а не «дублей нет».
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.checks import code_duplication as core

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
VALIDATOR = PKG / "ai_ops_kit" / "validation" / "validate_code_duplication.py"


def _fn(name: str) -> str:
    """Функция в 10+ операторов одной и той же структуры (имя и константы — разные)."""
    return (f"def {name}(x):\n    total = 0\n    count = 0\n    acc = 1\n    for i in range(x):\n"
            "        if i % 2 == 0:\n            total += i\n        else:\n            total -= i\n"
            "        count += 1\n        acc *= 2\n    return total, count, acc\n\n")


def _run(root: Path, *args):
    env = {"PATH": os.defpath, "HOME": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(VALIDATOR), "--child-root", str(root), *args],
                          capture_output=True, text=True, timeout=60, env=env)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/orders.py").write_text(_fn("load_orders"), encoding="utf-8")
    (tmp_path / "app/clients.py").write_text(_fn("load_clients"), encoding="utf-8")
    return tmp_path


def test_without_baseline_existing_duplicates_are_listed_not_hidden(project):
    result = _run(project)
    assert result.returncode == 1
    assert "база не принята — найдено групп дублей: 1" in result.stdout
    assert "app/clients.py:1:load_clients" in result.stdout and "--write-baseline" in result.stdout


def test_frozen_duplicates_pass_and_new_group_is_reported_with_address(project):
    written = _run(project, "--write-baseline")
    baseline = project / core.CHILD_BASELINE
    assert written.returncode == 0 and baseline.is_file()                # база реально на диске
    assert len(yaml.safe_load(baseline.read_text())["groups"]) == 1
    assert _run(project).returncode == 0                                  # заморожено — тихо
    (project / "app/payments.py").write_text(_fn("load_payments").replace("acc *= 2", "acc *= 3")
                                             .replace("    return", "    acc += 1\n    return"))
    (project / "app/refunds.py").write_text(_fn("load_refunds").replace("acc *= 2", "acc *= 3")
                                            .replace("    return", "    acc += 1\n    return"))
    result = _run(project)
    assert result.returncode == 1
    assert "новых групп дублей сверх базы: 1 (заморожено 1)" in result.stdout
    assert "app/payments.py:1:load_payments" in result.stdout


def test_removed_duplicate_is_reported_as_stale_baseline(project):
    _run(project, "--write-baseline")
    (project / "app/clients.py").write_text("def load_clients():\n    return []\n")
    result = _run(project)
    assert result.returncode == 0 and "сократите базу" in result.stdout


def test_existing_baseline_is_not_refrozen_without_force(project):
    _run(project, "--write-baseline")
    baseline = project / core.CHILD_BASELINE
    before = baseline.read_bytes()
    (project / "app/more.py").write_text(_fn("load_more"))
    refused = _run(project, "--write-baseline")
    assert refused.returncode == 1 and "--force" in refused.stdout
    assert baseline.read_bytes() == before                                # рост не «отмыт»
    assert _run(project, "--write-baseline", "--force").returncode == 0
    assert baseline.read_bytes() != before


def test_project_without_python_is_not_checked_not_clean(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.ts").write_text("export const a = 1\n")
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "НЕ ПРОВЕРЯЕТСЯ" in result.stdout and "TypeScript — 1" in result.stdout
    assert "OK" not in result.stdout
    assert not (tmp_path / core.CHILD_BASELINE).exists()
    assert _run(tmp_path, "--write-baseline").returncode == 2


def test_mixed_project_names_unchecked_languages(project):
    (project / "web").mkdir()
    (project / "web/ui.js").write_text("export const b = 2\n")
    result = _run(project)
    assert "проверено: Python — 2 файлов" in result.stdout
    assert "НЕ проверяется (детектор читает только Python): JavaScript — 1" in result.stdout


def test_tests_and_service_dirs_are_not_scanned(project):
    for d in ("tests", ".ai/managed", "node_modules/pkg", ".venv/lib"):
        (project / d).mkdir(parents=True)
        (project / d / "dup.py").write_text(_fn("load_noise"))
    groups = core.scan_project(project)["groups"]
    assert len(groups) == 1 and all("load_noise" not in m for m in groups[0]["members"])


def test_validator_ships_to_the_child():
    sys.path.insert(0, str(PKG / "installer"))
    try:
        import delivery_ops
    finally:
        sys.path.pop(0)
    assert delivery_ops.is_runtime_asset("ai_ops_kit/validation/validate_code_duplication.py")
    assert delivery_ops.is_runtime_asset("ai_ops_kit/checks/code_duplication.py")


def test_child_ci_runs_it_as_advisory_step():
    workflow = yaml.safe_load((PKG / "templates/ci/ai-ops-validate.yml").read_text(encoding="utf-8"))
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    step = next(s for s in steps if "validate_code_duplication.py" in str(s.get("run", "")))
    assert step.get("continue-on-error") is True and "--child-root ." in step["run"]


def test_first_health_says_not_checked_for_project_without_python(tmp_path):
    from ai_ops_kit.cli import ai_ops_cli_first_health as H
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.ts").write_text("export const a = 1\n")
    item = H._code_item(tmp_path)
    assert item["status"] == H.NOT_CHECKED and "не проверяется" in item["text"]
    (tmp_path / "src/app.py").write_text("x = 1\n")
    assert H._code_item(tmp_path)["status"] == H.OK


def test_unreadable_python_is_not_counted_as_checked(tmp_path):
    (tmp_path / "bad.py").write_bytes(b'x = "\\xff"\nprint "py2"\n')
    (tmp_path / "latin.py").write_bytes(b"s = '\xff'\n")
    result = _run(tmp_path)
    assert result.returncode == 2 and "НЕ ПРОВЕРЯЕТСЯ" in result.stdout
    assert "НЕ прочитано (кодировка/синтаксис) Python — 2" in result.stdout
    assert _run(tmp_path, "--write-baseline").returncode == 2
    assert not (tmp_path / core.CHILD_BASELINE).exists()


def test_partially_unreadable_project_names_skipped_files(project):
    (project / "app/broken.py").write_text("def f(:\n")
    result = _run(project)
    assert "проверено: Python — 2 файлов" in result.stdout and "app/broken.py" in result.stdout


@pytest.mark.parametrize("text", ["groups: [unclosed\n", "- a\n- b\n", "groups: 3\n"])
def test_malformed_baseline_is_named_not_a_traceback(project, text):
    baseline = project / core.CHILD_BASELINE
    baseline.parent.mkdir(parents=True)
    baseline.write_text(text)
    result = _run(project)
    assert result.returncode == 2 and "база не читается" in result.stdout
    assert "Traceback" not in result.stderr
