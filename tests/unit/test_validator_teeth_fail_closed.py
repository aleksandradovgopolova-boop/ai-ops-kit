"""B3: Validator teeth — fail-closed tests for four validators.

These validators (container_delivery, pipeline_e2e, product_qualification,
stack_qualification) previously only had positive tests (main([])==0). This test
verifies they DETECT defects by injecting faults and asserting non-zero return.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = PKG_ROOT / "ai_ops_kit" / "validation"


def _load_validator(name: str):
    """Load a validator module from the validation directory."""
    path = VALIDATION_DIR / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestContainerDeliveryFailClosed:
    """validate_container_delivery must return non-zero when deliver script is missing."""

    def test_missing_deliver_script_returns_nonzero(self):
        mod = _load_validator("validate_container_delivery.py")
        # Patch DELIVER to point to a non-existent file
        with mock.patch.object(mod, "DELIVER", Path("/nonexistent/deliver.sh")):
            result = mod.main([])
        assert result == 1, "Validator must return 1 when deliver script is missing"


class TestPipelineE2EFailClosed:
    """validate_pipeline_e2e must return non-zero when fixtures are missing."""

    def test_missing_fixtures_returns_nonzero(self):
        mod = _load_validator("validate_pipeline_e2e.py")
        # Patch FIX to point to a non-existent directory
        with mock.patch.object(mod, "FIX", Path("/nonexistent/fixtures")):
            result = mod.main([])
        assert result == 1, "Validator must return 1 when fixtures directory is missing"


class TestProductQualificationFailClosed:
    """validate_product_qualification must detect when a scenario produces wrong results.

    We test this by patching run_scenarios to return a failing result.
    """

    def test_failing_scenario_returns_nonzero(self):
        mod = _load_validator("validate_product_qualification.py")
        # Patch run_scenarios to return a failing result
        with mock.patch.object(mod, "run_scenarios", return_value=[
            ("PQ1 fake: should fail", False),
        ]):
            result = mod.main([])
        assert result == 1, "Validator must return 1 when a scenario fails"


class TestStackQualificationFailClosed:
    """validate_stack_qualification must return non-zero when fixtures are missing."""

    def test_missing_fixtures_returns_nonzero(self):
        mod = _load_validator("validate_stack_qualification.py")
        # Patch FIX to point to a non-existent directory
        with mock.patch.object(mod, "FIX", Path("/nonexistent/fixtures")):
            result = mod.main([])
        assert result == 1, "Validator must return 1 when fixtures directory is missing"

    def test_corrupted_golden_detected(self):
        """Validator must detect when golden files produce wrong failure IDs."""
        mod = _load_validator("validate_stack_qualification.py")
        # Patch run_checks to return a failing result (simulating corrupted golden)
        with mock.patch.object(mod, "run_checks", return_value=(
            [("golden pytest: corrupted -> id not found", False)],
            [],
        )):
            result = mod.main([])
        assert result == 1, "Validator must return 1 when golden checks fail"
