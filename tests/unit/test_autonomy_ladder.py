"""#1413: автономность — управляемый уровень по правилу, с авто-понижением и защитой от самоповышения."""
import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.governance import decision_boundary as db
from ai_ops_kit.governance import enforcement

LOW = {"risk": "low"}


def _journal(root: Path, work: str, task_type: str, results: list, at: str = "2026-11-10T00:00:00+00:00"):
    rows = []
    for i, ok in enumerate(results):
        att = f"{work}#a{i + 1}"
        rows.append({"kind": "run_start", "attempt_id": att, "task_type": task_type})
        rows.append({"kind": "run_end", "attempt_id": att, "ready_for_pr": ok, "at": at})
    path = root / "features" / work / "lifecycle-journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _policy(root: Path, doc: dict):
    path = root / ".ai-ops/POLICY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True))


@pytest.mark.parametrize(("kwargs", "level", "limited"), [
    ({"signals": LOW}, "policy_governed", "класс действия"),
    ({"signals": {"risk": "medium"}}, "deliver", "класс действия"),
    ({"signals": {"risk": "high"}}, "assist", "класс действия"),
    ({"signals": LOW, "task_type": "db-migration"}, "deliver", "тип задачи"),
    ({"signals": LOW, "runtime_rights": "read_only"}, "assist", "права runtime"),
    ({"signals": LOW, "runtime_rights": "no_merge"}, "deliver", "права runtime"),
    ({"signals": LOW, "runtime_rights": "что-то новое"}, "assist", "права runtime"),
])
def test_level_is_chosen_by_rule(kwargs, level, limited):
    signals = kwargs.pop("signals")
    v = db.ladder(signals, **kwargs)
    assert v["level"] == level and limited in v["limited_by"]
    assert v["allows"] == {"assist": [], "deliver": ["create_pr"]}.get(level, ["create_pr", "merge"])


def test_repeated_failures_demote_only_that_task_type(tmp_path):
    _journal(tmp_path, "w1", "db-migration", [False])
    _journal(tmp_path, "w2", "db-migration", [True, False])
    _journal(tmp_path, "w3", "feature", [False, False])
    v = db.ladder(LOW, root=tmp_path, task_type="db-migration")
    assert v["level"] == "assist" and v["demoted"] and v["limited_by"] == ["история"]
    assert v["allows"] == []
    assert db.ladder(LOW, root=tmp_path, task_type="docs")["level"] == "policy_governed"


def test_single_failure_does_not_demote(tmp_path):
    _journal(tmp_path, "w1", "db-migration", [False, True, True])
    v = db.ladder(LOW, root=tmp_path, task_type="db-migration")
    assert v["level"] == "deliver" and not v["demoted"]


def test_owner_restore_restarts_the_count(tmp_path):
    _journal(tmp_path, "w1", "db-migration", [False, False], at="2026-11-10T00:00:00+00:00")
    _policy(tmp_path, {"autonomy_ladder": {"restore": {"db-migration": "2026-11-12"}}})
    assert not db.ladder(LOW, root=tmp_path, task_type="db-migration")["demoted"]


def test_agent_cannot_raise_its_own_level(tmp_path):
    v = db.ladder(LOW, task_type="db-migration", requested_level="policy_governed")
    assert v["level"] == "deliver" and any("отклонено" in r for r in v["reason"])
    assert db.ladder(LOW, requested_level="execute")["level"] == "execute"   # строже — можно
    # Владелец поднимает потолок типа задачи только в защищённой политике...
    _policy(tmp_path, {"autonomy_ladder": {"task_types": {"db-migration": "supervised"}}})
    assert db.ladder(LOW, root=tmp_path, task_type="db-migration")["level"] == "supervised"
    # ...и если эту политику меняет сама работа, повышение не действует.
    v = db.ladder(LOW, root=tmp_path, task_type="db-migration", changed_paths=[".ai-ops/POLICY.yaml"])
    assert v["level"] == "deliver" and any("политика меняется" in r for r in v["reason"])


def test_owner_cannot_bypass_runtime_or_risk_facts(tmp_path):
    _policy(tmp_path, {"autonomy_ladder": {"task_types": {"db-migration": "policy_governed"}}})
    v = db.ladder({"risk": "high"}, root=tmp_path, task_type="db-migration", runtime_rights="no_push")
    assert v["level"] == "assist"


def test_broken_registry_fails_closed():
    v = db.ladder(LOW, model={"classes": []})
    assert v["level"] == "assist" and v["allows"] == []


def test_delivery_gate_waits_for_approval_after_demotion(tmp_path):
    _policy(tmp_path, {"enforcement": "block", "autonomy": {"create_pr": "execute"}})
    _journal(tmp_path, "w9", "db-migration", [True])
    ok = enforcement.gate_delivery(tmp_path, target="w9")
    assert ok["allowed"] and not ok["blocked"] and ok["autonomy"]["level"] == "deliver"
    _journal(tmp_path, "w1", "db-migration", [False, False])
    blocked = enforcement.gate_delivery(tmp_path, target="w9")
    assert blocked["blocked"] and blocked["requires_approval"]
    assert "лестница автономии" in blocked["reason"]


def test_engine_stamps_time_on_run_end():
    src = (Path(db.PKG) / "ai_ops_kit/engine/ai_ops_run_lifecycle_stages.py").read_text()
    end = src[src.index('{"kind": "run_end"'):]
    assert '"at": datetime.now(timezone.utc).isoformat()' in end[:600]
