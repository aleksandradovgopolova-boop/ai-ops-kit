"""Позднее завершение прежней попытки не меняет перенятую работу."""
from __future__ import annotations

import copy
import json

import pytest

from ai_ops_kit.cli import ai_ops_cli_commands as cmd
from ai_ops_kit.engine import parallel_live_dispatch as dsp
from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.shared import gitio
from test_parallel_live_dispatch import _saved_auto


def _automatic(root):
    signals, _ = _saved_auto(root)
    auto = cmd._automatic_roots(root, "work", signals, None)
    return dict(signals, _auto_package_signals=auto.pop("package_signals")), auto


def _passed(root):
    sha = gitio.git(root, "rev-parse", "HEAD")[1]
    return {"proceed": True, "stage": "fan-in", "integration_sha": sha,
            "aggregate": {"all_pass": True, "tested_revision": sha},
            "delivery_plan": {"ready": True, "integration_clone": str(root)}}


def _owned_bytes(root):
    files = list((root / ".git/ai-ops").rglob("*.yaml"))
    files += list((root / ".ai/claims").glob("*.yaml"))
    files += [root / ".ai/runtime/active-work.yaml", root / "features/work/parallel-report.json"]
    return {str(p): p.read_bytes() for p in files if p.is_file()}


@pytest.mark.parametrize("replacement", ["takeover", "same-session-generation"])
def test_late_parallel_completion_preserves_replacement_and_never_delivers(tmp_path, monkeypatch, replacement):
    signals, auto = _automatic(tmp_path)
    registry = aw.shared_registry_path(tmp_path)
    deliveries, dispatched, expected = [], [], {}
    report = tmp_path / "features/work/parallel-report.json"

    def runner(*args, **kwargs):
        old = copy.deepcopy(aw.load(registry)["active"][0])
        dispatched.append(old)
        if replacement == "takeover":
            assert aw.register(registry, "work", "ai-ops/work", ["aa.txt", "bb.txt"], "rescue",
                               child_root=tmp_path, published=True, takeover=True,
                               takeover_reason="explicit recovery after interruption") == 0
        else:
            assert aw.finish_cmd(registry, "work", child_root=tmp_path) == 0
            new_admission = dict(old["auto_admission"], attempt_id="replacement-attempt")
            assert aw.register(registry, "work", "ai-ops/work", ["aa.txt", "bb.txt"],
                               old["owner_session"], child_root=tmp_path, admission=new_admission) == 0
        report.write_text('{"holder":"replacement","must_survive":true}\n')
        expected.update(_owned_bytes(tmp_path))
        current = aw.load(registry)["active"][0]
        assert current != old and current["status"] == "in-progress"
        return _passed(tmp_path)

    monkeypatch.setattr(dsp, "_deliver_parallel", lambda *a, **k: deliveries.append(a))
    result = dsp.run_parallel_live("write work", signals, tmp_path, feature="work", provider="mock",
                                   open_pr=True, runner=runner, **auto)
    assert len(dispatched) == 1, "a real claim was acquired and then replaced during the runner"
    assert deliveries == [], "a stale attempt must stop before delivery"
    assert result["proceed"] is False and dsp.exit_code(result) == 2
    assert "claim" in result["reason"]
    assert _owned_bytes(tmp_path) == expected, "canonical/projected/carrier/report bytes belong to replacement"


def test_unchanged_attempt_finishes_and_next_same_session_has_new_identity(tmp_path):
    signals, auto = _automatic(tmp_path)
    original_admission = copy.deepcopy(auto["admission"])
    registry = aw.shared_registry_path(tmp_path)
    attempts = []

    def runner(*args, **kwargs):
        attempts.append(copy.deepcopy(aw.load(registry)["active"][0]["auto_admission"]))
        return _passed(tmp_path)

    for _ in range(2):
        result = dsp.run_parallel_live("write work", signals, tmp_path, feature="work", provider="mock",
                                       runner=runner, **auto)
        assert dsp.exit_code(result) == 0
        assert aw.load(registry)["active"][0]["status"] == "done"
        assert json.loads((tmp_path / "features/work/parallel-report.json").read_text())["proceed"] is True
    assert attempts[0]["identity"] == attempts[1]["identity"]
    assert attempts[0]["attempt_id"] != attempts[1]["attempt_id"]
    assert auto["admission"] == original_admission, "saved admission inputs stay unchanged"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "closed"])
def test_unknown_or_closed_claim_stops_before_delivery_and_report(tmp_path, monkeypatch, damage):
    signals, auto = _automatic(tmp_path)
    registry = aw.shared_registry_path(tmp_path)
    deliveries, expected = [], {}

    def runner(*args, **kwargs):
        if damage == "missing":
            registry.unlink()
        elif damage == "corrupt":
            registry.write_text("active: [invalid yaml")
        else:
            assert aw.finish_cmd(registry, "work", status="blocked", child_root=tmp_path) == 0
        (tmp_path / "features/work/parallel-report.json").write_text('{"preserve":"previous report"}\n')
        expected.update(_owned_bytes(tmp_path))
        return _passed(tmp_path)

    monkeypatch.setattr(dsp, "_deliver_parallel", lambda *a, **k: deliveries.append(a))
    result = dsp.run_parallel_live("write work", signals, tmp_path, feature="work", provider="mock",
                                   open_pr=True, runner=runner, **auto)
    assert dsp.exit_code(result) == 2 and deliveries == []
    assert _owned_bytes(tmp_path) == expected
    assert registry.exists() is (damage != "missing")


def test_takeover_during_already_admitted_delivery_keeps_receipt_and_new_report(tmp_path, monkeypatch):
    signals, auto = _automatic(tmp_path)
    registry = aw.shared_registry_path(tmp_path)
    expected, delivered = {}, []

    def deliver(rec, *args):
        delivered.append(rec["integration_sha"])
        rec["delivery"] = {"status": "opened", "sha_verified": True, "receipt": {"already_executed": True}}
        assert aw.register(registry, "work", "ai-ops/work", ["aa.txt", "bb.txt"], "rescue",
                           child_root=tmp_path, takeover=True, takeover_reason="explicit recovery") == 0
        (tmp_path / "features/work/parallel-report.json").write_text('{"holder":"replacement"}\n')
        expected.update(_owned_bytes(tmp_path))

    monkeypatch.setattr(dsp, "_deliver_parallel", deliver)
    result = dsp.run_parallel_live("write work", signals, tmp_path, feature="work", provider="mock",
                                   open_pr=True, runner=lambda *a, **k: _passed(tmp_path), **auto)
    assert len(delivered) == 1, "an already admitted external effect cannot be retroactively cancelled"
    assert result["delivery"]["receipt"]["already_executed"] is True
    assert dsp.exit_code(result) == 2 and _owned_bytes(tmp_path) == expected
