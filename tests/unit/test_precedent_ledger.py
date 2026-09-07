"""Гранулярные тесты precedent_ledger (#586): обучение = реестр прецедентов с доказательствами.

Каждое поведение — отдельный именованный тест с настоящим assert. Ключевые инварианты:
запись несёт evidence + число случаев, НЕ утверждает причинность/переносимость, а на выборке 1 —
«прецедент, 1 случай», не «правило».
"""
from __future__ import annotations

from ai_ops_kit.intelligence import precedent_ledger as pl

# Поля, которых у прецедента быть НЕ ДОЛЖНО: они утверждали бы вывод/причину/перенос (инвариант 1).
_FORBIDDEN = {"causation", "cause", "transferable", "transfer", "rule", "recommendation", "law"}


def _obs(oid, cls="defect", state="became_work", child="bnbm"):
    return {"id": oid, "statement": f"наблюдение {oid}", "observation_class": cls,
            "state": state, "child": {"name": child}}


def test_precedent_carries_evidence_and_case_count():
    """Прецедент несёт список evidence и число случаев = длине evidence."""
    p = pl.make_precedent("паттерн", [{"statement": "a"}, {"statement": "b"}], ["ctx"], "src")
    assert p["case_count"] == 2
    assert len(p["evidence"]) == 2
    assert p["kind"] == "Precedent"


def test_precedent_has_no_causation_field():
    """Запись НЕ содержит поля причинности/переносимости/правила — только факты (инвариант 1)."""
    p = pl.make_precedent("паттерн", [{"statement": "a"}], ["ctx"], "src")
    assert not (_FORBIDDEN & set(p)), f"прецедент утверждает вывод: {_FORBIDDEN & set(p)}"


def test_single_case_is_precedent_not_rule():
    """На выборке 1 — метка single-case и текст «прецедент, 1 случай», а НЕ «правило» (инвариант 2)."""
    p = pl.make_precedent("паттерн", [{"statement": "a"}], ["ctx"], "src")
    assert p["confidence"] == "single-case"
    assert p["frequency_label"] == "прецедент, 1 случай"
    assert "правило" not in p["frequency_label"]


def test_confidence_is_frequency_not_certainty():
    """confidence считается ТОЛЬКО из числа случаев: 1→single, 2..4→few, ≥5→recurring."""
    assert pl.confidence_from_cases(1) == "single-case"
    assert pl.confidence_from_cases(3) == "few-cases"
    assert pl.confidence_from_cases(7) == "recurring"


def test_note_leaves_decision_to_human():
    """Дисклеймер прямым текстом: прецедент, не правило; решение за человеком (инвариант 3)."""
    p = pl.make_precedent("x", [{"statement": "a"}], [], "src")
    assert "не правило" in p["note"] and "за тобой" in p["note"]


def test_observations_group_by_pattern_with_contexts():
    """Наблюдения группируются по классу; case_count = число, contexts = различные дочки."""
    obs = [_obs("o1", child="bnbm"), _obs("o2", child="ii-sreda"), _obs("o3", child="bnbm")]
    ps = pl.precedents_from_observations(obs)
    assert len(ps) == 1
    p = ps[0]
    assert p["case_count"] == 3
    assert set(p["contexts"]) == {"bnbm", "ii-sreda"}
    assert not (_FORBIDDEN & set(p))


def test_from_insight_is_single_case():
    """Один измеренный релиз = один случай («прецедент, 1 случай»), без причинности."""
    insight = {"id": "insight-x", "outcome_id": "x", "verdict": "met",
               "headline": "«x»: цель достигнута",
               "epistemics": {"observed": ["метрика на замере 10"], "inferred": [], "unknown": []}}
    p = pl.precedent_from_insight(insight)
    assert p is not None
    assert p["case_count"] == 1 and p["confidence"] == "single-case"
    assert not (_FORBIDDEN & set(p))


def test_from_insight_none_without_verdict():
    """Нет инсайта/вердикта → прецедента нет (на unknown данных для прецедента ещё нет)."""
    assert pl.precedent_from_insight(None) is None
    assert pl.precedent_from_insight({"outcome_id": "x"}) is None
