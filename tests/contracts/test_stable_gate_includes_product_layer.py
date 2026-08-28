"""Stable channel gate includes product layer readiness check.

Работа `stable-gate-includes-product-layer` (цель `qualification-closeout`).

РЕШЕНИЕ ВЛАДЕЛЬЦА ep-2026-08-20-stable-includes-product-operating-layer: stable включает
реализацию PR-1..PR-25. Канал stable не объявить, пока пять целей Product OS не достигнуты.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.contract, pytest.mark.critical_path]


@pytest.fixture(scope="module")
def release_claims():
    return yaml.safe_load((KIT / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plan():
    return yaml.safe_load((KIT / "planning" / "plan.yaml").read_text(encoding="utf-8"))


class TestStableGateRequiresProductLayer:
    """Stable channel requires product_layer_ready."""

    def test_stable_requires_product_layer_ready(self, release_claims):
        """Stable channel must include product_layer_ready in requires list."""
        channels = release_claims.get("channels", {})
        stable = channels.get("stable", {})
        requires = stable.get("requires", [])
        assert "product_layer_ready" in requires, (
            "stable channel не требует product_layer_ready — канал можно объявить заработанным, "
            "пока кит ещё не умеет вести продуктовую операционку "
            "(ep-2026-08-20-stable-includes-product-operating-layer)")

    def test_stable_declares_product_layer_goals(self, release_claims):
        """Stable channel must declare which goals constitute the product layer."""
        channels = release_claims.get("channels", {})
        stable = channels.get("stable", {})
        goals = stable.get("product_layer_goals", [])
        assert len(goals) >= 5, (
            f"stable.product_layer_goals содержит только {len(goals)} целей — "
            f"ожидается минимум 5 (product-operating-layer, backlog-intelligence, "
            f"roadmap-and-delivery, ai-product-operations, autonomous-product-loop)")

    def test_validator_detects_unachieved_goals(self):
        """Validator must fail when product goals are not achieved."""
        from ai_ops_kit.validation import validate_release_claims as vrc
        # Simulate a release-claims with product_layer_ready but unachieved goals
        data = {
            "version": "1.0.0",
            "channel": "stable",
            "channels": {
                "stable": {
                    "requires": ["product_layer_ready"],
                    "product_layer_goals": ["goal-a", "goal-b"],
                }
            },
        }
        # Create a temporary plan.yaml with unachieved goals
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir)
            (pkg / "planning").mkdir()
            (pkg / "planning" / "plan.yaml").write_text(yaml.dump({
                "goals": [
                    {"id": "goal-a", "status": "active"},
                    {"id": "goal-b", "status": "active"},
                ]
            }))
            # Temporarily override PKG
            orig_pkg = vrc.PKG
            vrc.PKG = pkg
            try:
                errors = vrc.channel_errors(data)
                assert any("product_layer_ready" in e for e in errors), (
                    f"валидатор не ловит не-achieved цели: {errors}")
            finally:
                vrc.PKG = orig_pkg

    def test_validator_passes_when_all_achieved(self):
        """Validator must pass when all product goals are achieved."""
        from ai_ops_kit.validation import validate_release_claims as vrc
        data = {
            "version": "1.0.0",
            "channel": "stable",
            "channels": {
                "stable": {
                    "requires": ["product_layer_ready"],
                    "product_layer_goals": ["goal-a", "goal-b"],
                }
            },
        }
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir)
            (pkg / "planning").mkdir()
            (pkg / "planning" / "plan.yaml").write_text(yaml.dump({
                "goals": [
                    {"id": "goal-a", "status": "achieved"},
                    {"id": "goal-b", "status": "achieved"},
                ]
            }))
            orig_pkg = vrc.PKG
            vrc.PKG = pkg
            try:
                errors = vrc.channel_errors(data)
                product_errors = [e for e in errors if "product_layer_ready" in e]
                assert not product_errors, (
                    f"валидатор краснеет при всех achieved целях: {product_errors}")
            finally:
                vrc.PKG = orig_pkg
