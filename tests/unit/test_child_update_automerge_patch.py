"""Авто-мерж update-PR: только патч-версии, опт-ин, по умолчанию выключен.

Слияние в main — более сильное действие, чем открыть PR, поэтому авто-мерж:
- опт-ин через `parent.auto_merge_patch`, по умолчанию OFF (`.get(..., False)`);
- применяется ТОЛЬКО к патч-версиям (совпадают major.minor, растёт patch) — минор/мажор на ревью;
- через `gh pr merge --auto` (после обязательных проверок ветки), без мгновенного обхода `--admin`.
"""
from __future__ import annotations

from pathlib import Path

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
