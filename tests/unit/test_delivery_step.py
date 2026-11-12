"""#1527: обычный шаг поставки не требует подъёма потолка, скачок краснеет, два PR подряд не ломают main."""
from __future__ import annotations

import copy

from hypothesis import given, strategies as st
import pytest

from test_delivery_budget import _exists, _shipped, ai_ops, budget  # noqa: F401 — фикстуры
from test_merge_preview import _commit_all, _git, _load_orchestrator, _make_base


def _doc(ceiling=1_000_000, step=40_000):
    return {"ceilings": {"volume_bytes": ceiling, "substantive_files": 10}, "steps": {"volume_bytes": step}}


@pytest.mark.parametrize("event,expected", [("pull_request", 960_000), ("", 960_000),
                                            ("push", 1_000_000), ("schedule", 1_000_000)])
def test_hard_limit_leaves_room_for_a_neighbour_only_before_merge(ai_ops, event, expected):  # noqa: F811
    assert ai_ops.volume_hard_limit(_doc(), event=event) == expected


@given(base=st.integers(0, 2_000_000), a=st.integers(0, 40_000), b=st.integers(0, 40_000))
def test_two_green_prs_merged_back_to_back_never_break_main(ai_ops, base, a, b):  # noqa: F811
    """Каждый PR: итог с main под границей PR и шаг не больше обычного -> вместе под потолком main."""
    doc = _doc(ceiling=2_100_000)
    pr_limit = ai_ops.volume_hard_limit(doc, event="pull_request")
    main_limit = ai_ops.volume_hard_limit(doc, event="push")
    dmf = _load_orchestrator()
    green = [d for d in (a, b) if base + d <= pr_limit and dmf.step_verdict(base, base + d, 40_000, False)["ok"]]
    if len(green) == 2:
        assert base + a + b <= main_limit


def test_step_verdict_jump_needs_a_record():
    dmf = _load_orchestrator()
    assert dmf.step_verdict(100, 40_100, 40_000, False)["ok"]              # ровно шаг — обычный рост
    jump = dmf.step_verdict(100, 40_101, 40_000, False)
    assert jump["jump"] and not jump["ok"]
    assert dmf.step_verdict(100, 90_000, 40_000, True)["ok"]


def test_only_records_added_by_this_pr_justify_a_jump():
    dmf = _load_orchestrator()
    old = {"at": "2026-11-01", "what": "step", "work": "old"}
    base = {"raises": [old, {"at": "2026-11-01", "what": "volume", "work": "v"}]}
    head = copy.deepcopy(base)
    assert dmf.new_step_records(head, base) == []
    head["raises"].append({"at": "2026-11-12", "what": "step", "work": "new"})
    assert [r["work"] for r in dmf.new_step_records(head, base)] == ["new"]


def test_registry_must_name_a_sane_step(ai_ops, budget):  # noqa: F811
    assert ai_ops.delivery_budget_errors(budget, shipped=_shipped(ai_ops), exists=_exists) == []
    for broken in (None, 0, budget["ceilings"]["volume_bytes"]):
        doc = copy.deepcopy(budget)
        doc["steps"] = {"volume_bytes": broken}
        assert any("шаг" in p for p in ai_ops.delivery_budget_errors(doc)), broken


def _write(root, rel, size):
    (root / rel).write_text("x" * size, encoding="utf-8")


def test_delivered_bytes_of_measures_the_base_tree(tmp_path):
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    _write(root, "shipped.py", 300)
    base = _commit_all(root, "shipped")
    _git(root, "checkout", "-q", "-b", "pr")
    _write(root, "shipped.py", 70_000)
    _commit_all(root, "pr grows")
    managed = {"shipped.py"}
    assert dmf.delivered_bytes_of(str(root), base, managed) == 300
    merged = dmf.delivered_merge_footprint(str(root), base, "pr", managed, ceiling=10_000_000, fraction=0.1)
    assert not dmf.step_verdict(300, merged["delivered_bytes"], 40_000, False)["ok"]
