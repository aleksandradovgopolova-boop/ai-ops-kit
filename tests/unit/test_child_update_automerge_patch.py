"""Авто-мерж update-PR: только патч-версии, опт-ин, по умолчанию выключен.

Слияние в main — более сильное действие, чем открыть PR, поэтому авто-мерж:
- опт-ин через `parent.auto_merge_patch`, по умолчанию OFF (`.get(..., False)`);
- применяется ТОЛЬКО к патч-версиям (совпадают major.minor, растёт patch) — минор/мажор на ревью;
- через `gh pr merge --auto` (после обязательных проверок ветки), без мгновенного обхода `--admin`.
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest
import yaml

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "ci" / "ai-ops-update.yml"


def test_template_is_valid_yaml() -> None:
    yaml.safe_load(TEMPLATE_PATH.read_text())


def test_automerge_is_opt_in_default_off() -> None:
    c = TEMPLATE_PATH.read_text()
    assert "auto_merge_patch" in c, "шаблон не читает флаг parent.auto_merge_patch"
    # дефолт OFF: чтение через .get(..., False)
    assert "get('auto_merge_patch', False)" in c or 'get("auto_merge_patch", False)' in c, \
        "auto_merge_patch должен по умолчанию быть выключен (.get(..., False))"


def test_automerge_only_patch() -> None:
    c = TEMPLATE_PATH.read_text()
    # гейт «только патч»: сравнение major.minor и рост patch, и отказ для не-патча
    assert "f[0]==t[0] and f[1]==t[1] and int(t[2])>int(f[2])" in c, \
        "нет проверки патч-версии (major.minor равны, patch растёт)"
    assert '!= patch' in c or '!= "patch"' in c or "!= 'patch'" in c, \
        "нет отказа авто-мержа для не-патч-версий"


def test_automerge_waits_for_checks_not_admin_bypass() -> None:
    c = TEMPLATE_PATH.read_text()
    assert "gh pr merge" in c and "--auto" in c, "авто-мерж должен идти через gh pr merge --auto"
    assert "--admin" not in c, "мгновенный обход проверок (--admin) недопустим для авто-мержа"


@pytest.mark.parametrize(
    "installed,available,auto,event,expected",
    [
        ("4.11.1", "4.11.2", "true", "schedule", "true"),
        ("4.11.1", "4.11.2", "false", "schedule", "false"),
        ("4.11.1", "4.11.2", "false", "workflow_dispatch", "true"),
        ("4.11.1", "4.11.2", "true", "workflow_dispatch", "true"),
        ("4.11.2", "4.11.2", "true", "schedule", "false"),
        ("4.11.2", "4.11.2", "true", "workflow_dispatch", "false"),
        ("4.11.2", "4.11.2", "false", "workflow_dispatch", "false"),
        ("4.11.1", "4.11.2", "unknown", "schedule", "false"),
    ],
)
def test_update_decision_executes_in_bash(
    tmp_path: Path, installed: str, available: str, auto: str, event: str, expected: str,
) -> None:
    """Исполнить реальную строку workflow: YAML/string assertions не ловили лишние кавычки."""
    workflow = yaml.safe_load(TEMPLATE_PATH.read_text())
    ver_step = next(s for s in workflow["jobs"]["update"]["steps"] if s.get("id") == "ver")
    decision = [line for line in ver_step["run"].splitlines() if 'echo "proceed=$(' in line]
    assert len(decision) == 1
    script = decision[0].replace("${{ github.event_name }}", event)
    output = tmp_path / "github output.txt"
    assert not output.exists()
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script], text=True, capture_output=True,
        env={**os.environ, "INSTALLED": installed, "AVAILABLE": available, "AUTO": auto,
             "GITHUB_OUTPUT": str(output)}, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file(), "workflow обязан действительно записать downstream output"
    assert output.read_text().splitlines() == [f"proceed={expected}"]
