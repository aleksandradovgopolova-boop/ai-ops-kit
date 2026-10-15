"""Unit tests for tools/workitem.py — WorkItem creation and status derivation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.lifecycle import workitem


@pytest.mark.unit
class TestWorkItemStart:
    """Tests for start(): creating a new WorkItem."""

    def test_start_creates_workitem_file(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "test-feat", "fix a typo")
        assert wi["kind"] == "workitem"
        assert wi["id"] == "test-feat"
        assert wi["status"] == "draft"
        assert workitem.wi_path(str(features), "test-feat").is_file()

    def test_start_has_required_paths(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "add feature")
        assert set(wi["paths"]) == {"blueprint", "run_state", "workitem"}

    def test_start_has_workflow(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "task", task_type="bug")
        assert wi["workflow"]  # non-empty, routed

    def test_start_has_lifecycle_intent(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        wi = workitem.start(str(features), "demo", "task")
        assert wi.get("lifecycle_intent") == "discovery"

    def test_start_writes_valid_yaml(self, tmp_path):
        features = tmp_path / "features"
        features.mkdir()
        workitem.start(str(features), "demo", "task")
        data = yaml.safe_load(workitem.wi_path(str(features), "demo").read_text(encoding="utf-8"))
        assert data["kind"] == "workitem"
        assert data["id"] == "demo"


@pytest.mark.unit
class TestDeriveStatus:
    """Tests for derive_status(): deterministic status from gate evidence."""

    def test_quick_without_evidence_needs_more(self):
        result = workitem.derive_status("QUICK", Path("/nonexistent"), {})
        assert result["status"] == "needs_more_evidence"

    def test_quick_with_full_evidence_is_done(self):
        evidence = {
            "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "pass",
                "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
        }
        result = workitem.derive_status("QUICK", Path("/nonexistent"), evidence)
        assert result["status"] == "done"

    def test_real_gate_failure_is_blocked(self):
        evidence = {
            "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "fail", "blockers": ["tests failed"]},
        }
        result = workitem.derive_status("QUICK", Path("/nonexistent"), evidence)
        assert result["status"] == "blocked"

    def test_status_result_has_schema(self):
        result = workitem.derive_status("QUICK", Path("/nonexistent"), {})
        assert result["schema_version"] == 1
        assert result["kind"] == "workitem-status"
        assert "action" in result
        assert "lifecycle_intent" in result

    def test_unclosed_human_approval_needs_human_decision(self):
        """Перенесено из монолита (прополка): если все машинные гейты pass, но остался незакрытый
        human-approval — статус needs_human_decision, а не done. Гранулярно проверялись
        needs_more_evidence/done/blocked, но эта ветвь — нет."""
        ge = workitem.gate_executor
        gates = ge.load_gates()
        for wid, w in ge.load_workflows().items():
            gs = w.get("quality_gates", []) or []
            human = [g for g in gs if ge.classify(gates[g]) == "human-approval"]
            if not human:
                continue
            # закрываем все НЕ-human гейты, human оставляем открытым
            ev = {g: {"status": "pass", "provided": list(gates[g].get("required_evidence", []) or [])}
                  for g in gs if g not in human}
            result = workitem.derive_status(wid, Path("/nonexistent"), ev)
            assert result["status"] == "needs_human_decision", (wid, human, result["status"])
            return
        pytest.skip("нет workflow с human-approval гейтом")


def _planned_work(tmp_path):
    import json
    from ai_ops_kit.gates import gate_executor

    features = tmp_path / "features"
    wi = workitem.start(features, "external", "fixture external runtime")
    wi["workflow"] = "QUICK"
    path = workitem.wi_path(features, "external")
    path.write_text(yaml.safe_dump(wi))
    plan = {"schema_version": 1, "kind": "run-plan", "workitem_id": "external",
            "base_workflow": "QUICK", "gates": [*gate_executor.load_workflows()["QUICK"]["quality_gates"], "ux_review"],
            "required_tracks": [{"track": "VISUAL", "reason": "fixture UI", "gates": ["ux_review"]}]}
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    evidence = {"intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
                "implementation_verification": {"status": "pass", "provided": [
                    "build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]}}
    ep = tmp_path / "evidence.json"
    ep.write_text(json.dumps(evidence))
    return features, path, plan, ep, evidence


def test_external_status_keeps_run_plan_track_gates(tmp_path):
    features, path, _, ep, _ = _planned_work(tmp_path)
    result = workitem.status_cmd(features, "external", evidence_file=ep)
    assert result["status"] == "needs_more_evidence"
    assert "ux_review" in result["unmet_gates"]
    assert yaml.safe_load(path.read_text())["status"] == "needs_more_evidence"


@pytest.mark.parametrize("change", [
    {"gates": []}, {"gates": "ux_review"}, {"workitem_id": "other"},
    {"base_workflow": "ENGINEERING"}, {"required_tracks": "bad"}, {"kind": "other"}])
def test_unusable_run_plan_refuses_without_changing_workitem(tmp_path, change):
    features, path, plan, ep, _ = _planned_work(tmp_path)
    plan.update(change)
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="RunPlan"):
        workitem.status_cmd(features, "external", evidence_file=ep)
    assert path.read_bytes() == before


def test_corrupt_run_plan_is_not_legacy_absence(tmp_path):
    features, path, _, ep, _ = _planned_work(tmp_path)
    (path.parent / "run-plan.yaml").write_text("gates: [broken")
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="RunPlan"):
        workitem.status_cmd(features, "external", evidence_file=ep)
    assert path.read_bytes() == before


def test_legacy_without_run_plan_preserves_base_status(tmp_path):
    features, path, _, ep, _ = _planned_work(tmp_path)
    (path.parent / "run-plan.yaml").unlink()
    assert workitem.status_cmd(features, "external", evidence_file=ep)["status"] == "done"


def test_track_cannot_disappear_from_flat_gate_list(tmp_path):
    features, path, plan, ep, _ = _planned_work(tmp_path)
    plan["gates"].remove("ux_review")
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="RunPlan"):
        workitem.status_cmd(features, "external", evidence_file=ep)
    assert path.read_bytes() == before


def test_all_planned_evidence_can_complete_external_work(tmp_path):
    import json
    from ai_ops_kit.gates import gate_executor

    features, path, _, ep, evidence = _planned_work(tmp_path)
    evidence["ux_review"] = {"status": "pass", "provided": gate_executor.load_gates()["ux_review"]["required_evidence"]}
    ep.write_text(json.dumps(evidence))
    result = workitem.status_cmd(features, "external", evidence_file=ep)
    assert result["status"] == "done", result
    assert yaml.safe_load(path.read_text())["status"] == "done"


def test_optional_track_gate_metadata_does_not_break_valid_plan(tmp_path):
    features, path, plan, ep, _ = _planned_work(tmp_path)
    del plan["required_tracks"][0]["gates"]
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    assert "ux_review" in workitem.status_cmd(features, "external", evidence_file=ep)["unmet_gates"]


def test_real_standalone_cli_retains_missing_planned_evidence(tmp_path):
    import json
    import os
    import subprocess
    import sys

    features, path, _, ep, _ = _planned_work(tmp_path)
    script = Path(workitem.__file__).resolve()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run([sys.executable, str(script), "status", str(features), "external",
                             "--evidence", str(ep), "--json"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "needs_more_evidence"
    assert "ux_review" in report["unmet_gates"]
    assert yaml.safe_load(path.read_text())["status"] == "needs_more_evidence"


def test_active_conditional_track_cannot_disappear_from_gate_list(tmp_path):
    features, path, plan, ep, _ = _planned_work(tmp_path)
    plan["required_tracks"] = []
    plan["conditional_tracks"] = [{"track": "VISUAL", "reason": "active fixture", "gates": ["ux_review"]}]
    plan["gates"].remove("ux_review")
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="RunPlan"):
        workitem.status_cmd(features, "external", evidence_file=ep)
    assert path.read_bytes() == before


def test_direct_orchestrator_uses_saved_plan_even_with_empty_override(tmp_path):
    from ai_ops_kit.providers import orchestrator

    _features, _path, _plan, _ep, evidence = _planned_work(tmp_path)
    state, run_dir = orchestrator.run_workflow(
        "QUICK", "fixture external runtime", tmp_path, workitem_id="external",
        gate_evidence=evidence, verbose=False, gate_ids=[])
    assert state["status"] == "blocked", state
    assert "ux_review" in state["unmet_gates"]
    assert (Path(run_dir) / "TaskState.yaml").is_file()


def test_direct_orchestrator_bad_plan_stops_before_provider_or_state(tmp_path):
    from ai_ops_kit.providers import orchestrator

    _features, path, _plan, _ep, _evidence = _planned_work(tmp_path)
    (path.parent / "run-plan.yaml").write_text("not a plan")
    calls = []
    with pytest.raises(SystemExit, match="RunPlan"):
        orchestrator.run_workflow("QUICK", "fixture", tmp_path, workitem_id="external",
                                  provider=lambda prompt: calls.append(prompt) or "", verbose=False)
    assert calls == []
    assert not (tmp_path / ".ai/runtime/workitems/external").exists()


def test_unknown_plan_gate_stops_before_direct_provider(tmp_path):
    from ai_ops_kit.providers import orchestrator

    _features, path, plan, _ep, _evidence = _planned_work(tmp_path)
    plan["gates"].append("not-a-real-gate")
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    calls = []
    with pytest.raises(SystemExit, match="RunPlan"):
        orchestrator.run_workflow("QUICK", "fixture", tmp_path, workitem_id="external",
                                  provider=lambda prompt: calls.append(prompt) or "", verbose=False)
    assert calls == []
    assert not (tmp_path / ".ai/runtime/workitems/external").exists()


def test_incomplete_base_plan_refused_before_provider(tmp_path):
    from ai_ops_kit.providers import orchestrator

    features, path, plan, ep, _ = _planned_work(tmp_path)
    plan["gates"].remove("implementation_verification")
    (path.parent / "run-plan.yaml").write_text(yaml.safe_dump(plan))
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="RunPlan"):
        workitem.status_cmd(features, "external", evidence_file=ep)
    calls = []
    with pytest.raises(SystemExit, match="RunPlan"):
        orchestrator.run_workflow("QUICK", "fixture", tmp_path, workitem_id="external",
                                  provider=lambda prompt: calls.append(prompt) or "", verbose=False)
    assert calls == []
    assert path.read_bytes() == before
    assert not (tmp_path / ".ai/runtime/workitems/external").exists()
