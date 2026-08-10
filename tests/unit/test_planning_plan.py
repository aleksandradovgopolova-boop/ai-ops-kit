"""Delivery plan: разбор, семантика, вывод статуса (v3.35 Product Operating Model).

Три теста на capability — positive, fail-closed, side-effect proof:
  * positive     — валидный план разбирается, статусы выводятся из графа;
  * fail-closed  — битый/пустой/циклический план НЕ выглядит как «работы нет»;
  * side-effect  — факт из WorkItem и реестра активных работ ПЕРЕБИВАЕТ объявленный статус.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import delivery_plan as P

MODEL = C.load_model()


def _write(root: Path, work, goals=None):
    data = {"schema_version": 1, "kind": "delivery-plan",
            "goals": goals or [{"id": "g1", "status": "active",
                                "outcome": {"user_can_do_it": False}}],
            "work": work}
    (root / "planning").mkdir(parents=True, exist_ok=True)
    (root / "planning" / "plan.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def _item(wid, **kw):
    base = {"id": wid, "title": f"работа {wid}", "type": "engineering", "goal": "g1",
            "status": "todo", "owner_role": "engineer", "depends_on": [],
            "write_scope": [f"src/{wid.lower()}/"]}
    base.update(kw)
    return base


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_valid_plan_parses_and_derives_status(tmp_path):
    _write(tmp_path, [_item("A", type="architecture", owner_role="architect"),
                      _item("B", depends_on=["A"])])
    pl = P.load(tmp_path)
    rep = P.validate(pl, MODEL)
    assert rep["errors"] == [], rep["errors"]
    res = P.resolve(pl, tmp_path, MODEL)
    assert res["A"]["status"] == "ready"
    assert res["B"]["status"] == "blocked"
    assert "A" in res["B"]["blocked_by"]
    # Причина названа словами, а не подразумевается: пустой список причин = молчаливый вывод.
    assert res["B"]["reasons"]


def test_derived_status_is_order_independent(tmp_path):
    """Перестановка строк в файле не меняет ответ: обход топологический, а не по порядку строк."""
    forward = [_item("A"), _item("B", depends_on=["A"]), _item("C", depends_on=["B"])]
    _write(tmp_path, forward)
    a = {k: v["status"] for k, v in P.resolve(P.load(tmp_path), tmp_path, MODEL).items()}
    _write(tmp_path, list(reversed(forward)))
    b = {k: v["status"] for k, v in P.resolve(P.load(tmp_path), tmp_path, MODEL).items()}
    assert a == b


def test_unblocks_counts_transitive_downstream(tmp_path):
    _write(tmp_path, [_item("A"), _item("B", depends_on=["A"]), _item("C", depends_on=["B"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["A"]["unblocks"] == 2      # B и C, а не только прямой потомок
    assert res["C"]["unblocks"] == 0


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_missing_plan_is_none_not_empty(tmp_path):
    """Отсутствие плана и пустой план — РАЗНЫЕ ответы; None означает «контур не заполнен»."""
    assert P.load(tmp_path) is None


def test_empty_file_raises_not_returns_empty(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text("", encoding="utf-8")
    with pytest.raises(P.PlanCorrupt):
        P.load(tmp_path)


def test_broken_yaml_raises(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text("work: [\n  - id: A\n   bad", encoding="utf-8")
    with pytest.raises(P.PlanCorrupt):
        P.load(tmp_path)


def test_cycle_is_error_not_warning(tmp_path):
    _write(tmp_path, [_item("A", depends_on=["B"]), _item("B", depends_on=["A"])])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("цикл" in x.lower() for x in rep["errors"])


def test_cycle_does_not_hang_resolve(tmp_path):
    """Цикл — ошибка валидатора, но resolve обязан завершиться и не молчать об этих элементах."""
    _write(tmp_path, [_item("A", depends_on=["B"]), _item("B", depends_on=["A"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert set(res) == {"A", "B"}


def test_unknown_dependency_blocks(tmp_path):
    """Зависимость вне плана НЕ считается закрытой: неизвестное не зелёное."""
    _write(tmp_path, [_item("A", depends_on=["NOPE"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["A"]["status"] == "blocked"
    assert "NOPE" in res["A"]["blocked_by"]


def test_vendor_field_is_rejected(tmp_path):
    """План называет РОЛЬ. Поле исполнителя привязало бы план продукта к вендору."""
    _write(tmp_path, [_item("A", runtime="claude-code")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("runtime" in x for x in rep["errors"])


def test_declared_derived_status_is_flagged(tmp_path):
    """`ready` в файле — расхождение: этот статус обязан считать граф."""
    _write(tmp_path, [_item("A", status="ready")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("ВЫВОДИМЫЙ" in x for x in rep["warnings"])


def test_unknown_role_and_type_are_errors(tmp_path):
    _write(tmp_path, [_item("A", owner_role="wizard", type="magic")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("owner_role" in x for x in rep["errors"])
    assert any("type" in x for x in rep["errors"])


def test_goal_must_resolve(tmp_path):
    _write(tmp_path, [_item("A", goal="nope")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("goal" in x for x in rep["errors"])


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_workitem_fact_overrides_declared_status(tmp_path):
    """WorkItem закрыт гейтами -> элемент плана done, даже если в файле стоит todo."""
    _write(tmp_path, [_item("A")])
    d = tmp_path / "features" / "A"
    d.mkdir(parents=True)
    (d / "workitem.yaml").write_text("id: A\nstatus: done\n", encoding="utf-8")
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["A"]["status"] == "done"
    assert res["A"]["source"] == "workitem"
    assert res["A"]["drift"]                       # расхождение с объявленным ВИДНО, а не скрыто


def test_active_work_makes_item_in_progress(tmp_path):
    _write(tmp_path, [_item("A")])
    rt = tmp_path / ".ai" / "runtime"
    rt.mkdir(parents=True)
    (rt / "active-work.yaml").write_text(
        "schema_version: 1\nkind: active-work\nactive:\n"
        "  - id: s1\n    workitem: A\n    branch: b\n    areas: [src/a/]\n"
        "    session: s\n    status: in-progress\n", encoding="utf-8")
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["A"]["status"] == "in_progress"
    assert res["A"]["source"] == "active-work"


def test_write_scope_conflict_with_active_work_blocks(tmp_path):
    """Пересечение области записи с активной работой блокирует — иначе две сессии рвут одно место."""
    _write(tmp_path, [_item("A", write_scope=["src/shared/"])])
    rt = tmp_path / ".ai" / "runtime"
    rt.mkdir(parents=True)
    (rt / "active-work.yaml").write_text(
        "schema_version: 1\nkind: active-work\nactive:\n"
        "  - id: s1\n    workitem: OTHER\n    branch: b\n    areas: [src/shared/models/]\n"
        "    session: s\n    status: in-progress\n", encoding="utf-8")
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["A"]["status"] == "blocked"
    assert res["A"]["conflicts_with"] == ["OTHER"]


def test_human_decision_blocks_even_with_deps_done(tmp_path):
    _write(tmp_path, [_item("A", status="done"),
                      _item("B", depends_on=["A"], human_decision="нужно решение владельца")])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["B"]["status"] == "blocked"
    assert any("решение человека" in r for r in res["B"]["reasons"])
