"""Разбор машинизуемости не расходится с реестром гейтов (C3, v3.37).

Разбор, лежащий прозой, врёт со второго дня: гейт перевели — строка осталась; гейт добавили —
строки нет. Здесь проверяется связь в обе стороны и то, что сам разбор осмыслен: у каждого вердикта
есть причина, у каждого — «что для этого нужно», и ни одно объявленное доказательство не выдумано.

Плюс пробы: карта обязана краснеть на забытом гейте, на лишнем и на том, что хвалится переводом,
которого не было.
"""
from __future__ import annotations

import copy

import pytest

from ai_ops_kit.devtools import gate_machinability as gm
from ai_ops_kit.gates.gate_executor import load_gates

GATES = load_gates()
REG = gm.load_registry()


def test_the_map_matches_the_gate_registry():
    errs = gm.coverage_errors(REG, GATES)
    assert errs == [], "\n  - ".join([""] + errs)


def test_every_opinion_closed_gate_is_covered():
    """Ни один гейт, чьё «зелёное» — мнение, не остался без разбора."""
    covered = set(REG["gates"])
    assert gm.opinion_gates(GATES) <= covered


def test_every_entry_names_a_reason_and_what_is_missing():
    for gid, e in REG["gates"].items():
        assert e["verdict"] in gm.VERDICTS, gid
        assert len(e.get("reason", "").split()) >= 8, f"{gid}: причина в одно слово — не причина"
        assert len(e.get("needs", "").split()) >= 3, f"{gid}: «что нужно» не названо"


def test_declared_evidence_keys_exist_in_the_gate_registry():
    """Разбор ссылается на доказательства, которые у гейта ЕСТЬ, а не на придуманные."""
    for gid, e in REG["gates"].items():
        actual = set((GATES[gid].get("required_evidence") or []))
        declared = set((e.get("machine_evidence") or []) + (e.get("judge_evidence") or []))
        assert declared <= actual, f"{gid}: {sorted(declared - actual)} нет в quality/gates.yaml"


def test_human_by_nature_gates_are_named_and_do_not_contradict_their_own_data():
    """Самая важная группа: объявить гейт человеческим — это отказ от машины, и он требует довода.

    Довод проверяется структурно, а не по наличию слова в прозе: если ВСЕ доказательства гейта
    объявлены машинными, вердикт «человеческое по существу» противоречит собственным данным
    записи — либо вердикт неверен, либо классификация доказательств."""
    human = {gid for gid, e in REG["gates"].items() if e["verdict"] == "human_by_nature"}
    assert human == {"code_review", "architecture_review", "decision_quality",
                     "stakeholder_readiness"}, human
    for gid in human:
        e = REG["gates"][gid]
        actual = set(GATES[gid].get("required_evidence") or [])
        machine = set(e.get("machine_evidence") or [])
        assert machine != actual or not actual, (
            f"{gid}: все доказательства объявлены машинными, но вердикт — человеческий. "
            f"Одно из двух неверно")
        assert len(e["reason"].split()) >= 15, f"{gid}: отказ от машины без развёрнутого довода"


def test_the_converted_gate_is_marked_done_and_is_actually_machine():
    e = REG["gates"]["documentation_updated"]
    assert e["status"] == "done" and e["verdict"] == "mechanizable"
    assert GATES["documentation_updated"].get("closed_by") == "validator"
    assert GATES["documentation_updated"].get("validator") == "validate-documentation-updated"


def test_split_counts_add_up_and_reach_the_report():
    rep = gm.split(REG, GATES)
    assert sum(rep["counts"].values()) == len(REG["gates"])
    assert rep["closed_by_machine"] + rep["closed_by_opinion"] == rep["gates_total"]
    text = gm.format_report(rep)
    assert "может стать машинным" in text and "по существу человеческое" in text
    assert "documentation_updated" in text


# ─── пробы: карта обязана краснеть ─────────────────────────────────────────────────────────────

def test_a_forgotten_gate_is_caught():
    reg = copy.deepcopy(REG)
    reg["gates"].pop("security")
    assert any("security" in e and "нет" in e for e in gm.coverage_errors(reg, GATES))


def test_an_entry_for_a_machine_gate_is_caught():
    reg = copy.deepcopy(REG)
    reg["gates"]["intake_completeness"] = {"verdict": "mechanizable", "reason": "x " * 10,
                                           "needs": "a b c"}
    assert any("intake_completeness" in e for e in gm.coverage_errors(reg, GATES))


def test_claiming_a_conversion_that_did_not_happen_is_caught():
    """Карта не вправе хвалиться переводом: гейт с `done` обязан быть машинным в реестре."""
    reg = copy.deepcopy(REG)
    reg["gates"]["security"]["status"] = "done"
    errs = gm.coverage_errors(reg, GATES)
    assert any("хвалится" in e for e in errs), errs


def test_a_verdict_without_a_reason_is_caught():
    reg = copy.deepcopy(REG)
    reg["gates"]["security"]["reason"] = ""
    assert any("без причины" in e for e in gm.coverage_errors(reg, GATES))


def test_an_invented_evidence_key_is_caught():
    reg = copy.deepcopy(REG)
    reg["gates"]["security"]["machine_evidence"] = ["no_secrets", "магия"]
    assert any("магия" in e for e in gm.coverage_errors(reg, GATES))


@pytest.mark.parametrize("verdict", ["mechanizable", "partly", "human_by_nature"])
def test_every_verdict_value_is_explained_in_the_registry(verdict):
    """Словарь вердиктов объявлен рядом с данными: читающий не должен угадывать значения."""
    assert len(REG["verdicts"][verdict].split()) >= 10
