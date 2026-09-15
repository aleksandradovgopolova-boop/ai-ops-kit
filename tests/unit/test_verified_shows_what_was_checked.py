"""«Проверено» показывает, ЧТО именно проверено — продуктовыми словами, а не счёт гейтов (#958).

Исход направления one-feature-end-to-end `verified_is_shown_as_trust_not_gate_list`: в момент
«Проверено» человек обязан видеть ОСНОВАНИЕ доверять (какие продуктовые измерения приняты), а не
число «гейты 3/3» и не плоское «замечаний нет». Ядро кита — «no false green»: называем ТОЛЬКО те
измерения, что реально прошли, и НЕ выдаём мнение независимого ревьюера за машинную проверку.

Тест ПОВЕДЕНЧЕСКИЙ: грузит `presenter_formatters` из файла (`spec_from_file_location`, не через
sys.path — во избежание загрязнения корня worktree) и смотрит на человеко-обращённый рендер.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
PF_PATH = KIT / "ai_ops_kit" / "ui" / "presenter_formatters.py"
PC_PATH = KIT / "ai_ops_kit" / "ui" / "presenter_core.py"

pytestmark = pytest.mark.unit


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PF = _load(PF_PATH, "pf_under_test")
PC = _load(PC_PATH, "pc_under_test")


def _ready_body(passed_gates):
    """Человеко-обращённый рендер ветки `ready` для набора ПРОЙДЕННЫХ ревьюируемых гейтов."""
    rep = {"verdict": "pass", "readiness": {"ready_for_merge": True, "reason": "ok"},
           "reviewable": list(passed_gates),
           "reviews": [{"gate": g, "status": "pass", "valid": True} for g in passed_gates],
           "changed_files": ["a.py", "b.py"]}
    msg = PF.from_review(rep)
    assert msg["status"] == "ok" and msg["headline"] == "Проверено"
    return msg, PC.render(msg, audience="product")


def test_verified_names_product_dimensions_not_gate_ids_or_counts():
    """Свод называет измерения продуктовыми словами; ни имён гейтов, ни «N из M»."""
    _msg, body = _ready_body(["code_review", "security", "architecture_review"])
    # продуктовые слова присутствуют
    for dim in ("код", "безопасность", "архитектур"):
        assert dim in body, body
    # внутренние имена гейтов НЕ просачиваются к человеку
    for gid in ("code_review", "security", "architecture_review"):
        assert gid not in body, body
    # счёт гейтов не показывается человеку
    assert " из " not in body, body
    assert "гейт" not in body.lower(), body
    assert "3/3" not in body and "3 из 3" not in body, body


def test_verified_does_not_name_a_dimension_that_was_not_checked():
    """Инвариант честности: называем ТОЛЬКО пройденные измерения, не выдумываем непроверенное."""
    # прошёл только code_review; security на ревью НЕ пройден (needs-changes) — но ready всё равно
    # выставлен извне: свод обязан назвать код и НЕ называть безопасность.
    rep = {"verdict": "pass", "readiness": {"ready_for_merge": True, "reason": "ok"},
           "reviewable": ["code_review", "security"],
           "reviews": [{"gate": "code_review", "status": "pass", "valid": True},
                       {"gate": "security", "status": "needs-changes", "valid": True}],
           "changed_files": ["a.py"]}
    body = PC.render(PF.from_review(rep), audience="product")
    assert "код" in body, body
    assert "безопасност" not in body, body


def test_verified_does_not_pass_opinion_off_as_machine_check():
    """Мнение независимого ревьюера (ai-review гейты) НЕ называется машинной/автоматической проверкой."""
    # ревьюируемые гейты закрывает независимый судья (writer≠judge), а не детерминированный валидатор
    _msg, body = _ready_body(["code_review", "security"])
    assert "независимый ревьюер" in body.lower(), body
    # честно: не «проверено машиной/автоматически», раз опоры-валидатора не было
    assert "проверено машиной" not in body, body
    assert "проверено автоматически" not in body, body


def test_verified_falls_back_neutral_for_unknown_gate_without_inventing_meaning():
    """Гейт без известной продуктовой фразы: не выдумываем смысл — нейтральный свод, но всё ещё «Проверено»."""
    # `code_quality` — не реальный id из quality/gates.yaml: продуктового имени нет.
    _msg, body = _ready_body(["code_quality"])
    assert "Независимая проверка пройдена" in body, body
    assert "code_quality" not in body, body
