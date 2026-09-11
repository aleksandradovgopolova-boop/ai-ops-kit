"""Handoff работы между ролями-владельцами — named-переход owner_role (#639, первый клин).

  * positive     — register c owner_role + handoff меняет владельца и пишет запись перехода;
  * role-only    — to_role обязана быть из словаря модели; человек/исполнитель отвергается;
  * guards       — handoff без брифа и «в ту же роль» отвергаются (передача без смысла — не передача);
  * projection   — WorkView отдаёт живой owner_role и журнал handoffs, роли попадают в participants.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.lifecycle import role_handoff as RH
from ai_ops_kit.lifecycle.active_work import Path, handoff_cmd, load, register
from ai_ops_kit.lifecycle import work_view as WV


@pytest.fixture
def work_file():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "active-work.yaml"


def _entry(work_file, wid="w1"):
    return next(w for w in load(work_file)["active"] if w["id"] == wid)


# ── vocab / pure apply ───────────────────────────────────────────────────────────────────────

def test_roles_vocab_loads_from_model():
    vocab = RH.roles_vocab()
    # Словарь модели доставлен и читается по контракту — типовые роли на месте.
    assert {"product", "architect", "engineer"} <= vocab


def test_apply_handoff_role_to_role_records_transition():
    entry = {"id": "w1", "owner_role": "product"}
    new, err = RH.apply_handoff(entry, "architect", "discovery закончен, нужен дизайн системы", "s1",
                                at="2026-09-08T00:00:00+00:00")
    assert err is None
    assert new["owner_role"] == "architect"
    assert new["handoffs"][-1] == {"from": "product", "to": "architect",
                                   "reason": "discovery закончен, нужен дизайн системы",
                                   "at": "2026-09-08T00:00:00+00:00", "session": "s1"}
    # Исходный dict не мутирован.
    assert entry.get("handoffs") is None and entry["owner_role"] == "product"


def test_apply_handoff_rejects_non_role():
    _, err = RH.apply_handoff({"owner_role": "product"}, "alice@example.com", "почему", "s")
    assert err and "вне словаря" in err


def test_apply_handoff_requires_brief():
    _, err = RH.apply_handoff({"owner_role": "product"}, "architect", "  ", "s")
    assert err and "брифа" in err


def test_apply_handoff_same_role_is_noop_error():
    _, err = RH.apply_handoff({"owner_role": "architect"}, "architect", "и снова", "s")
    assert err and "уже принадлежит" in err


# ── register + handoff_cmd through the registry ────────────────────────────────────────────────

def test_register_with_owner_role_persists(work_file):
    assert register(work_file, "w1", "feature/w1", ["areaA"], "s1", owner_role="product") == 0
    assert _entry(work_file)["owner_role"] == "product"


def test_register_rejects_bogus_owner_role(work_file):
    assert register(work_file, "w1", "feature/w1", ["areaA"], "s1", owner_role="ceo") == 1


def test_handoff_cmd_transfers_owner_and_logs(work_file):
    register(work_file, "w1", "feature/w1", ["areaA"], "s1", owner_role="product")
    assert handoff_cmd(work_file, "w1", "architect", "нужен дизайн системы", "s2") == 0
    e = _entry(work_file)
    assert e["owner_role"] == "architect"
    assert [h["to"] for h in e["handoffs"]] == ["architect"]
    assert e["handoffs"][0]["from"] == "product"
    # Второй переход дописывается, история копится.
    assert handoff_cmd(work_file, "w1", "engineer", "дизайн готов, в имплементацию", "s3") == 0
    e = _entry(work_file)
    assert e["owner_role"] == "engineer"
    assert [h["from"] + "->" + h["to"] for h in e["handoffs"]] == \
        ["product->architect", "architect->engineer"]


def test_handoff_cmd_unknown_work_errors(work_file):
    register(work_file, "w1", "feature/w1", ["areaA"], "s1")
    assert handoff_cmd(work_file, "missing", "architect", "повод", "s2") == 1


# ── WorkView projection ────────────────────────────────────────────────────────────────────────

def test_work_view_surfaces_live_owner_role_and_handoffs(tmp_path):
    awf = tmp_path / ".ai" / "runtime" / "active-work.yaml"
    awf.parent.mkdir(parents=True, exist_ok=True)
    register(awf, "w1", "feature/w1", ["areaA"], "s1", owner_role="product")
    handoff_cmd(awf, "w1", "architect", "нужен дизайн", "s2")
    view = WV.project_work("w1", tmp_path)
    assert view["owner_role"] == "architect"          # живой факт после передачи, не стартовая роль
    assert [h["to"] for h in view["handoffs"]] == ["architect"]
    # Роли из журнала попадают в participants (источник «кто владел работой» теперь есть).
    assert "product" in view["participants"] and "architect" in view["participants"]
