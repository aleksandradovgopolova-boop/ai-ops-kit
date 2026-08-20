"""Кто закрывает гейт — объявлено в реестре и совпадает с тем, как гейт исполняется.

ПОВОД — ЗАМЕР. Из 35 гейтов 19 не имеют исполняемого валидатора: их закрывает заключение
LLM-судьи или решение человека. В отчёте прогона все гейты выглядели одинаково, и «пройден» от
детерминированной проверки было неотличимо от «пройден» по чьему-то мнению. Слово «зелёный» без
имени того, кто его поставил, стоит ровно столько, сколько стоит самый слабый способ его получить.

ЧЕТЫРЕ ЗНАЧЕНИЯ, А НЕ ТРИ. Гейт с `review_mode: writer` и без валидатора подтверждает САМ СЕБЯ.
Назвать это `judge` значило бы напечатать в отчёте утверждение, против которого стоит инвариант
«writer ≠ judge», — поэтому у самозаявления своё имя.

Три обязательных теста на capability (AGENTS.md):
  * positive     — у каждого гейта есть `closed_by`, и он совпадает с выводом из кода;
  * fail-closed  — разъехавшееся объявление и незнакомое значение краснеют;
  * side-effect  — разбивка доходит до отчёта прогона и до поставляемого документа.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.gates import gate_executor as ge

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]
GATES = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
DELIVERED_DOC = PKG / "rules" / "quality" / "gate-closure-map.md"


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_every_gate_declares_who_closes_it():
    missing = sorted(gid for gid, g in GATES.items() if not g.get("closed_by"))
    assert not missing, f"гейты без `closed_by`: {missing} — дочка не узнает, машина это или мнение"


def test_declared_value_matches_how_the_gate_is_actually_executed():
    """Реестр несёт значение ДЛЯ ДОЧКИ (она читает реестр, а не код), но правду говорит код.

    Второе объявление рядом с первым разошлось бы на первой же правке — этот класс дефектов кит
    ловит у себя же, поэтому здесь он ловится тоже.
    """
    drift = {gid: (g["closed_by"], ge.closed_by(g))
             for gid, g in GATES.items() if g["closed_by"] != ge.closed_by(g)}
    assert not drift, (
        f"объявленное разошлось с исполняемым: {drift}. Правьте объявление, а не тест — "
        f"значение выводится из `gate_executor.classify`")


def test_the_measurement_is_what_the_delivered_document_says():
    """Документ едет в дочку и называет числа. Число, которое перестало быть правдой, хуже отсутствия."""
    counts = ge.closure_breakdown(GATES)["counts"]
    text = DELIVERED_DOC.read_text(encoding="utf-8")
    claim = (f"**Итого: {counts['validator']} машиной, {counts['judge']} судьёй, "
             f"{counts['writer']} писателем, {counts['human']} человеком**")
    assert claim in text, (
        f"документ поставки называет не тот замер — ожидалось «{claim}». Обновите его вместе с "
        f"реестром: цитата в документе стареет молча")


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_an_unknown_value_is_refused():
    unknown = sorted(gid for gid, g in GATES.items()
                     if g["closed_by"] not in ge.CLOSED_BY_VALUES)
    assert not unknown, (
        f"незнакомое значение `closed_by` у {unknown} (допустимы {list(ge.CLOSED_BY_VALUES)})")


def test_a_gate_with_a_validator_is_never_called_an_opinion():
    """Обратная половина: машинная проверка не должна оказаться записанной как мнение — иначе
    отчёт занижал бы силу того, что действительно проверено."""
    wrong = sorted(gid for gid, g in GATES.items()
                   if g.get("validator") and g["closed_by"] != "validator"
                   and g.get("human_approval") is not True)
    assert not wrong, wrong


def test_a_gate_without_a_validator_is_never_called_machine_checked():
    """Главная ложь, которую этот механизм закрывает: мнение, названное машинной проверкой."""
    wrong = sorted(gid for gid, g in GATES.items()
                   if not g.get("validator") and g["closed_by"] == "validator")
    assert not wrong, (
        f"гейты без валидатора объявлены проверенными машиной: {wrong} — именно это утверждение "
        f"и учит доверять зелёному вслепую")


def test_writer_closed_gates_are_named_and_do_not_grow_silently():
    """Самозаявление — слабейшая форма закрытия, и её список обязан быть виден, а не выведен.

    Ратчет: новый гейт, закрывающий сам себя, краснеет и требует решения — валидатор, судья или
    осознанное согласие на самозаявление.
    """
    writer_closed = sorted(gid for gid, g in GATES.items() if g["closed_by"] == "writer")
    # 2026-08-20 (C3): список СОКРАТИЛСЯ — `documentation_updated` переведён в машинный
    # (`ai_ops_kit/gates/documentation_evidence.py`), потому что оба его доказательства оказались
    # фактами о дифе, а не суждением. Ратчет ходит вниз: сюда можно только убавлять.
    assert writer_closed == ["documentation_drift"], (
        f"список самозаявляющихся гейтов изменился: {writer_closed}. Если гейт добавлен осознанно "
        f"— обновите этот замер и rules/quality/gate-closure-map.md вместе с ним; если убавился — "
        f"это ратчет вниз, и он приветствуется")


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_the_breakdown_reaches_the_run_report():
    """Разбивка обязана дойти до отчёта прогона: сведения, не покинувшие модуль, до человека не доходят."""
    rep = ge.evaluate("ENGINEERING")
    cl = rep.get("closure")
    assert cl, "в результате оценки гейтов нет разбивки closure"
    assert set(cl["counts"]) == set(ge.CLOSED_BY_VALUES)
    assert sum(cl["counts"].values()) == len(rep["evaluated_gates"])
    assert set(cl["by_gate"]) == set(rep["evaluated_gates"])
    assert set(cl["machine_checked"]) | set(cl["judged_or_human"]) == set(rep["evaluated_gates"])
    assert not (set(cl["machine_checked"]) & set(cl["judged_or_human"])), "гейт и машина, и мнение"


def test_the_pipeline_puts_the_breakdown_into_run_report_json():
    """ШОВ: разбивка попадает в `gates` отчёта прогона, а не остаётся внутри исполнителя гейтов."""
    src = (PKG / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")
    assert '"closure": gates.get("closure"),' in src, (
        "отчёт прогона больше не несёт разбивку — дочка снова видит все гейты одинаковыми")
    assert 'проверено машиной' in src, "человеку разбивку не печатают"


def test_a_conditional_human_approval_escalates_only_on_its_signal():
    """side-effect: `security` — судья по умолчанию и человек по сигналу. Постоянный `human`
    блокировал бы каждую задачу, постоянный `judge` скрывал бы эскалацию."""
    gate = GATES["security"]
    assert ge.closed_by(gate, {}) == "judge"
    assert ge.closed_by(gate, {"destructive": True}) == "human"


def test_the_delivered_document_rides_to_the_child():
    """Документ обязан быть в поставке: объяснение, оставшееся в репозитории кита, дочка не увидит."""
    manifest = yaml.safe_load((PKG / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))
    patterns = manifest["update_policy"]["managed_set"]
    rel = DELIVERED_DOC.relative_to(PKG).as_posix()
    assert DELIVERED_DOC.is_file(), f"нет {rel}"
    assert any(Path(rel).match(p) for p in patterns), (
        f"{rel} не попадает ни под один шаблон поставки {patterns} — документ останется в ките")
