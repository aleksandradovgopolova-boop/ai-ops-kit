"""no-verdict в ДЕГРАДИРОВАВШЕЙ среде называется «среда», а не «код плохой» (issue #603).

ПОВОД — живой прогон (07.09, #577/#591): в глубоко-over_budget сессии независимый судья
(`claude -p`) ОТВЕЧАЕТ, но не заключает вердикт (reads=0, без refusal). Раньше evidence падал в
generic-ветку «судья не вернул reviewer-result», и владелец читал это как «мой код плохой». Надо
ОТДЕЛИТЬ условие среды (сессия деградировала — повтори в чистой) от «код плохой» и от «прочитал,
но не заключил».

Инвариант, который эти пробы стерегут: degraded ТОЛЬКО переименовывает причину no-verdict и
ставит needs_human=False — он НЕ превращает fail в pass и НЕ закрывает гейт (0 false-green).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.gates import gate_executor


BLOCKING = {"blocking": True}
ADVISORY = {"blocking": False}


def _said(ev):
    return " ".join((ev.get("blockers") or []) + (ev.get("warnings") or []))


def _evidence(ev):
    return " ".join(ev.get("evidence") or [])


# --- 1. degraded НАЗЫВАЕТ причину средой -------------------------------------

@pytest.mark.unit
def test_degraded_no_verdict_named_environment_not_code():
    """session_degraded=True при no-verdict/reads=0/без refusal -> причина названа СРЕДОЙ
    (reviewer-environment-degraded), needs_human=False, но гейт всё ещё НЕ закрыт (fail)."""
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="no-verdict",
        errors=["ревьюер не вынес вердикт"], session_degraded=True)
    said = _said(ev)
    assert "reviewer-environment-degraded" in said or "reviewer-environment-degraded" in _evidence(ev)
    assert "СРЕДА" in said or "среда" in said
    assert "чистой сессии" in said                 # человеку сказано, ЧТО делать
    # чинится чистой сессией, а не решением человека (как budget-ветка):
    assert not ev.get("pending_human")
    # ★АНТИ-ЛОЖНО-ЗЕЛЁНОЕ★: причина переименована, но гейт НЕ закрыт и НЕ pass:
    assert ev["status"] == "fail"
    assert ev.get("blockers"), "блокирующий гейт обязан нести блокер — degraded его не снимает"


@pytest.mark.unit
def test_degraded_keeps_reviewer_verdict_marker():
    """`_hard_stop` распознаёт reviewer-blocked по подстроке 'reviewer verdict' в evidence —
    degraded не должен ломать это распознавание."""
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="no-verdict",
        errors=["x"], session_degraded=True)
    assert any("reviewer verdict" in e for e in ev.get("evidence", []))


# --- 2. КОНТРАСТ: не-degraded остаётся generic --------------------------------

@pytest.mark.unit
def test_not_degraded_stays_generic_no_verdict():
    """Тот же вызов с session_degraded=False -> generic-ветка «не вернул reviewer-result»,
    БЕЗ ярлыка среды. Ровно этот контраст доказывает, что средой названо ТОЛЬКО деградировавшее."""
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="no-verdict",
        errors=["ревьюер не вынес вердикт"], session_degraded=False)
    said = _said(ev) + " " + _evidence(ev)
    assert "reviewer-environment-degraded" not in said
    assert "не вернул разбираемого reviewer-result" in _said(ev)
    assert ev.get("pending_human") is True         # generic no-verdict зовёт человека


@pytest.mark.unit
def test_default_is_not_degraded():
    """Умолчание session_degraded=False: старое поведение НЕ меняется без явного сигнала."""
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="no-verdict", errors=["x"])
    assert "reviewer-environment-degraded" not in (_said(ev) + " " + _evidence(ev))


# --- 3. Приоритет веток -------------------------------------------------------

@pytest.mark.unit
def test_refusal_overrides_degraded():
    """refusal ПЕРЕКРЫВАЕТ degraded: провайдер назвал причину (пусто/отказ) — она первична,
    идём в refusal-ветку, а не в environment-degraded."""
    refusal = {"kind": "provider-refusal", "reason": "empty_answer",
               "reason_text": "модель вернула пустой ответ", "provider": "claude-cli"}
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="refusal: empty_answer",
        refusal=refusal, session_degraded=True)
    said = _said(ev) + " " + _evidence(ev)
    assert "пустой" in _said(ev)                    # refusal-ветка (по reason_text)
    assert "reviewer-environment-degraded" not in said, "degraded не должен красть refusal"


@pytest.mark.unit
def test_run_budget_not_confused_with_session_degraded():
    """RUN-бюджет вызовов (stopped=budget:...) при session_degraded=False -> budget-ветка,
    НЕ environment-degraded: это разные причины, их нельзя путать."""
    ev = gate_executor.evidence_from_no_verdict(
        BLOCKING, gate_id="code_review", stopped="budget: max_model_calls",
        session_degraded=False)
    assert "бюджет" in _said(ev)
    assert "reviewer-environment-degraded" not in (_said(ev) + " " + _evidence(ev))
    assert not ev.get("pending_human")


# --- 4. Advisory-гейт: degraded warn'ит, но тоже не закрывает ------------------

@pytest.mark.unit
def test_advisory_degraded_warns_not_fails_but_still_unmet():
    """Advisory-гейт при degraded -> warn (не fail), но по-прежнему НЕ закрыт (несёт warning)."""
    ev = gate_executor.evidence_from_no_verdict(
        ADVISORY, gate_id="ux_review", stopped="no-verdict",
        errors=["x"], session_degraded=True)
    assert ev["status"] == "warn"
    assert ev.get("warnings")
    assert "reviewer-environment-degraded" in _said(ev) or \
           "reviewer-environment-degraded" in _evidence(ev)


# --- 5. FLOW: проброс через signals в _run_reviews ----------------------------

def _init_git(root: Path):
    subprocess.run(["git", "init"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)


_ENG = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}


def _run_eng(child_root, reviewer, feature, signals):
    from ai_ops_kit.engine import execution_pipeline
    ops = iter([{"op": "write", "path": f"src/{feature}.py", "content": "def g():\n    return 1\n"},
                {"done": True}])
    return execution_pipeline.run_pipeline(
        task="engineering task", signals=signals, child_root=child_root,
        proposer=lambda ctx: next(ops), budget={"max_model_calls": 30}, feature=feature,
        commit=True, isolate=True, install_deps=False, review=True, reviewer_proposer=reviewer)


def _cr(report):
    return next((r for r in (report.get("reviews") or []) if r["gate"] == "code_review"), None)


def _prose(_p):
    # проза без JSON -> parse_action не разбирает -> no-verdict, reads=0, без refusal
    return "Пока не могу заключить по этому диффу."


@pytest.mark.unit
def test_flow_over_budget_signal_names_environment(child_root):
    """★FLOW★ signals[session_spend_state]=over_budget + судья-проза (no-verdict) -> gate_ev/entry
    несёт reviewer-environment-degraded. Проброс cli -> signals -> _run_reviews -> evidence живой.
    ★АНТИ-ЛОЖНО-ЗЕЛЁНОЕ★: гейт code_review по-прежнему НЕ закрыт (в unmet)."""
    _init_git(child_root)
    report = _run_eng(child_root, _prose, "deg_on",
                      {**_ENG, "session_spend_state": "over_budget"})
    e = _cr(report)
    assert e is not None and e.get("closed_as") == "refused", report.get("reviews")
    assert "reviewer-environment-degraded" in (e.get("reason") or ""), e
    assert "code_review" in report["gates"]["unmet"], "degraded НЕ закрывает гейт (false-green)"


@pytest.mark.unit
def test_flow_without_signal_stays_generic(child_root):
    """★FLOW-КОНТРАСТ★ те же прогон и судья, но БЕЗ session_spend_state -> generic no-verdict,
    без ярлыка среды. Доказывает, что средой названо ТОЛЬКО при явном сигнале в signals."""
    _init_git(child_root)
    report = _run_eng(child_root, _prose, "deg_off", dict(_ENG))
    e = _cr(report)
    assert e is not None and e.get("closed_as") == "refused", report.get("reviews")
    assert "reviewer-environment-degraded" not in (e.get("reason") or ""), e
    assert "code_review" in report["gates"]["unmet"]
