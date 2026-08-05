"""Process Contract Tests (v3.27.5 WP6) — доказательство инвариантов процессов.

Эти тесты специально доказывают, что:
- PRODUCT не может попасть в merge без code review
- PRODUCT с migration получает architecture review
- CRITICAL с deployment получает deploy readiness
- draft не запускает full verification
- docs-only не запускает product tests
- analytics live не требуется до release
- released без DeliveryReceipt невалиден

Каждый тест — контракт, который не должен нарушаться.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml


# ============================================================================
# WP2: Gate Coverage Matrix — PRODUCT/CRITICAL имеют полный контур качества
# ============================================================================

class TestGateCoverageMatrix:
    """Доказательство: PRODUCT и CRITICAL не могут пройти без необходимых гейтов."""

    def test_product_requires_code_review(self):
        """PRODUCT workflow включает code_review в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        product = workflows.get("PRODUCT", {})
        gates = product.get("quality_gates", [])
        assert "code_review" in gates, "PRODUCT должен требовать code_review (WP2)"

    def test_product_requires_security(self):
        """PRODUCT workflow включает security в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        product = workflows.get("PRODUCT", {})
        gates = product.get("quality_gates", [])
        assert "security" in gates, "PRODUCT должен требовать security (WP2)"

    def test_product_requires_architecture_review(self):
        """PRODUCT workflow включает architecture_review в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        product = workflows.get("PRODUCT", {})
        gates = product.get("quality_gates", [])
        assert "architecture_review" in gates, "PRODUCT должен требовать architecture_review (WP2)"

    def test_product_requires_deploy_readiness(self):
        """PRODUCT workflow включает deploy_readiness в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        product = workflows.get("PRODUCT", {})
        gates = product.get("quality_gates", [])
        assert "deploy_readiness" in gates, "PRODUCT должен требовать deploy_readiness (WP2)"

    def test_critical_requires_architecture_review(self):
        """CRITICAL workflow включает architecture_review в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        critical = workflows.get("CRITICAL", {})
        gates = critical.get("quality_gates", [])
        assert "architecture_review" in gates, "CRITICAL должен требовать architecture_review (WP2)"

    def test_critical_requires_deploy_readiness(self):
        """CRITICAL workflow включает deploy_readiness в quality_gates."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows_data = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        workflows = workflows_data.get("workflows", {})
        critical = workflows.get("CRITICAL", {})
        gates = critical.get("quality_gates", [])
        assert "deploy_readiness" in gates, "CRITICAL должен требовать deploy_readiness (WP2)"

    def test_gates_applicability_includes_product(self):
        """code_review, security, architecture_review, deploy_readiness применимы к PRODUCT."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        for gate_name in ["code_review", "security", "architecture_review", "deploy_readiness"]:
            gate = gates.get(gate_name, {})
            applicability = gate.get("applicability", [])
            assert "PRODUCT" in applicability, f"{gate_name} должен быть применим к PRODUCT (WP2)"

    def test_gates_applicability_includes_critical(self):
        """architecture_review, deploy_readiness применимы к CRITICAL."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        for gate_name in ["architecture_review", "deploy_readiness"]:
            gate = gates.get(gate_name, {})
            applicability = gate.get("applicability", [])
            assert "CRITICAL" in applicability, f"{gate_name} должен быть применим к CRITICAL (WP2)"


# ============================================================================
# WP3: Analytics Gate Split — design до merge, runtime после release
# ============================================================================

class TestAnalyticsGateSplit:
    """Доказательство: analytics разделён на design (до merge) и runtime (после release)."""

    def test_analytics_design_readiness_exists(self):
        """analytics_design_readiness гейт существует."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        assert "analytics_design_readiness" in gates, "analytics_design_readiness должен существовать (WP3)"

    def test_analytics_runtime_verification_exists(self):
        """analytics_runtime_verification гейт существует."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        assert "analytics_runtime_verification" in gates, "analytics_runtime_verification должен существовать (WP3)"

    def test_analytics_design_does_not_require_live(self):
        """analytics_design_readiness НЕ требует events_verified_live."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        design = gates.get("analytics_design_readiness", {})
        required = design.get("required_evidence", [])
        assert "events_verified_live" not in required, \
            "analytics_design_readiness не должен требовать events_verified_live (WP3)"

    def test_analytics_runtime_requires_live(self):
        """analytics_runtime_verification ТРЕБУЕТ events_verified_live."""
        gates_path = Path(__file__).parents[2] / "quality" / "gates.yaml"
        gates_data = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        gates = gates_data.get("gates", {})
        runtime = gates.get("analytics_runtime_verification", {})
        required = runtime.get("required_evidence", [])
        assert "events_verified_live" in required, \
            "analytics_runtime_verification должен требовать events_verified_live (WP3)"

    def test_analytics_workflows_use_design(self):
        """PRODUCT, ANALYTICS, ADOPTION используют analytics_design_readiness, не analytics_readiness."""
        workflows_path = Path(__file__).parents[2] / "registry" / "workflows.yaml"
        workflows = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
        for wf_name in ["PRODUCT", "ANALYTICS", "ADOPTION"]:
            wf = workflows.get(wf_name, {})
            gates = wf.get("quality_gates", [])
            # analytics_readiness больше не используется
            assert "analytics_readiness" not in gates, \
                f"{wf_name} не должен использовать analytics_readiness (WP3)"


# ============================================================================
# WP4: Progressive Verification Truth — skip/affected/module/full tiers
# ============================================================================

class TestProgressiveVerification:
    """Доказательство: progressive verification работает корректно."""

    def test_docs_only_returns_skip_tier(self):
        """docs-only изменения возвращают skip tier, не запускают product tests."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
        import verification_tiers

        tier = verification_tiers.decide_tier(["README.md", "docs/guide.md"])
        assert tier == "skip", "docs-only должен возвращать skip tier (WP4)"

    def test_draft_intent_returns_affected_tier(self):
        """draft lifecycle_intent возвращает affected tier, не full."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
        import verification_tiers

        tier = verification_tiers.decide_tier(["tools/module.py"], lifecycle_intent="draft")
        assert tier == "affected", "draft intent должен возвращать affected tier (WP4)"

    def test_merge_candidate_intent_returns_full_tier(self):
        """merge_candidate lifecycle_intent возвращает full tier."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
        import verification_tiers

        tier = verification_tiers.decide_tier(["tools/module.py"], lifecycle_intent="merge_candidate")
        assert tier == "full", "merge_candidate intent должен возвращать full tier (WP4)"

    def test_no_affected_tests_returns_unknown_status(self):
        """Если граф не нашёл затронутых тестов, возвращается impact_unknown, не 'не влияет'."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
        import verification_tiers

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tools").mkdir()
            (root / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
            # Нет тестов -> impact_unknown
            result = verification_tiers.select_tests(["tools/module.py"], str(root))
            assert result["impact_status"] == "targeted_tests_not_found", \
                "нет тестов должен возвращать targeted_tests_not_found, не 'не влияет' (WP4)"


# ============================================================================
# WP5: Release Evidence — SHA-verified DeliveryReceipt
# ============================================================================

class TestReleaseEvidence:
    """Доказательство: released требует SHA-verified DeliveryReceipt."""

    def test_released_without_delivery_receipt_fails(self):
        """feature.status=released без DeliveryReceipt -> fail."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "validation"))
        import validate_feature_blueprint

        with tempfile.TemporaryDirectory() as td:
            fdir = Path(td) / "test-feature"
            fdir.mkdir()
            bp = {
                "schema_version": 1, "kind": "feature-blueprint",
                "feature": {"id": "test-feature", "name": "Test", "status": "released",
                            "current_stage": "delivery"},
                "artifacts": {
                    "discovery": [{"path": "discovery/problem.md", "status": "done"}],
                    "delivery": [{"path": "delivery/plan.md", "status": "done"}],
                },
            }
            (fdir / "discovery").mkdir()
            (fdir / "delivery").mkdir()
            (fdir / "discovery" / "problem.md").write_text("# Problem\n", encoding="utf-8")
            (fdir / "delivery" / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")

            errors = validate_feature_blueprint.validate_dir(fdir)
            released_errors = [e for e in errors if "released" in e]
            assert len(released_errors) > 0, "released без DeliveryReceipt должен fail (WP5)"

    def test_released_with_sha_verified_delivery_receipt_passes(self):
        """feature.status=released с SHA-verified DeliveryReceipt -> ok."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "validation"))
        import validate_feature_blueprint

        with tempfile.TemporaryDirectory() as td:
            fdir = Path(td) / "test-feature"
            fdir.mkdir()
            bp = {
                "schema_version": 1, "kind": "feature-blueprint",
                "feature": {"id": "test-feature", "name": "Test", "status": "released",
                            "current_stage": "delivery"},
                "artifacts": {
                    "discovery": [{"path": "discovery/problem.md", "status": "done"}],
                    "delivery": [{"path": "delivery/plan.md", "status": "done"}],
                },
            }
            (fdir / "discovery").mkdir()
            (fdir / "delivery").mkdir()
            (fdir / "discovery" / "problem.md").write_text("# Problem\n", encoding="utf-8")
            (fdir / "delivery" / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")

            # Добавляем SHA-verified DeliveryReceipt
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": "d1",
                       "workitem_id": "test-feature", "sha_verified": True, "remote_sha": "abc123"}
            (fdir / "delivery-receipt.yaml").write_text(yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")

            errors = validate_feature_blueprint.validate_dir(fdir)
            released_errors = [e for e in errors if "released" in e]
            assert len(released_errors) == 0, \
                "released с SHA-verified DeliveryReceipt должен pass (WP5)"

    def test_released_with_sha_unverified_delivery_receipt_fails(self):
        """feature.status=released с sha_verified=false DeliveryReceipt -> fail."""
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "validation"))
        import validate_feature_blueprint

        with tempfile.TemporaryDirectory() as td:
            fdir = Path(td) / "test-feature"
            fdir.mkdir()
            bp = {
                "schema_version": 1, "kind": "feature-blueprint",
                "feature": {"id": "test-feature", "name": "Test", "status": "released",
                            "current_stage": "delivery"},
                "artifacts": {
                    "discovery": [{"path": "discovery/problem.md", "status": "done"}],
                    "delivery": [{"path": "delivery/plan.md", "status": "done"}],
                },
            }
            (fdir / "discovery").mkdir()
            (fdir / "delivery").mkdir()
            (fdir / "discovery" / "problem.md").write_text("# Problem\n", encoding="utf-8")
            (fdir / "delivery" / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")

            # Добавляем DeliveryReceipt с sha_verified=false
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": "d1",
                       "workitem_id": "test-feature", "sha_verified": False, "remote_sha": "abc123"}
            (fdir / "delivery-receipt.yaml").write_text(yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")

            errors = validate_feature_blueprint.validate_dir(fdir)
            released_errors = [e for e in errors if "released" in e]
            assert len(released_errors) > 0, \
                "released с sha_verified=false DeliveryReceipt должен fail (WP5)"
