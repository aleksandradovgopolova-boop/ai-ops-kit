"""Каждый гейт машиночитаемо отвечает «какую ошибку он предотвращает» — ратчет (#636, поверх #616).

ПОВОД — ВНЕШНЕЕ ПРОДУКТОВОЕ РЕВЮ 08.09.2026 (п.13). Прополка #616 уже дала по каждому advisory-гейту
ЯВНОЕ решение данными (`quality/gates.yaml` → `advisory_review`). Чего не хватало структурно:
failure mode жил ТОЛЬКО прозой в `purpose` («Класс: непроверенное исправление»), а false-positive
rate — булевым `field_evidence` + числом в комментарии. Нельзя было машинно спросить «что гейт
предотвращает и с какой частотой ложных».

ЧТО ЗДЕСЬ. Ратчет на два инлайн-поля каждого гейта:
  * `prevents` — класс дефекта (короткий ключ, вынесен из прозы purpose). Гейт без ответа —
    кандидат на снятие: так через год не заводится «Gate Garden».
  * `evidence` — {field, false_positives}. field ∈ proven|by_construction|human_by_nature|pending;
    false_positives — целое ТОЛЬКО при field: proven (наблюдение), иначе unavailable (честность как
    в usage_ledger: неизвестное = unavailable, никогда 0).

МЕХАНИЗМ РАТЧЕТА. НОВЫЙ blocking-гейт без непустого `prevents` краснеет; advisory-гейт обязан нести
и `evidence.field` (его «план» — статус поля: proven/by_construction/human_by_nature/pending). Поле
`field: proven` сверяется с `advisory_review.field_evidence: true` — два представления не вправе
разойтись молча. Границы (§26): структуризация уже принятых решений, поверхность гейтов НЕ растёт.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.gates.gate_executor import load_gates

PKG_ROOT = Path(__file__).resolve().parents[2]

VOCAB = {"proven", "by_construction", "human_by_nature", "pending"}

GATES = load_gates()
_DOC = yaml.safe_load((PKG_ROOT / "quality" / "gates.yaml").read_text(encoding="utf-8"))
DECISIONS = (_DOC.get("advisory_review") or {}).get("decisions") or {}


def audit(gates: dict, decisions: dict) -> list[str]:
    """Единая проверка: и живые тесты, и пробы прогоняют её. Возвращает список ошибок."""
    errs: list[str] = []
    for gid, g in gates.items():
        prevents = g.get("prevents")
        if not (isinstance(prevents, str) and prevents.strip()):
            kind = "blocking" if g.get("blocking") else "advisory"
            errs.append(f"{gid} ({kind}): пустой prevents — гейт не отвечает, что предотвращает")
        ev = g.get("evidence")
        if not isinstance(ev, dict):
            errs.append(f"{gid}: нет evidence {{field, false_positives}}")
            continue
        field = ev.get("field")
        if field not in VOCAB:
            errs.append(f"{gid}: evidence.field='{field}' вне словаря {sorted(VOCAB)}")
        fp = ev.get("false_positives")
        # честность: целое ТОЛЬКО при field: proven; иначе строго 'unavailable' (никогда 0)
        if isinstance(fp, bool) or not (isinstance(fp, int) or fp == "unavailable"):
            errs.append(f"{gid}: false_positives={fp!r} — целое (наблюдение) или 'unavailable'")
        elif isinstance(fp, int) and field != "proven":
            errs.append(f"{gid}: целое false_positives при field='{field}' — наблюдение бывает "
                        f"только у proven; неизвестное = unavailable, никогда 0")
    # синхронизация с прополкой #616: field: proven <-> field_evidence: true
    for gid, dec in decisions.items():
        if dec.get("decision") == "removed":
            continue
        if gid not in gates:
            errs.append(f"advisory_review называет '{gid}', которого нет в gates")
            continue
        proven = (gates[gid].get("evidence") or {}).get("field") == "proven"
        if bool(dec.get("field_evidence")) != proven:
            errs.append(f"{gid}: field_evidence={dec.get('field_evidence')} расходится с "
                        f"evidence.field (proven={proven})")
    return errs


@pytest.mark.contract
def test_the_registry_answers_what_each_gate_prevents():
    assert audit(GATES, DECISIONS) == [], "\n  - ".join([""] + audit(GATES, DECISIONS))


@pytest.mark.contract
def test_every_blocking_gate_names_a_defect_class():
    """Инвариант ревю: blocking-гейт без непустого prevents недопустим."""
    for gid, g in GATES.items():
        if g.get("blocking"):
            assert (g.get("prevents") or "").strip(), f"{gid}: blocking без prevents"


@pytest.mark.contract
def test_every_advisory_gate_carries_an_evidence_field():
    """Advisory без evidence.field = гейт без плана: краснеет как ратчет."""
    for gid, g in GATES.items():
        if not g.get("blocking"):
            assert (g.get("evidence") or {}).get("field") in VOCAB, f"{gid}: advisory без evidence.field"


@pytest.mark.contract
def test_false_positive_zero_is_never_fabricated():
    """0 ложных допустим только как наблюдение (field: proven), не как удобный дефолт."""
    for gid, g in GATES.items():
        ev = g.get("evidence") or {}
        if isinstance(ev.get("false_positives"), int):
            assert ev.get("field") == "proven", f"{gid}: число ложных без полевого evidence"


# ─── пробы: реестр обязан краснеть ──────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_a_blocking_gate_without_prevents_is_caught():
    g = copy.deepcopy(GATES)
    g["security"]["prevents"] = ""
    assert any("security" in e and "prevents" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_an_advisory_gate_without_evidence_field_is_caught():
    g = copy.deepcopy(GATES)
    g["release_safety"]["evidence"] = {"false_positives": "unavailable"}
    assert any("release_safety" in e and "field" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_a_fabricated_zero_false_positive_is_caught():
    g = copy.deepcopy(GATES)
    g["documentation_updated"]["evidence"] = {"field": "by_construction", "false_positives": 0}
    assert any("documentation_updated" in e and "false_positives" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_desync_with_advisory_review_is_caught():
    """Флип field_evidence без обновления гейта (или наоборот) — красное."""
    g = copy.deepcopy(GATES)
    g["contour_consistency"]["evidence"] = {"field": "pending", "false_positives": "unavailable"}
    assert any("contour_consistency" in e and "field_evidence" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_a_prevents_added_out_of_thin_air_for_a_missing_gate_is_caught():
    """advisory_review не вправе называть гейт, которого в реестре нет."""
    g = copy.deepcopy(GATES)
    dec = copy.deepcopy(DECISIONS)
    dec["ghost_gate"] = {"decision": "justified_advisory", "field_evidence": True}
    assert any("ghost_gate" in e for e in audit(g, dec))
