"""«Verified» — это УРОВЕНЬ ЗНАНИЯ, а не счёт зелёных галочек (P0 №5 продуктового ревью, #982).

«Проверено» обязано описывать, ЧТО МЫ ЗНАЕМ о работе: хребет НАЗВАННЫХ уровней знания, каждый с
честным состоянием (известно / ещё неизвестно / измерено-и-нет), — а не «8 из 8 гейтов». Это прямое
следствие инварианта ядра «no evidence → no claim»: недоказанное называется недоказанным, а не
замалчивается. В пару к #958 (что и КЕМ проверено) этот срез добавляет ГРАНИЦУ знания — что ещё
неизвестно (доехал ли деплой, идут ли события, взял ли продукт цель).

Тесты ПОВЕДЕНЧЕСКИЕ: смотрят на данные хребта и на человеко-обращённый свод, а не на реализацию.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.shared import gate_dimensions as gd

pytestmark = pytest.mark.unit

# Внутренние термины, которых человек на уровне product видеть не должен (расширение списка JARGON
# из tests/unit/test_ui_presenter.py — те же корни плюс счёт гейтов и id-имена уровней).
JARGON = ("write_scope", "tested_revision", "GateResult", "preflight_block", "ApprovalRecord",
          "gate:", "SHA", "implementation_verification", "code_review", "deploy_readiness",
          "analytics_runtime_verification", "evidence_verdict")


def _ev(deterministic=(), ai_judgment=(), human=()):
    return {"deterministic": list(deterministic),
            "ai_judgment": list(ai_judgment), "human": list(human)}


def test_verified_names_knowledge_levels_not_gate_counts():
    """Свод называет уровни знания продуктовыми словами; ни счёта «N из M», ни id гейтов, ни «гейт»."""
    lines = gd.knowledge_readout(_ev(
        deterministic=["implementation_verification", "regression_test_evidence"],
        ai_judgment=["code_review"]))
    body = "\n".join(lines)
    assert "Функция реализована." in body, body
    assert "Код проверен независимым ревьюером." in body, body
    assert "Критические сценарии прошли." in body, body
    # счёт гейтов и внутренние имена в лицо человеку не идут
    assert " из " not in body, body
    assert "гейт" not in body.lower(), body
    for token in ("implementation_verification", "code_review", "regression_test_evidence"):
        assert token not in body, body


def test_missing_source_is_named_not_yet_known_not_false_verified():
    """Инвариант «no evidence → no claim»: источника нет -> уровень честно «ещё неизвестно», не «проверено»."""
    # прошла только реализация; ревью/сценарии/деплой/события/outcome источника не имеют
    lines = gd.knowledge_readout(_ev(deterministic=["implementation_verification"]))
    body = "\n".join(lines)
    assert "Функция реализована." in body, body
    # непройденное НАЗЫВАЕТСЯ как неизвестное, а не выдаётся за проверенное
    assert "Что пока неизвестно:" in body, body
    assert "код ещё не смотрел независимый ревьюер" in body, body
    assert "развёртывание ещё не проверено" in body, body
    assert "продуктовый результат ещё не накоплен" in body, body
    # и ложного «проверено» для непройденных уровней нет
    assert "Код проверен независимым ревьюером." not in body, body
    assert "Развёртывание проверено." not in body, body


def test_no_source_at_all_claims_nothing_verified():
    """Ни одного пройденного источника -> ни одного «известно»; свод — только граница знания."""
    assert gd.knowledge_has_known(_ev()) is False
    lines = gd.knowledge_readout(_ev())
    body = "\n".join(lines)
    # ни одно достигнутое утверждение не появляется
    assert "Функция реализована." not in body, body
    # зато честно перечислено, что ещё неизвестно
    assert "Что пока неизвестно:" in body, body
    assert "реализация ещё не подтверждена" in body, body


def test_product_outcome_reflects_measurement_honestly():
    """Продуктовый результат: met -> известно, failed -> измерено-и-нет, без измерения -> ещё неизвестно."""
    # без измерения — ещё неизвестно
    assert "продуктовый результат ещё не накоплен" in "\n".join(gd.knowledge_readout(_ev()))
    # измерен и достигнут — названо достигнутым
    met = "\n".join(gd.knowledge_readout(_ev(), outcome_verdict="met"))
    assert "Продуктовый результат подтверждён измерением." in met, met
    # измерен и НЕ достигнут — это не «неизвестно» и не «достигнуто», а честное «цель не взята»
    failed = "\n".join(gd.knowledge_readout(_ev(), outcome_verdict="failed"))
    assert "цель пока не взята" in failed, failed
    assert "продуктовый результат ещё не накоплен" not in failed, failed


def test_passed_dimension_outside_spine_is_kept_and_attributed_to_source():
    """Пройденное вне хребта (безопасность, архитектура) не теряется и названо честным источником."""
    lines = gd.knowledge_readout(_ev(ai_judgment=["security", "architecture_review"]))
    body = "\n".join(lines)
    assert "Независимый ревьюер также принял:" in body, body
    assert "безопасность" in body and "архитектуру" in body, body
    # мнение независимого ревьюера машинной проверкой не зовётся
    assert "Машина также проверила" not in body, body


def test_opinion_is_not_passed_off_as_machine_check():
    """Уровень «Код проверен» атрибутирован независимому ревьюеру; реализация — машине, не наоборот."""
    body = "\n".join(gd.knowledge_readout(_ev(
        deterministic=["implementation_verification"], ai_judgment=["code_review"])))
    assert "Код проверен независимым ревьюером." in body, body
    # реализацию подтвердил детерминированный источник — она не приписана ревьюеру
    assert "Функция реализована." in body, body


def test_unknown_source_gate_does_not_invent_a_level():
    """Пройденный незнакомый гейт вне хребта смысл не выдумывает: его нет в дополнительной строке."""
    body = "\n".join(gd.knowledge_readout(_ev(deterministic=["some_brand_new_gate"])))
    assert "some_brand_new_gate" not in body, body
    # незнакомый гейт не порождает ложного «Машина также проверила: <выдуманное>»
    assert "Машина также проверила" not in body, body


def test_no_internal_jargon_reaches_product_face():
    """В свод уровней знания внутренние термины не просачиваются (переиспользуем JARGON)."""
    body = "\n".join(gd.knowledge_readout(_ev(
        deterministic=["implementation_verification", "deploy_readiness"],
        ai_judgment=["code_review", "security"], human=[]), outcome_verdict="failed"))
    for j in JARGON:
        assert j not in body, f"внутренний термин просочился на уровень product: {j}"


def test_levels_carry_honest_state_as_data():
    """Хребет уровней знания доступен ДАННЫМИ: у каждого уровня явное состояние, а не только текст."""
    levels = gd.knowledge_levels(_ev(deterministic=["implementation_verification"]),
                                 outcome_verdict="failed")
    by_key = {lv["key"]: lv for lv in levels}
    assert by_key["implemented"]["state"] == gd.LEVEL_KNOWN
    assert by_key["reviewed"]["state"] == gd.LEVEL_UNKNOWN
    assert by_key["product_outcome"]["state"] == gd.LEVEL_NOT_MET
    # все семь уровней присутствуют — граница знания полна, а не обрезана до пройденного
    assert len(levels) == len(gd.KNOWLEDGE_LEVELS) == 7
