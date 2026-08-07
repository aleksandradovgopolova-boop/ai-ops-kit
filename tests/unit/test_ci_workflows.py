"""CI-конфиг согласован с pytest.ini.

Причина: `pytest.ini` объявляет `--cov` в addopts, а два джоба ставили только `pyyaml pytest`.
Любой запуск pytest без `--no-cov` в таком джобе падал на разборе аргументов — до единого теста,
за 12 секунд, с сообщением «unrecognized arguments: --cov=...». Один из них (`pr-smoke`) блокировал
каждый PR, второй держал `package-quality` на main красным.

Класс дефекта тот же, что у checks_count: конфигурация в одном файле, требование — в другом, и
ничто их не сверяет. Здесь сверка есть.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((PKG / ".github" / "workflows").glob("*.yml"))


def _addopts_require_cov():
    text = (PKG / "pytest.ini").read_text(encoding="utf-8")
    return "--cov" in text


def _jobs(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (data.get("jobs") or {}).items()


def _steps_text(job):
    out = []
    for st in job.get("steps") or []:
        if isinstance(st, dict):
            out.append(str(st.get("run") or ""))
    return out


@pytest.mark.unit
def test_workflows_exist():
    assert WORKFLOWS, "не найдено ни одного workflow — проверка бессмысленна"


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_every_pytest_job_can_satisfy_addopts(wf):
    """Джоб, запускающий pytest без --no-cov, обязан ставить pytest-cov."""
    if not _addopts_require_cov():
        pytest.skip("pytest.ini больше не требует --cov")

    broken = []
    for name, job in _jobs(wf):
        runs = _steps_text(job)
        installs_cov = any("pytest-cov" in r for r in runs)
        for r in runs:
            for line in r.splitlines():
                if not re.search(r"\bpytest\b", line) or "pip install" in line:
                    continue
                if "-m pytest" not in line and not line.strip().startswith("pytest"):
                    continue
                if "--no-cov" in line:
                    continue
                if not installs_cov:
                    broken.append(f"{name}: {line.strip()[:90]}")
    assert not broken, (
        "pytest запускается с --cov из addopts, но джоб не ставит pytest-cov — "
        f"падение на разборе аргументов до первого теста: {broken}")


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_workflow_is_valid_yaml_with_jobs(wf):
    """Битый workflow не запускается вовсе — молчаливо зелёный PR без единой проверки."""
    data = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("jobs"), f"{wf.name}: нет jobs"
