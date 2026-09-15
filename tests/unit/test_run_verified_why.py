"""Итог ПРОГОНА показывает «что проверено» продуктовыми словами, а не счёт гейтов (#958).

Исход направления one-feature-end-to-end `verified_is_shown_as_trust_not_gate_list`, путь ПРОГОНА
(в пару к #965, закрывшему путь `review`): на run-пути человек больше не видит «проверено машиной X
из Y; остальное — мнение: <id>», а видит ОСНОВАНИЕ доверять — какие продуктовые измерения приняты
и КЕМ (детерминированная машина vs независимый ревьюер). Ядро — «no false green»: называем ТОЛЬКО
реально пройденные измерения и НЕ выдаём мнение за машинную проверку.

Свод собирает `shared.gate_dimensions.run_verified_lines` (общий нижний слой: ту же карту читают и
`ui.from_review`, и `engine.pipeline_stages`). Тесты — поведенческие: смотрят на строки свода.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.shared import gate_dimensions as gd

pytestmark = pytest.mark.unit


def test_machine_line_names_product_dimensions_not_ids_or_counts():
    """Пройденные машинные гейты названы продуктовыми словами; без id и без «N из M»."""
    lines = gd.run_verified_lines(
        {"deterministic": ["implementation_verification", "requirements"],
         "ai_judgment": [], "human": []})
    body = "\n".join(lines)
    assert "машина проверила" in body, body
    assert "реализацию: тесты и сборку" in body and "требования" in body, body
    # внутренние id гейтов и счёт «N из M» в лицо человеку не идут
    for gid in ("implementation_verification", "requirements"):
        assert gid not in body, body
    assert " из " not in body, body


def test_opinion_is_not_passed_off_as_machine_check():
    """Заключение независимого ревьюера (ai-review) названо мнением, не машинной проверкой."""
    lines = gd.run_verified_lines(
        {"deterministic": [], "ai_judgment": ["code_review", "architecture_review"], "human": []})
    body = "\n".join(lines)
    assert "независимый ревьюер" in body.lower(), body
    assert "код" in body and "архитектуру" in body, body
    assert "машина проверила" not in body, body  # мнение ≠ машина


def test_machine_and_opinion_are_told_apart_honestly():
    """Обе группы присутствуют и РАЗЛИЧЕНЫ: машинное отдельно, мнение отдельно."""
    lines = gd.run_verified_lines(
        {"deterministic": ["documentation_updated"],
         "ai_judgment": ["code_review"], "human": []})
    assert len(lines) == 2, lines
    machine = next(x for x in lines if x.startswith("машина"))
    opinion = next(x for x in lines if "ревьюер" in x)
    assert "обновление документации" in machine
    assert "код" in opinion and "код" not in machine


def test_unpassed_dimension_is_never_named():
    """Инвариант честности: непройденный гейт не попадает в свод (его нет в evidence_verdict)."""
    # security НЕ пройден -> его нет ни в одном списке источников -> «безопасность» не называется
    lines = gd.run_verified_lines(
        {"deterministic": ["requirements"], "ai_judgment": ["code_review"], "human": []})
    body = "\n".join(lines)
    assert "безопасност" not in body, body


def test_no_passed_gates_means_no_verified_claim():
    """Пройденных гейтов нет -> пустой свод: вызывающий НЕ вправе писать «Проверено»."""
    assert gd.run_verified_lines({"deterministic": [], "ai_judgment": [], "human": []}) == []
    assert gd.run_verified_lines({}) == []


def test_unknown_passed_gate_does_not_invent_meaning():
    """Пройденный гейт без продуктовой фразы: группа названа нейтрально, id не течёт, смысл не выдуман."""
    lines = gd.run_verified_lines(
        {"deterministic": ["some_new_validator_gate"], "ai_judgment": [], "human": []})
    body = "\n".join(lines)
    assert "машина проверила" in body, body
    assert "детерминированные проверки пройдены" in body, body
    assert "some_new_validator_gate" not in body, body


def test_pipeline_stages_renders_the_summary_on_the_run_path():
    """ШОВ: путь прогона печатает «Проверено» УРОВНЯМИ ЗНАНИЯ (P0 №5, #982), а не счёт гейтов.

    #958 закрыл «N/M гейтов» продуктовыми словами; P0 №5 поднял свод до уровня знания —
    run-путь зовёт `shared.gate_dimensions.knowledge_readout`, а не плоский `run_verified_lines`.
    """
    from pathlib import Path
    pkg = Path(__file__).resolve().parents[2]
    src = (pkg / "ai_ops_kit" / "engine" / "pipeline_stages.py").read_text(encoding="utf-8")
    assert "knowledge_readout" in src
    assert "Проверено — вот что уже известно о работе:" in src
    assert "проверено машиной" not in src, "старый счёт в лицо человеку вернулся"
