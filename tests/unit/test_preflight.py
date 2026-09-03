"""Unit tests for tools/preflight.py — pre-execution checks.

Tests the deterministic preflight gates: classification, context payload,
spec sufficiency, atomicity, context budget, approvals, lifecycle errors,
and economic budget. Complements test_property_based.py without duplication.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.gates import preflight

# Собранный ContextPayload для heavy-задач: без него heavy блокируется на context_payload,
# и остальные гейты (spec/atomic/economics) остались бы непроверенными.
GOOD_PAYLOAD = {"text": "=== [rule] ..."}


@pytest.mark.critical_path
@pytest.mark.unit
class TestPreflightClean:
    """Tests for clean preflight — no blockers."""

    def test_clean_quick_atomic(self, child_root):
        """QUICK atomic task with no issues should pass preflight."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
            "size": "small",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True
        assert result["blocked"] is False
        assert len(result["reasons"]) == 0


@pytest.mark.critical_path
@pytest.mark.unit
class TestSpecSufficiency:
    """Tests for spec-first gate — blocks heavy tasks without spec."""

    def test_quick_without_spec_not_blocked(self, child_root):
        """QUICK task without spec should not block (light task)."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestAtomicity:
    """Tests for atomic gate — non-atomic tasks need decomposition confirmation."""

    def test_atomic_task_passes(self, child_root):
        """Atomic task with work_package_id should pass atomic gate."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestContextBudget:
    """Tests for context budget overflow gate."""

    def test_overflow_blocked(self, child_root):
        """Context overflow should block execution."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        bundle = {"overflow": True}
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            bundle=bundle,
            author=True,
        )
        assert result["blocked"] is True
        assert any("context" in r.lower() or "budget" in r.lower() for r in result["reasons"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestApprovals:
    """Tests for human approval gates — secret_boundary and destructive."""

    def test_secret_boundary_without_approval_blocked(self, child_root):
        """secret_boundary=True without ApprovalRecord should block."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "secret_boundary": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
        )
        assert result["blocked"] is True
        assert any("approval" in r.lower() or "human" in r.lower() for r in result["reasons"])

    def test_destructive_without_approval_blocked(self, child_root):
        """destructive=True without ApprovalRecord should block."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "destructive": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
        )
        assert result["blocked"] is True
        assert any("destructive" in r.lower() for r in result["reasons"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestLifecycleErrors:
    """Tests for lifecycle error gate — fail-closed for heavy tasks."""

    def test_lifecycle_error_heavy_blocked(self, child_root):
        """Heavy task with lifecycle errors should block (fail-closed)."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
            lifecycle_errors=["Compiler failed"],
        )
        assert result["blocked"] is True
        assert any("lifecycle" in r.lower() for r in result["reasons"])

    def test_lifecycle_error_quick_not_blocked(self, child_root):
        """QUICK task with lifecycle errors should not block (light task)."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            lifecycle_errors=["Compiler failed"],
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestReevaluateOnly:
    """Tests for reevaluate_only mode — bypasses some gates."""

    def test_reevaluate_bypasses_spec(self, child_root):
        """reevaluate_only=True should bypass spec-first gate."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            reevaluate_only=True,
        )
        # Spec gate should not block
        spec_check = result["checks"].get("spec", {})
        assert not spec_check.get("blocking") or spec_check.get("skipped_reevaluate")

    def test_reevaluate_does_not_bypass_approvals(self, child_root):
        """reevaluate_only=True should NOT bypass approval gates."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "destructive": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            reevaluate_only=True,
        )
        assert result["blocked"] is True
        assert any("approval" in r.lower() or "destructive" in r.lower() for r in result["reasons"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestSpecSufficiencyDetailed:
    """Spec-first gate — точные значения из перенесённого selftest."""

    def test_incomplete_spec_blocked(self, child_root):
        """Существующая, но неполная спека (blocking_missing) -> blocked + spec-first."""
        result = preflight.assess(
            {"task_type": "QUICK"}, child_root, "w", payload=GOOD_PAYLOAD,
            spec_cov={"spec_artifact": True, "blocking_missing": ["goal", "scope"]},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is True
        assert any("spec-first" in r for r in result["reasons"])

    def test_heavy_without_spec_without_author_blocked(self, child_root):
        """Heavy без спеки и без --author -> blocked (spec-first ДО реализации)."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
            child_root, "w", payload=GOOD_PAYLOAD,
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is True
        assert any("spec-first" in r and "ДО реализации" in r for r in result["reasons"])

    def test_heavy_without_spec_with_author_passes(self, child_root):
        """Heavy без спеки, но с --author -> spec-гейт пройден, spec-first не поднят."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
            child_root, "w", payload=GOOD_PAYLOAD, author=True,
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["checks"]["spec"]["ok"] is True
        assert not any("spec-first" in r for r in result["reasons"])

    def test_heavy_with_full_spec_passes_without_author(self, child_root):
        """Heavy с полной спекой на диске -> spec-гейт пройден даже без --author."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
            child_root, "w", payload=GOOD_PAYLOAD,
            spec_cov={"spec_artifact": True, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["checks"]["spec"]["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestAtomicityDetailed:
    """Atomic-гейт — boolean-подтверждения недостаточно (v2.120)."""

    _WP = {"should_decompose": True, "work_packages": [{"id": "a"}, {"id": "b"}]}

    def test_non_atomic_without_confirmation_blocked(self, child_root):
        """Неатомарная задача без выбора пакета -> blocked."""
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "w", payload=GOOD_PAYLOAD,
            spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=self._WP,
        )
        assert result["blocked"] is True

    def test_bare_decomposition_confirmed_still_blocked(self, child_root):
        """Голый decomposition_confirmed больше не пускает блоб -> всё ещё blocked."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "decomposition_confirmed": True}, child_root, "w",
            payload=GOOD_PAYLOAD, spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg=self._WP,
        )
        assert result["blocked"] is True

    def test_existing_package_id_passes_atomic(self, child_root):
        """Выбран существующий пакет из плана -> atomic-гейт пройден."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "work_package_id": "a"}, child_root, "w", author=True,
            payload=GOOD_PAYLOAD, spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg=self._WP,
        )
        assert result["checks"]["atomic"]["ok"] is True

    def test_fictional_package_id_blocked(self, child_root):
        """Вымышленный work_package_id (нет в плане) -> blocked + selected_valid False."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "work_package_id": "ghost"}, child_root, "w",
            payload=GOOD_PAYLOAD, spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg=self._WP,
        )
        assert result["blocked"] is True
        assert result["checks"]["atomic"]["selected_valid"] is False

    def test_sequence_plan_id_passes_atomic(self, child_root):
        """id из авторитетного плана sequence-исполнителя -> atomic-гейт пройден."""
        result = preflight.assess(
            {"task_type": "ENGINEERING", "work_package_id": "seq-2",
             "_sequence_plan_ids": ["seq-1", "seq-2"]}, child_root, "w", author=True,
            payload=GOOD_PAYLOAD, spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg=self._WP,
        )
        assert result["checks"]["atomic"]["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestContextPayload:
    """ContextPayload обязателен для heavy (fail-closed), для QUICK — light."""

    def test_payload_none_heavy_blocked(self, child_root):
        """payload не собран + heavy -> blocked (fail-closed)."""
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "w", payload=None,
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is True

    def test_payload_none_quick_not_blocked(self, child_root):
        """payload не собран + QUICK -> не блокирует (light)."""
        result = preflight.assess(
            {"task_type": "QUICK"}, child_root, "w", payload=None,
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestApprovalsValidRecord:
    """secret_boundary с валидным, сверяемым ApprovalRecord -> approvals пройдены."""

    def test_secret_boundary_with_valid_approval_passes(self, child_root):
        from ai_ops_kit.gates import approvals

        fdir = child_root / "features" / "w"
        fdir.mkdir(parents=True, exist_ok=True)
        # Привязка обязана быть СВЕРЯЕМОЙ: кладём план и связываем запись с его реальным хэшем.
        (fdir / "run-plan.yaml").write_text(
            "base_workflow: ENGINEERING\ngates: [a]\n", encoding="utf-8")
        approvals.write_record(
            child_root, "w", "secrets", "u@x", "config", "согласовано",
            created_at="2026-07-18", expires_at="2027-01-01T00:00:00Z",
            risk="secret", source="user",
        )
        result = preflight.assess(
            {"task_type": "ENGINEERING", "secret_boundary": True}, child_root, "w",
            payload=GOOD_PAYLOAD, spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["checks"]["approvals"]["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestEconomicBudget:
    """Экономическая граница ДО tool loop (v3.21.0 EngOps срез 3).

    author=True снимает spec-first, чтобы единственной переменной осталась экономика.
    """

    _BASE = dict(payload=GOOD_PAYLOAD, author=True,
                 spec_cov={"spec_artifact": False, "blocking_missing": []},
                 work_pkg={"should_decompose": False})

    def test_economic_check_present(self, child_root):
        """Экономическая проверка присутствует в checks."""
        result = preflight.assess({"task_type": "ENGINEERING"}, child_root, "we", **self._BASE)
        assert bool(result["checks"].get("economic_budget"))

    def test_no_history_proceeds_unknown(self, child_root):
        """Нет истории -> не блок, verdict proceed_unknown, статус unavailable, median None."""
        result = preflight.assess({"task_type": "ENGINEERING"}, child_root, "we", **self._BASE)
        eco = result["checks"]["economic_budget"]
        assert result["blocked"] is False
        assert eco["ok"] is True
        assert eco["verdict"] == "proceed_unknown"
        assert eco["estimate_status"] == "unavailable"
        assert eco["cost_median"] is None

    def test_ledger_recorded_estimate(self, child_root):
        """Side-effect proof: ledger записан и читается -> measured_history, sample=2, max=9.0."""
        from ai_ops_kit.gates import economic_preflight
        from ai_ops_kit.shared import usage_ledger

        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        est = economic_preflight.estimate(child_root)
        assert est["status"] == "measured_history"
        assert est["sample_tasks"] == 2
        assert est["cost_max"] == 9.0

    def test_worst_run_over_limit_blocked(self, child_root):
        """Худший сравнимый прогон (9.0) дороже лимита (5) -> blocked ДО модели."""
        from ai_ops_kit.shared import usage_ledger
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "we",
            plan={"execution_budget": {"max_cost": 5}}, **self._BASE)
        assert result["blocked"] is True
        assert result["checks"]["economic_budget"]["ok"] is False
        assert any("economic-preflight" in r for r in result["reasons"])

    def test_only_economics_blocks(self, child_root):
        """Блокирует именно экономика — других причин в reasons нет."""
        from ai_ops_kit.shared import usage_ledger
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "we",
            plan={"execution_budget": {"max_cost": 5}}, **self._BASE)
        assert len(result["reasons"]) == 1

    def test_within_limit_not_blocked(self, child_root):
        """В пределах лимита -> экономика не блокирует."""
        from ai_ops_kit.shared import usage_ledger
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "we",
            plan={"execution_budget": {"max_cost": 20}}, **self._BASE)
        assert result["checks"]["economic_budget"]["ok"] is True
        assert result["blocked"] is False

    def test_no_execution_budget_not_blocked(self, child_root):
        """Лимита нет вовсе -> не выдумываем и не блокируем."""
        from ai_ops_kit.shared import usage_ledger
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        result = preflight.assess({"task_type": "ENGINEERING"}, child_root, "we", **self._BASE)
        assert result["checks"]["economic_budget"]["ok"] is True

    def test_reevaluate_only_skips_economic(self, child_root):
        """reevaluate_only -> экономическая проверка не применяется, не блокирует."""
        from ai_ops_kit.shared import usage_ledger
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            usage_ledger.append(child_root, wid, [{
                "role": "writer", "cost": cost, "cost_status": "measured",
                "usage_status": "measured", "input_tokens": 10, "output_tokens": 10}])
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "we",
            plan={"execution_budget": {"max_cost": 5}}, reevaluate_only=True, **self._BASE)
        assert "economic_budget" not in result["checks"]
        assert result["blocked"] is False
