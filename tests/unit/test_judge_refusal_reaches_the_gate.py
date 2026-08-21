"""Отказ судьи доезжает до гейта своими словами — сквозной путь (C2, v3.37).

Отдельные звенья проверены в `test_response_contract_selftest.py`. Здесь — то, ради чего они
существуют: прогон workflow, в котором провайдер отказал, и человек читает ПРИЧИНУ, а не «нет
заключения reviewer». Между звеньями и результатом стоит `run_workflow`, и без этой пробы правка
могла бы быть верной в каждом файле и не работать вместе.

Берётся RESEARCH: у него один judge-стадия (`fact-check`) и блокирующий судейский гейт `evidence` —
самая короткая цепочка, на которой утверждение вообще проверяемо.
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.providers import orchestrator
from ai_ops_kit.providers.response_contract import ProviderRefusal

WF = "RESEARCH"
JUDGE_STAGE = "fact-check"
JUDGE_GATE = "evidence"


def _run(child_root, judge_fn, mode="enforced", monkeypatch=None):
    """Прогон с подменённым `for_contract`: связывание с контрактом проверено отдельно, здесь
    проверяется обработка того, что связанный провайдер вернул (или чем отказал)."""
    monkeypatch.setattr(orchestrator, "for_contract",
                        lambda _p, _c: (judge_fn, {"mode": mode, "mechanism": "проба"}))
    return orchestrator.run_workflow(
        workflow_id=WF, task_text="проверить утверждение", child_root=child_root,
        provider=orchestrator.mock_provider, verbose=False, fresh=True, collect=True)


def _gate(run_dir, gate_id):
    report = json.loads((run_dir / "GateReport.json").read_text(encoding="utf-8"))
    return next(r for r in report["gate_results"] if r["gate"] == gate_id)


@pytest.mark.unit
def test_refusal_is_recorded_next_to_the_stage_and_names_the_cause(child_root, monkeypatch):
    def refuses(_prompt):
        raise ProviderRefusal("truncated", "потолок 8192 токенов", "anthropic", "claude-opus-5")

    state, run_dir = _run(child_root, refuses, monkeypatch=monkeypatch)

    rec = json.loads((run_dir / f"stage-{JUDGE_STAGE}.refusal.json").read_text(encoding="utf-8"))
    assert rec["kind"] == "provider-refusal" and rec["reason"] == "truncated"
    assert rec["provider"] == "anthropic"

    art = (run_dir / f"stage-{JUDGE_STAGE}.md").read_text(encoding="utf-8")
    assert "Заключения нет" in art and "обрезан" in art
    assert not (run_dir / f"stage-{JUDGE_STAGE}.reviewer.json").exists(), \
        "после отказа разбирать нечего — вердикта не существует"


@pytest.mark.unit
def test_the_gate_stays_closed_and_says_what_actually_happened(child_root, monkeypatch):
    def refuses(_prompt):
        raise ProviderRefusal("truncated", "потолок 8192 токенов", "anthropic", "claude-opus-5")

    state, run_dir = _run(child_root, refuses, monkeypatch=monkeypatch)

    assert state["status"] == "blocked"
    g = _gate(run_dir, JUDGE_GATE)
    assert g["status"] == "fail" and g["blocking"] is True
    said = " ".join(g["blockers"])
    assert "обрезан" in said, said
    assert "нет заключения reviewer" not in said, "старая формулировка врала о причине"


@pytest.mark.unit
def test_the_shape_mode_is_written_down_not_assumed(child_root, monkeypatch):
    """«Чем обеспечена форма» — факт прогона, и он записан, а не выводится читателем по имени."""
    def refuses(_prompt):
        raise ProviderRefusal("empty_answer", "", "anthropic", "claude-opus-5")

    state, _ = _run(child_root, refuses, monkeypatch=monkeypatch)
    shape = state["verdict_shape"][JUDGE_STAGE]
    assert shape["mode"] == "enforced" and shape["mechanism"] == "проба"
    assert shape["refusal"]["reason"] == "empty_answer"


@pytest.mark.unit
def test_a_normal_verdict_still_closes_the_gate(child_root, monkeypatch):
    """Обратная сторона: путь не сломан — валидный ответ по-прежнему закрывает гейт."""
    verdict = json.dumps({"schema_version": 1, "kind": "reviewer-result", "gate": JUDGE_GATE,
                          "status": "pass", "summary": "источники на месте",
                          "checks": [{"id": "source_per_claim", "status": "pass"}],
                          "blockers": []}, ensure_ascii=False)
    state, run_dir = _run(child_root, lambda _p: verdict, monkeypatch=monkeypatch)

    assert (run_dir / f"stage-{JUDGE_STAGE}.reviewer.json").exists()
    assert not (run_dir / f"stage-{JUDGE_STAGE}.refusal.json").exists()
    assert _gate(run_dir, JUDGE_GATE)["status"] == "pass"
    assert state["verdict_shape"][JUDGE_STAGE]["mode"] == "enforced"


@pytest.mark.unit
def test_where_the_mechanism_is_absent_the_run_says_so_and_still_works(child_root, monkeypatch):
    """`claude-cli` и подобные: форма не обеспечена, вердикт разбирается из прозы — и это записано."""
    verdict = ("## Заключение\n\nИсточники на месте.\n\n"
               + json.dumps({"schema_version": 1, "kind": "reviewer-result", "gate": JUDGE_GATE,
                             "status": "pass", "checks": [{"id": "source_per_claim",
                                                           "status": "pass"}],
                             "blockers": []}, ensure_ascii=False))
    state, run_dir = _run(child_root, lambda _p: verdict, mode="unsupported",
                          monkeypatch=monkeypatch)
    assert state["verdict_shape"][JUDGE_STAGE]["mode"] == "unsupported"
    assert _gate(run_dir, JUDGE_GATE)["status"] == "pass", "путь без механизма обязан работать"
