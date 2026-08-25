"""Unit tests for tools/run_plan.py — plan creation and validation."""
from __future__ import annotations

import pytest

import run_plan


@pytest.mark.unit
class TestValidateWorkitemId:
    """Tests for validate_workitem_id(): path traversal prevention."""

    def test_valid_slug_accepted(self):
        assert run_plan.validate_workitem_id("wi-abc_123.v2") == "wi-abc_123.v2"

    def test_simple_slug_accepted(self):
        assert run_plan.validate_workitem_id("feat-42") == "feat-42"

    @pytest.mark.parametrize("bad", [
        "../evil", "a/b", "/abs", "..", ".hidden",
        "UPPER", "x" * 65, "", "a b", "a\\b",
    ])
    def test_invalid_slugs_rejected(self, bad):
        with pytest.raises(ValueError):
            run_plan.validate_workitem_id(bad)


@pytest.mark.unit
class TestBuildPlan:
    """Tests for build_plan(): constructing a run plan from signals."""

    def test_build_plan_has_required_fields(self):
        signals = {
            "task_type": "ENGINEERING",
            "task_text": "fix a bug",
        }
        plan = run_plan.build_plan(signals)
        assert plan["kind"] == "run-plan"
        assert plan["schema_version"] == 1
        assert plan["base_workflow"]
        assert "gates" in plan
        assert "execution_budget" in plan

    def test_build_plan_with_workitem_id(self):
        signals = {"task_type": "QUICK", "task_text": "small fix"}
        plan = run_plan.build_plan(signals, workitem_id="feat-42")
        assert plan["workitem_id"] == "feat-42"

    def test_build_plan_auto_workitem_id(self):
        signals = {"task_type": "QUICK", "task_text": "small fix"}
        plan = run_plan.build_plan(signals)
        assert plan["workitem_id"].startswith("wi-")

    def test_build_plan_tracks_present(self):
        signals = {"task_type": "PRODUCT", "ui_changed": True, "measurable_behavior": True,
                   "security_surface_changed": True, "user_facing_change": True}
        plan = run_plan.build_plan(signals)
        # Should have tracks lists
        assert "required_tracks" in plan
        assert "conditional_tracks" in plan
        assert "skipped_tracks" in plan


@pytest.mark.unit
class TestTrackSelection:
    """Выбор треков и гейтов из сигналов — поведение, а не только форма плана.

    Перенесено из монолитного test_run_plan_selftest (прополка): гранулярный файл проверял лишь
    НАЛИЧИЕ ключей required/conditional/skipped, а какие именно треки выбираются по сигналам и какие
    гейты они добавляют — не проверялось нигде. Здесь эта логика закреплена по-тестово.
    """

    _PRODUCT_SIG = {
        "task_type": "PRODUCT", "risk": "medium",
        "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
        "ui_changed": True, "measurable_behavior": True, "security_surface_changed": True,
        "user_facing_change": True, "task_text": "фильтр по статусу в каталоге заказов",
    }

    def test_product_ui_analytics_security_require_their_tracks(self):
        plan = run_plan.build_plan(self._PRODUCT_SIG)
        required = {t["track"] for t in plan["required_tracks"]}
        assert {"VISUAL", "ANALYTICS", "SECURITY", "DOCUMENTATION"} <= required
        assert plan["base_workflow"] == "PRODUCT"

    def test_selected_tracks_add_their_gates_to_base(self):
        # PRODUCT сам по себе не имел ux/analytics гейтов — их добавляют треки
        plan = run_plan.build_plan(self._PRODUCT_SIG)
        assert {"ux_review", "analytics_design_readiness", "security"} <= set(plan["gates"])
        assert run_plan.validate_plan(plan) == []

    def test_no_ui_skips_visual_with_reason_and_drops_its_gate(self):
        sig = dict(self._PRODUCT_SIG); sig["ui_changed"] = False
        plan = run_plan.build_plan(sig)
        vis = next((t for t in plan["skipped_tracks"] if t["track"] == "VISUAL"), None)
        assert vis is not None and "UI" in vis["reason"]
        assert "ux_review" not in plan["gates"]

    def test_ai_component_adds_conditional_ai_track_and_gate(self):
        sig = dict(self._PRODUCT_SIG); sig["ai_component"] = True
        plan = run_plan.build_plan(sig)
        assert any(t["track"] == "AI" for t in plan["conditional_tracks"])
        assert "ai_red_team" in plan["gates"]


@pytest.mark.unit
class TestValidatePlan:
    """Tests for validate_plan(): plan integrity checks."""

    def test_valid_plan_no_errors(self):
        signals = {"task_type": "ENGINEERING", "task_text": "fix"}
        plan = run_plan.build_plan(signals)
        errors = run_plan.validate_plan(plan)
        assert errors == []

    def test_wrong_kind_is_error(self):
        plan = {"kind": "wrong", "base_workflow": "QUICK", "gates": [],
                "required_tracks": [], "conditional_tracks": [], "skipped_tracks": []}
        errors = run_plan.validate_plan(plan)
        assert any("kind" in e for e in errors)

    def test_missing_workflow_is_error(self):
        plan = {"kind": "run-plan", "base_workflow": "", "gates": [],
                "required_tracks": [], "conditional_tracks": [], "skipped_tracks": []}
        errors = run_plan.validate_plan(plan)
        assert any("base_workflow" in e for e in errors)


@pytest.mark.unit
class TestValidateTracks:
    """Tests for validate_tracks(): registry integrity."""

    def test_tracks_yaml_is_consistent(self):
        errors = run_plan.validate_tracks()
        assert errors == []
