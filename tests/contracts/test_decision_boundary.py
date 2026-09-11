"""Граница решений НАЗВАНА данными — и её имена ложатся на РЕАЛЬНЫЙ механизм (issue #615).

`registry/decision-boundary.yaml` — не декларация в вакууме: каждый класс действия
(AUTONOMOUS/COLLABORATIVE/ASSISTED) заявляет `maps_to_autonomy_level`, а этот тест ПРОВЕРЯЕТ, что
заявленный уровень ведёт себя в исполняемом gate (`policy_engine`) именно так, как обещает класс:
  * AUTONOMOUS(execute)         — кит исполняет сам, без одобрения;
  * COLLABORATIVE(require_approval) — заблокировано без одобрения, разрешено с ним;
  * ASSISTED(suggest)          — автономно не исполняется (решение за человеком).

И честность деклараций (инвариант AGENTS.md): у каждой строки `implemented_by` статус из набора, а
названный файл механизма РЕАЛЬНО существует — заявленная связь не имеет права быть выдумкой.

Тест ПОВЕДЕНЧЕСКИЙ: он импортирует продуктовый код кита (`policy_engine`, `spec_levels`) и ЗОВЁТ
его, доказывая, что имя класса = поведение gate, а не подпись под ним.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.gates import spec_levels
from ai_ops_kit.governance import decision_boundary as db
from ai_ops_kit.governance import policy_engine as pe

KIT = Path(__file__).resolve().parents[2]
MODEL_REL = "registry/decision-boundary.yaml"


@pytest.fixture(scope="module")
def model():
    doc = yaml.safe_load((KIT / MODEL_REL).read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "decision-boundary.yaml не разобран в mapping"
    return doc


def _classes(model):
    return {c["id"]: c for c in model["classes"]}


# ── форма модели: три оси, три класса, правило ──────────────────────────────────────────────────

def test_model_declares_three_axes(model):
    axes = {a["id"] for a in model["axes"]}
    assert axes == {"reversibility", "blast_radius", "error_cost"}, (
        f"оси границы решений должны быть ровно три (обратимость × радиус × цена), а не {axes}")


def test_model_declares_three_named_classes(model):
    ids = set(_classes(model))
    assert ids == {"AUTONOMOUS", "COLLABORATIVE", "ASSISTED"}, (
        f"класса действий должно быть ровно три названных, а не {ids}")


def test_assignment_rule_escalates_by_worst_axis(model):
    rule = model["assignment_rule"]
    assert rule["id"] == "worst_axis_escalates"
    # правило и его инварианты названы, а не подразумеваются
    assert rule.get("never_downgraded_silently"), "не назван инвариант «нельзя понизить молча»"
    assert rule.get("fail_closed"), "не назван инвариант fail-closed"


# ── имена классов ложатся на РЕАЛЬНЫЙ gate автономии ────────────────────────────────────────────

def test_class_levels_are_known_autonomy_levels(model):
    """Каждый класс маппится на уровень, который вообще существует в исполняемом gate."""
    for cid, c in _classes(model).items():
        assert c["maps_to_autonomy_level"] in pe.LEVELS, (
            f"{cid}: уровень {c['maps_to_autonomy_level']} не из policy_engine.LEVELS {pe.LEVELS}")


def test_class_levels_match_artifact_registry_vocabulary(model):
    """Тот же словарь уровней, что и у артефактов (одна правда, не две)."""
    reg = yaml.safe_load((KIT / "registry" / "artifact-registry.yaml").read_text(encoding="utf-8"))
    vocab = set(reg["autonomy_levels"])
    for cid, c in _classes(model).items():
        assert c["maps_to_autonomy_level"] in vocab, (
            f"{cid}: уровень не из artifact-registry.autonomy_levels {vocab}")


def test_autonomous_class_executes_without_approval(model):
    """AUTONOMOUS обещает «кит делает сам» — уровень execute РЕАЛЬНО исполняет без одобрения."""
    level = _classes(model)["AUTONOMOUS"]["maps_to_autonomy_level"]
    policy = {"default": level, "actions": {}}
    decision = pe.authorize("act", policy)
    assert decision["allowed"] is True, "AUTONOMOUS обязан исполняться автономно"
    assert decision["requires_approval"] is False


def test_collaborative_class_blocks_until_human_approves(model):
    """COLLABORATIVE обещает «кит готовит, человек одобряет» — без approved gate блокирует, с ним пускает."""
    level = _classes(model)["COLLABORATIVE"]["maps_to_autonomy_level"]
    policy = {"default": level, "actions": {}}
    assert pe.may_execute("act", policy, approved=False) is False, (
        "COLLABORATIVE без одобрения человека не должен исполняться")
    assert pe.may_execute("act", policy, approved=True) is True, (
        "COLLABORATIVE с одобрением человека обязан исполниться")


def test_assisted_class_never_executes_autonomously(model):
    """ASSISTED обещает «решение за человеком» — уровень не исполняет автономно даже при approved."""
    level = _classes(model)["ASSISTED"]["maps_to_autonomy_level"]
    policy = {"default": level, "actions": {}}
    assert pe.may_execute("act", policy, approved=False) is False
    assert pe.may_execute("act", policy, approved=True) is False, (
        "ASSISTED — решение человека, а не автономное действие кита")


# ── тяжёлая ось реально поднимает строгость (spec_levels) ────────────────────────────────────────

def test_irreversible_axis_escalates_to_critical(model):
    """Ось «обратимость» в тяжёлом полюсе (irreversible) РЕАЛЬНО эскалирует спецификацию до L3 CRITICAL —
    механизм, на который ссылается implemented_by, а не только слова модели."""
    assert spec_levels.classify({"irreversible": True})["level"] == 3
    assert spec_levels.classify({"risk": "critical"})["level"] == 3
    # мягкий профиль не эскалирует — иначе «эскалация» ничего не значила бы
    assert spec_levels.classify({"task_type": "QUICK"})["level"] == 0


# ── честность деклараций implemented_by ─────────────────────────────────────────────────────────

def test_implemented_by_status_is_honest(model):
    """Каждая строка помечена implemented|planned; ничто не выдаётся за готовое молча."""
    for row in model["implemented_by"]:
        assert row["status"] in ("implemented", "planned"), (
            f"{row['mechanism']}: статус '{row['status']}' не из (implemented, planned)")


def test_named_mechanism_files_exist(model):
    """Заявленный файл механизма (`where`) РЕАЛЬНО существует — связь не выдумана."""
    for row in model["implemented_by"]:
        where = row.get("where")
        if where is None:
            # where=null допустим ТОЛЬКО для planned (механизм ещё не собран)
            assert row["status"] == "planned", (
                f"{row['mechanism']}: implemented без файла — where не может быть null")
            continue
        assert (KIT / where).exists(), f"{row['mechanism']}: названного файла нет — {where}"


def test_every_class_is_backed_by_some_mechanism(model):
    """Каждый класс упомянут хотя бы одним implemented механизмом — имя не висит в воздухе."""
    backed = set()
    for row in model["implemented_by"]:
        if row["status"] == "implemented":
            backed.update(row.get("provides") or [])
    for cid in _classes(model):
        assert cid in backed, f"{cid}: ни один РЕАЛИЗОВАННЫЙ механизм его не исполняет"


# ── ЕДИНЫЙ КЛАССИФИКАТОР: три оси разом → имя класса (issue #631) ─────────────────────────────────
# Тесты ПОВЕДЕНЧЕСКИЕ: зовут decision_boundary.evaluate и проверяют, что имя класса считается из
# всех трёх осей вместе по правилу модели, а не описано словами.

def test_all_soft_axes_give_autonomous():
    v = db.evaluate({"risk": "low"})
    assert v["decision_class"] == "AUTONOMOUS"
    assert v["autonomy_level"] == "execute"
    assert v["requires_approval"] is False


def test_irreversible_axis_escalates_to_assisted():
    v = db.evaluate({"risk": "low", "irreversible": True})
    assert v["decision_class"] == "ASSISTED", "необратимость — тяжёлая ось, решение за человеком"
    assert v["autonomy_level"] == "suggest"
    assert v["executor"] == "human"


def test_expensive_axis_escalates_to_assisted():
    assert db.evaluate({"risk": "critical"})["decision_class"] == "ASSISTED"
    assert db.evaluate({"risk": "high"})["decision_class"] == "ASSISTED"
    assert db.evaluate({"secret_boundary": True})["decision_class"] == "ASSISTED"


def test_wide_blast_radius_escalates_to_assisted():
    assert db.evaluate({"risk": "low", "blast_radius": "wide"})["decision_class"] == "ASSISTED"
    assert db.evaluate({"risk": "low", "external_consumers": True})["decision_class"] == "ASSISTED"


def test_mixed_profile_gives_collaborative():
    v = db.evaluate({"risk": "low", "protected_paths": True})
    assert v["decision_class"] == "COLLABORATIVE", "защищённые пути без тяжёлой оси → совместно"
    assert v["autonomy_level"] == "require_approval"
    assert db.evaluate({"risk": "medium"})["decision_class"] == "COLLABORATIVE"


def test_no_signals_fails_closed_to_collaborative():
    """fail_closed: цену подтвердить нечем (нет risk) → не AUTONOMOUS, а COLLABORATIVE."""
    v = db.evaluate({})
    assert v["decision_class"] == "COLLABORATIVE"
    assert v["requires_approval"] is True


def test_worst_axis_escalates_among_soft():
    """Одна тяжёлая ось среди мягких поднимает весь класс до ASSISTED."""
    v = db.evaluate({"risk": "low", "blast_radius": "local", "irreversible": True})
    assert v["decision_class"] == "ASSISTED"


def test_requested_more_autonomous_is_not_silently_downgraded():
    """never_downgraded_silently: запрос AUTONOMOUS при необратимом действии не понижает строгость."""
    v = db.evaluate({"irreversible": True}, requested_class="AUTONOMOUS")
    assert v["decision_class"] == "ASSISTED", "нельзя понизить строгость молча"
    assert v["escalated_from"] == "AUTONOMOUS"
    assert any("нельзя понизить молча" in r for r in v["reason"])


def test_requested_stricter_is_honored():
    """Строже — можно: запрос ASSISTED на мягком профиле принимается."""
    v = db.evaluate({"risk": "low"}, requested_class="ASSISTED")
    assert v["decision_class"] == "ASSISTED"


def test_class_level_mapping_comes_from_registry(model):
    """autonomy_level классификатора = maps_to_autonomy_level ИЗ реестра (единый источник, не дубль)."""
    classes = _classes(model)
    for cls_id, signals in (("AUTONOMOUS", {"risk": "low"}),
                            ("COLLABORATIVE", {"risk": "medium"}),
                            ("ASSISTED", {"risk": "critical"})):
        v = db.evaluate(signals)
        assert v["decision_class"] == cls_id
        assert v["autonomy_level"] == classes[cls_id]["maps_to_autonomy_level"], (
            f"{cls_id}: уровень классификатора разошёлся с реестром")


def test_reason_is_present_and_explains(model):
    """Вердикт объясним: причина непуста для любого действия."""
    for signals in ({}, {"risk": "low"}, {"risk": "critical"}, {"protected_paths": True}):
        v = db.evaluate(signals)
        assert v["reason"] and all(isinstance(r, str) for r in v["reason"])
