"""Гейты дизайна цитируют стабильные ID UI/UX-Конституции (волна 2, наблюдение).

Работа `design-gates-cite-constitution-ids`. Три тонких блокирующих гейта дизайна работают по
чек-листам `rules/design/*`; каждый пункт несёт `constitution_id` — ID правила Конституции
(`standards/uiux/rules.yaml`, генерится из `UI_CONSTITUTION.md`), к которому пункт привязан по
смыслу. Находка ревью цитирует этот ID, как code-review цитирует rule id.

Тест держит ДВА инварианта:
  1. ПРИВЯЗКА ЧЕСТНА: каждый `constitution_id` (кроме явного `none`) резолвится в реальный ID
     реестра; каждый пункт вообще НЕСЁТ поле (новый пункт без привязки краснит); а страж резолва
     доказанно fail-closed (даёт False на выдуманном ID — не тавтология).
  2. СИЛА ГЕЙТОВ НЕ ТРОНУТА: `blocking`/`severity_policy` трёх гейтов в `quality/gates.yaml`
     совпадают с базлайном main. Эта работа — НАБЛЮДЕНИЕ; усиление покрытия — отдельная работа.
     Если кто-то под видом «цитирования ID» ослабит/усилит гейт — тест краснеет.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_YAML = REPO_ROOT / "standards" / "uiux" / "rules.yaml"
GATES_YAML = REPO_ROOT / "quality" / "gates.yaml"
RECONCILIATION = REPO_ROOT / "standards" / "uiux" / "gate-reconciliation.md"
DESIGN_DIR = REPO_ROOT / "rules" / "design"

# Три чек-листа, стоящие за тремя блокирующими гейтами дизайна.
CHECKLISTS = {
    "ux_review": DESIGN_DIR / "ux-heuristics.yaml",
    "accessibility_review": DESIGN_DIR / "accessibility-checklist.yaml",
    "design_system_usage": DESIGN_DIR / "design-system-checklist.yaml",
}

# Ревьюеры, чьи промпты обязаны инструктировать цитировать constitution_id.
REVIEWER_AGENTS = [
    REPO_ROOT / "agents" / "quality" / "ux-reviewer.md",
    REPO_ROOT / "agents" / "quality" / "accessibility-reviewer.md",
    REPO_ROOT / "agents" / "quality" / "design-system-reviewer.md",
]

# БАЗЛАЙН СИЛЫ ГЕЙТОВ на main (снят при постройке работы). Пин, а не чтение «самих себя»: смысл
# теста — заметить ИЗМЕНЕНИЕ этих полей, поэтому эталон зафиксирован здесь, а не выведен из файла.
EXPECTED_GATE_STRENGTH = {
    "ux_review": {
        "blocking": True,
        "severity_policy": {"critical": "fail", "major": "fail_or_documented_override", "minor": "nonblocking"},
    },
    "accessibility_review": {
        "blocking": True,
        "severity_policy": {"critical": "fail", "major": "fail_or_documented_override", "minor": "nonblocking"},
    },
    "design_system_usage": {
        # у design_system_usage severity_policy на main НЕТ — фиксируем и это (silent add = смена силы).
        "blocking": True,
        "severity_policy": None,
    },
}

SENTINEL_NONE = "none"


def _valid_rule_ids() -> set[str]:
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    return {r["id"] for r in d["rules"]}


def _resolves(constitution_id: str, valid_ids: set[str]) -> bool:
    """Страж привязки: ID валиден, если это явный `none` ИЛИ реальный ID реестра.

    Ровно эту функцию использует и позитивный, и fail-closed тест — иначе fail-closed доказывал бы
    тавтологию «строка in множество», а не поведение самого стража."""
    if constitution_id == SENTINEL_NONE:
        return True
    return constitution_id in valid_ids


def _iter_items():
    for gate, path in CHECKLISTS.items():
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in d["items"]:
            yield gate, path.name, item


@pytest.mark.unit
def test_every_checklist_item_carries_a_constitution_id():
    """Каждый пункт трёх чек-листов НЕСЁТ `constitution_id` — новый пункт без привязки краснит."""
    missing = [
        (fname, item["id"])
        for _gate, fname, item in _iter_items()
        if "constitution_id" not in item
    ]
    assert not missing, f"пункты без constitution_id: {missing}"


@pytest.mark.unit
def test_constitution_ids_resolve_to_real_rules():
    """ПРИВЯЗКА: каждый constitution_id (кроме `none`) резолвится в реальный ID standards/uiux/rules.yaml."""
    valid = _valid_rule_ids()
    dangling = [
        (fname, item["id"], item.get("constitution_id"))
        for _gate, fname, item in _iter_items()
        if not _resolves(item.get("constitution_id"), valid)
    ]
    assert not dangling, f"constitution_id не резолвится в реестр (мёртвая/выдуманная ссылка): {dangling}"


@pytest.mark.unit
def test_resolver_is_fail_closed():
    """FAIL-CLOSED: сам страж `_resolves` даёт КРАСНОЕ на выдуманном ID, а не только True на всём.

    Иначе тест привязки был бы тавтологией: он должен ловить именно несуществующий ID."""
    valid = _valid_rule_ids()
    real = next(iter(valid))
    assert _resolves(real, valid) is True, "страж отвергает реальный ID — ложное красное"
    assert _resolves(SENTINEL_NONE, valid) is True, "явный none должен считаться валидным"
    assert _resolves("UI-000-НЕТ-ТАКОГО", valid) is False, (
        "страж НЕ ловит выдуманный ID — привязка была бы дырявой")


@pytest.mark.unit
def test_gate_strength_unchanged_from_main():
    """СИЛА НЕ ТРОНУТА: blocking/severity_policy трёх гейтов == базлайну main (это наблюдение)."""
    gates = yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))["gates"]
    for gate_id, expected in EXPECTED_GATE_STRENGTH.items():
        gate = gates[gate_id]
        assert gate.get("blocking") == expected["blocking"], (
            f"{gate_id}: blocking изменён ({gate.get('blocking')} != {expected['blocking']}) — "
            "эта работа не меняет силу гейтов")
        assert gate.get("severity_policy") == expected["severity_policy"], (
            f"{gate_id}: severity_policy изменён — эта работа не меняет силу гейтов")


@pytest.mark.unit
def test_reviewer_prompts_instruct_citing_constitution_id():
    """ШОВ: промпты трёх ревьюеров инструктируют цитировать constitution_id (проводка, не только данные)."""
    for agent in REVIEWER_AGENTS:
        text = agent.read_text(encoding="utf-8")
        assert "constitution_id" in text, (
            f"{agent.name} не инструктирует цитировать constitution_id — находки не будут ссылаться на Конституцию")


@pytest.mark.unit
def test_divergences_are_recorded_and_honest():
    """РАСХОЖДЕНИЯ НЕ СКРЫТЫ: файл реконсиляции существует и называет каждый `none`-пункт поимённо."""
    assert RECONCILIATION.is_file(), "нет standards/uiux/gate-reconciliation.md — расхождения не зафиксированы"
    doc = RECONCILIATION.read_text(encoding="utf-8")
    none_items = [item["id"] for _g, _f, item in _iter_items() if item.get("constitution_id") == SENTINEL_NONE]
    assert none_items, "ожидались пункты без правила Конституции — иначе расхождения A нечего фиксировать"
    for item_id in none_items:
        assert item_id in doc, f"пункт `{item_id}` с constitution_id=none не назван в реконсиляции — расхождение скрыто"
