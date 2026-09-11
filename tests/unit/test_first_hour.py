"""Оркестратор первого часа (#647): model→answers→bootstrap→next одним нарративом.

  * honest-stop — блокирующие вопросы ИЛИ противоречие источников => needs_answers, направление не
                  выдаётся за готовое; нечитаемое дерево => blocked_understanding;
  * ready       — ответов хватает => bootstrap (предпросмотр без apply) и next только после apply;
  * narrative   — presenter.from_first_hour даёт один связный ответ с честным статусом на каждой стадии.
"""
from __future__ import annotations

from ai_ops_kit.planning import first_hour as FH
from ai_ops_kit.ui import presenter_formatters as PF


def _und(cls="EARLY_PRODUCT", questions=None, conflicts=None):
    return {"schema_version": 1, "kind": "repository-understanding",
            "classification": {"class": cls, "confidence": "medium"},
            "ask": {"questions": questions or []}, "conflicts": conflicts or [],
            "reconstructed": {}, "audit": {"contours": [], "ready": [], "ai_can_build": [],
                                           "blocking_gaps": []}}


# ── honest stop ────────────────────────────────────────────────────────────────────────────────

def test_unreadable_tree_blocks(tmp_path):
    res = FH.run(tmp_path, understanding=_und(cls="UNKNOWN"))
    assert res["stage"] == FH.BLOCKED_UNDERSTANDING
    assert res["bootstrap"] is None and res["next"] is None


def test_blocking_questions_need_answers(tmp_path):
    und = _und(questions=[{"ask": "какова цель продукта?", "blocks_work": True},
                          {"ask": "мелочь", "blocks_work": False}])
    res = FH.run(tmp_path, understanding=und)
    assert res["stage"] == FH.NEEDS_ANSWERS
    assert len(res["blocking_questions"]) == 1
    assert res["bootstrap"] is None            # направление НЕ собрано, пока не отвечено


def test_source_conflict_needs_answers(tmp_path):
    und = _und(questions=[], conflicts=[{"category": "database", "state": "conflicting",
                                         "summary": "README vs ARCHITECTURE"}])
    res = FH.run(tmp_path, understanding=und)
    # Противоречие источников (#634) — тоже честная остановка: кит не выбирает сторону молча.
    assert res["stage"] == FH.NEEDS_ANSWERS


# ── ready ────────────────────────────────────────────────────────────────────────────────────

def test_ready_preview_does_not_write_or_recommend(tmp_path, monkeypatch):
    # Ответов хватает (нет блокеров/конфликтов). Без apply — предпросмотр: bootstrap.plan зовётся,
    # apply и next_work.compute — НЕТ (дисциплина записи: без явного apply кит не пишет).
    called = {"plan": False, "apply": False, "next": False}
    import ai_ops_kit.planning.product_bootstrap as _boot
    import ai_ops_kit.planning.next_work as _nw
    monkeypatch.setattr(_boot, "plan", lambda root, und=None, model=None: called.__setitem__("plan", True) or {"will_write": [], "work_items": []})
    monkeypatch.setattr(_boot, "apply", lambda *a, **k: called.__setitem__("apply", True) or {})
    monkeypatch.setattr(_nw, "compute", lambda *a, **k: called.__setitem__("next", True) or {})
    res = FH.run(tmp_path, understanding=_und(), apply=False)
    assert res["stage"] == FH.READY
    assert called["plan"] and not called["apply"] and not called["next"]
    assert res["bootstrap_applied"] is False and res["next"] is None


def test_ready_apply_writes_and_recommends(tmp_path, monkeypatch):
    import ai_ops_kit.planning.product_bootstrap as _boot
    import ai_ops_kit.planning.next_work as _nw
    monkeypatch.setattr(_boot, "plan", lambda root, und=None, model=None: {"will_write": [], "work_items": [1, 2]})
    monkeypatch.setattr(_boot, "apply", lambda *a, **k: {"error": None, "work_items": 2, "written": [{"path": "planning/plan.yaml"}]})
    monkeypatch.setattr(_nw, "compute", lambda *a, **k: {"next_best": {"id": "w1", "title": "первая работа"}})
    res = FH.run(tmp_path, understanding=_und(), apply=True)
    assert res["stage"] == FH.READY and res["bootstrap_applied"] is True
    assert res["next"]["next_best"]["id"] == "w1"


# ── narrative (presenter) ──────────────────────────────────────────────────────────────────────

def test_narrative_needs_answers_asks():
    msg = PF.from_first_hour({"stage": FH.NEEDS_ANSWERS, "classification": "EARLY_PRODUCT",
                              "blocking_questions": [{"ask": "цель?"}], "conflicts": []})
    assert msg["status"] == "needs_input"
    steps = " ".join(msg["next"])
    assert "--answer" in steps and "--flow --apply" in steps


def test_narrative_ready_applied_names_first_work():
    msg = PF.from_first_hour({"stage": FH.READY, "classification": "EARLY_PRODUCT",
                              "bootstrap_applied": True, "bootstrap": {"work_items": 2},
                              "next": {"next_best": {"id": "w1", "title": "первая работа"}}})
    assert msg["status"] == "ok"
    assert "первая работа" in msg["summary"]


def test_narrative_ready_preview_offers_apply():
    msg = PF.from_first_hour({"stage": FH.READY, "classification": "EARLY_PRODUCT",
                              "bootstrap_applied": False,
                              "bootstrap": {"will_write": [{"path": "ROADMAP.md", "will_write": True}],
                                            "work_items": []}})
    assert msg["status"] == "ok"
    assert "--flow --apply" in " ".join(msg["next"])


def test_narrative_blocked_understanding_degraded():
    msg = PF.from_first_hour({"stage": FH.BLOCKED_UNDERSTANDING, "classification": "UNKNOWN"})
    assert msg["status"] == "degraded"
