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


# ── первый результат файлом (issue #1140: конец установки = результат, не «установлено») ──────────

def test_render_result_blocked_returns_none():
    # Дерево не прочиталось — результата НЕТ. Файла-обманки быть не должно: «установлено» за
    # «сделано» не выдаём.
    assert FH.render_result_markdown({"stage": FH.BLOCKED_UNDERSTANDING,
                                      "classification": "UNKNOWN"}) is None


def test_render_result_needs_answers_names_questions_without_yaml():
    md = FH.render_result_markdown({
        "stage": FH.NEEDS_ANSWERS, "classification": {"class": "EARLY_PRODUCT"},
        "blocking_questions": [{"id": "goal", "ask": "какова цель продукта?"}], "conflicts": []})
    assert md is not None
    assert "Первый результат" in md
    assert "goal" in md and "какова цель" in md
    # Ответы даются командой, а не ручной правкой YAML — иначе приёмка направления не выполнена.
    assert "--answer" in md and "--flow --apply" in md
    assert "YAML" in md


def test_render_result_ready_names_plan_and_first_work():
    md = FH.render_result_markdown({
        "stage": FH.READY, "classification": {"class": "EARLY_PRODUCT"},
        "bootstrap_applied": True,
        "bootstrap": {"work_items": 3, "written": [{"path": "planning/plan.yaml", "what": "план"}]},
        "next": {"next_best": {"id": "w1", "title": "навести порядок в тестах",
                               "why": ["самый дешёвый первый шаг"]}}})
    assert md is not None
    assert "навести порядок в тестах" in md
    assert "Работ в плане: 3" in md
    assert "planning/plan.yaml" in md
    assert "самый дешёвый первый шаг" in md
    assert "ai-ops next" in md


def test_write_result_writes_generated_file_and_returns_rel(tmp_path):
    rel = FH.write_result(tmp_path, {
        "stage": FH.READY, "classification": {"class": "EARLY_PRODUCT"},
        "bootstrap_applied": True, "bootstrap": {"work_items": 1, "written": []},
        "next": {"next_best": {"id": "w1", "title": "работа"}}})
    assert rel == FH.RESULT_REL
    written = (tmp_path / FH.RESULT_REL)
    assert written.is_file()
    body = written.read_text(encoding="utf-8")
    assert body.endswith("\n")
    assert "работа" in body


def test_write_result_skips_when_no_result(tmp_path):
    # blocked_understanding — файла быть не должно (fail-closed: нет результата — нет обещания).
    rel = FH.write_result(tmp_path, {"stage": FH.BLOCKED_UNDERSTANDING, "classification": "UNKNOWN"})
    assert rel is None
    assert not (tmp_path / FH.RESULT_REL).exists()


def test_applied_result_offers_dashboard_in_all_existing_outputs(tmp_path, monkeypatch):
    import ai_ops_kit.planning.product_bootstrap as boot
    import ai_ops_kit.planning.next_work as nw
    monkeypatch.setattr(boot, "plan", lambda *a, **k: {})
    monkeypatch.setattr(boot, "apply", lambda *a, **k: {"written": [], "work_items": 1})
    monkeypatch.setattr(nw, "compute", lambda *a, **k: {"plan_present": True, "next_best": {"id": "work"}})
    res = FH.run(tmp_path, apply=True, understanding=_und())
    assert res["dashboard_offer"]["request"] == "Создай пульт продукта"
    assert "пульт продукта" in " ".join(PF.from_first_hour(res)["next"])
    FH.write_result(tmp_path, res)
    assert "Создай пульт продукта" in (tmp_path / FH.RESULT_REL).read_text()
    assert not (tmp_path / "dashboard").exists()
    assert not (tmp_path / ".github/workflows/status-dashboard.yml").exists()


def test_preview_has_no_dashboard_offer(tmp_path, monkeypatch):
    import ai_ops_kit.planning.product_bootstrap as boot
    monkeypatch.setattr(boot, "plan", lambda *a, **k: {})
    res = FH.run(tmp_path, understanding=_und())
    assert not res.get("dashboard_offer")
    assert "Создай пульт продукта" not in FH.render_result_markdown(res)


def test_failed_apply_or_invalid_plan_has_no_dashboard_offer(tmp_path, monkeypatch):
    import ai_ops_kit.planning.product_bootstrap as boot
    import ai_ops_kit.planning.next_work as nw
    monkeypatch.setattr(boot, "plan", lambda *a, **k: {})
    monkeypatch.setattr(boot, "apply", lambda *a, **k: {"error": "cannot write"})
    assert not FH.run(tmp_path, apply=True, understanding=_und()).get("dashboard_offer")
    monkeypatch.setattr(boot, "apply", lambda *a, **k: {"written": []})
    monkeypatch.setattr(nw, "compute", lambda *a, **k: {"plan_errors": ["invalid"]})
    assert not FH.run(tmp_path, apply=True, understanding=_und()).get("dashboard_offer")


def test_real_bootstrap_and_repeat_do_not_create_or_overwrite_dashboard(tmp_path):
    from pathlib import Path
    import ai_ops_kit.planning.product_bootstrap as boot

    marker = tmp_path / "dashboard/index.html"
    marker.parent.mkdir()
    marker.write_text("existing product dashboard")
    boot.apply(tmp_path, understanding=_und())
    plan = tmp_path / "planning/plan.yaml"
    roadmap = tmp_path / "ROADMAP.md"
    plan.write_text(plan.read_text() + "\n# existing owner note\n")
    roadmap.write_text(roadmap.read_text() + "\n<!-- existing owner note -->\n")
    before = {p: p.read_bytes() for p in (plan, roadmap)}
    before_files = {p.relative_to(tmp_path): p.read_bytes()
                    for p in tmp_path.rglob("*") if p.is_file()}
    for _ in range(2):
        res = FH.run(tmp_path, apply=True, understanding=_und())
        assert res["next"]["plan_present"] is True
        assert not res["next"].get("plan_errors")
        assert res["dashboard_offer"]
        rel = FH.write_result(tmp_path, res)
        assert "Создай пульт продукта" in (tmp_path / rel).read_text()
        assert {p: p.read_bytes() for p in before} == before
        after_files = {p.relative_to(tmp_path): p.read_bytes()
                       for p in tmp_path.rglob("*") if p.is_file()}
        assert set(after_files) == set(before_files) | {Path(FH.RESULT_REL)}
        assert all(after_files[p] == data for p, data in before_files.items())
    assert marker.read_text() == "existing product dashboard"
    assert not (tmp_path / ".github").exists()


def test_unreadable_or_unanswered_first_hour_never_offers_dashboard(tmp_path):
    for und in (_und(cls="UNKNOWN"), _und(questions=[{"blocks_work": True}]),
                _und(conflicts=[{"category": "goal", "summary": "conflict"}])):
        res = FH.run(tmp_path, apply=True, understanding=und)
        assert not res.get("dashboard_offer")
        assert "Создай пульт продукта" not in (FH.render_result_markdown(res) or "")
    assert not (tmp_path / "planning").exists()


def test_real_model_cli_exposes_offer_in_json_file_and_rendered_output(tmp_path):
    import json
    import yaml
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "ai_ops_kit/cli/ai_ops_cli.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def cli(*extra):
        result = subprocess.run(
            [sys.executable, str(script), "model", str(tmp_path), "--flow", "--apply", *extra],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        return result.stdout

    (tmp_path / "README.md").write_text("# Bonus calculator\n\nCalculates employee bonuses.\n")
    (tmp_path / "main.py").write_text("def bonus(amount):\n    return amount * 0.1\n")
    answers = tmp_path / ".ai/project/onboarding-answers.yaml"
    answers.parent.mkdir(parents=True)
    answers.write_text(yaml.safe_dump({"answers": {
        "primary_user": "Finance analyst", "main_problem": "Avoid manual bonus spreadsheets",
        "key_scenarios": "Calculate a bonus and export a report",
        "main_goal_now": "Make bonus reports reliable",
        "next_outcome": "Analyst sees one correct bonus report",
        "forbidden_without_approval": "Delete data or publish externally",
        "protected_paths": "production/"}}))
    res = json.loads(cli("--json"))
    assert res["stage"] == "ready", res.get("blocking_questions")
    assert res["dashboard_offer"]["request"] == "Создай пульт продукта"
    assert "Создай пульт продукта" in (tmp_path / FH.RESULT_REL).read_text()
    assert "Создай пульт продукта" in cli()
    assert not (tmp_path / "dashboard").exists()
