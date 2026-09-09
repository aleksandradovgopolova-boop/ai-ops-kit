"""Шина внимания (#633): гарантия, что каждый повод позвать человека доходит до inbox.

  * bus       — record кладёт повод, collect отдаёт pending, resolve снимает; идемпотентно по key;
  * inbox     — то, что записано в шину, ВИДНО в inbox (8-й источник) и меняет статус/счёт очереди;
  * coverage  — каждый смоделированный тип вызова человека (decision / blocked) появляется в inbox.
"""
from __future__ import annotations

import pytest
import yaml

from ai_ops_kit.lifecycle import attention_bus as AB
from ai_ops_kit.cli import ai_ops_cli_intents as CI


def _empty_registry(root):
    """Валидный пустой active-work — чтобы inbox считал реестр достоверным (registry_ok)."""
    p = root / ".ai" / "runtime" / "active-work.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"schema_version": 1, "kind": "active-work", "active": []}),
                 encoding="utf-8")


# ── bus ──────────────────────────────────────────────────────────────────────────────────────

def test_record_then_collect(tmp_path):
    assert AB.record(tmp_path, key="preflight:w1", source="прогон: preflight",
                     reason="работа остановлена", kind=AB.BLOCKED, work_id="w1")
    recs = AB.collect(tmp_path)
    assert len(recs) == 1 and recs[0]["key"] == "preflight:w1" and recs[0]["status"] == "pending"


def test_record_idempotent_by_key(tmp_path):
    AB.record(tmp_path, key="preflight:w1", source="s", reason="первая", kind=AB.BLOCKED)
    AB.record(tmp_path, key="preflight:w1", source="s", reason="вторая причина", kind=AB.BLOCKED)
    recs = AB.collect(tmp_path)
    assert len(recs) == 1 and recs[0]["reason"] == "вторая причина"  # обновление, не дубль


def test_resolve_removes(tmp_path):
    AB.record(tmp_path, key="preflight:w1", source="s", reason="r", kind=AB.BLOCKED)
    assert AB.resolve(tmp_path, "preflight:w1") is True
    assert AB.collect(tmp_path) == []
    assert AB.resolve(tmp_path, "preflight:w1") is False   # уже снят — идемпотентно


# ── attention_summary (#676): «сколько внимания стоил прогон» ──────────────────────────────────

def test_attention_summary_counts_all_including_resolved(tmp_path):
    # #676: снятый повод остаётся свидетельством, что внимание понадобилось — иначе метрику
    # «человеческое внимание на результат» не посчитать. resolve помечает, а не удаляет.
    AB.record(tmp_path, key="preflight:w1", source="s", reason="r", kind=AB.BLOCKED, work_id="w1")
    AB.record(tmp_path, key="gov:w2", source="s", reason="r", kind=AB.DECISION, work_id="w2")
    assert AB.resolve(tmp_path, "preflight:w1") is True     # снят -> из очереди ушёл

    pending_keys = {r["key"] for r in AB.collect(tmp_path)}
    assert pending_keys == {"gov:w2"}                        # снятого в очереди нет, второй остался
    s = AB.attention_summary(tmp_path)
    assert s == {"total": 2, "decision": 1, "blocked": 1, "pending": 1, "resolved": 1}


def test_attention_summary_empty_is_zero(tmp_path):
    assert AB.attention_summary(tmp_path) == {
        "total": 0, "decision": 0, "blocked": 0, "pending": 0, "resolved": 0}


def test_resolve_does_not_lose_the_record(tmp_path):
    AB.record(tmp_path, key="preflight:w1", source="s", reason="r", kind=AB.BLOCKED)
    AB.resolve(tmp_path, "preflight:w1")
    # collect (для inbox) снятого не отдаёт, но замер внимания его помнит
    assert AB.collect(tmp_path) == []
    assert AB.attention_summary(tmp_path)["total"] == 1


def test_missing_fields_not_recorded(tmp_path):
    assert AB.record(tmp_path, key="", source="s", reason="r") is False
    assert AB.collect(tmp_path) == []


def test_corrupt_store_is_failsafe_empty(tmp_path):
    p = tmp_path / ".ai" / "runtime" / "attention.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(": : не yaml : :", encoding="utf-8")
    assert AB.collect(tmp_path) == []                      # битый сток не роняет чтение


# ── inbox integration (8-й источник) ───────────────────────────────────────────────────────

def test_attention_surfaces_in_inbox(tmp_path):
    _empty_registry(tmp_path)
    AB.record(tmp_path, key="preflight:w1", source="прогон: preflight",
              reason="работа остановлена до запуска модели", kind=AB.BLOCKED, work_id="w1")
    queue = CI._inbox_collect(tmp_path)
    assert queue["registry_ok"] is True
    assert queue["total"] == 1
    assert [a["key"] for a in queue["attention"]] == ["preflight:w1"]
    # Остановка -> очередь заблокирована; текст называет источник и причину.
    assert CI._inbox_status(queue) == "blocked"
    text = CI._inbox_render(queue, aud="technical")
    assert "прогон: preflight" in text and "остановлена до запуска" in text


def test_decision_kind_makes_inbox_need_input(tmp_path):
    _empty_registry(tmp_path)
    AB.record(tmp_path, key="boundary:current", source="граница решений",
              reason="это решение за человеком", kind=AB.DECISION)
    queue = CI._inbox_collect(tmp_path)
    assert CI._inbox_status(queue) == "needs_input"
    assert "вызовов из прогона — 1" in CI._inbox_counts(queue)


def test_empty_bus_keeps_inbox_ok(tmp_path):
    _empty_registry(tmp_path)
    queue = CI._inbox_collect(tmp_path)
    assert queue["attention"] == [] and queue["total"] == 0
    assert CI._inbox_status(queue) == "ok"


@pytest.mark.parametrize("kind,expect", [(AB.BLOCKED, "blocked"), (AB.DECISION, "needs_input")])
def test_each_human_call_type_reaches_inbox(tmp_path, kind, expect):
    _empty_registry(tmp_path)
    AB.record(tmp_path, key=f"k:{kind}", source="источник", reason="повод", kind=kind)
    queue = CI._inbox_collect(tmp_path)
    assert len(queue["attention"]) == 1
    assert CI._inbox_status(queue) == expect
