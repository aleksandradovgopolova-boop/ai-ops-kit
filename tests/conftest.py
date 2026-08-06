"""Pytest configuration for AI Ops Kit Verification Foundation (v3.25.0).

This conftest provides:
1. Fixtures for common test patterns (temp repos, mock providers, etc.)
2. Selftest wrappers — allow running existing --selftest functions via pytest
3. Critical path markers for CI layer separation
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Add tools/ to path for imports
PKG_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PKG_ROOT / "tools"
VALIDATION_DIR = PKG_ROOT / "validation"
for p in (TOOLS_DIR, VALIDATION_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_repo(tmp_path):
    """Create a minimal temporary repository structure for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".ai").mkdir()
    (repo / ".ai" / "runtime").mkdir()
    (repo / "features").mkdir()
    return repo


@pytest.fixture
def mock_provider():
    """A simple mock provider for testing orchestrator/pipeline."""
    def _mock(prompt: str) -> str:
        return f"MOCK_RESPONSE: {prompt[:50]}"
    return _mock


@pytest.fixture
def child_root(tmp_path):
    """Alias for temp_repo — standard naming in AI Ops codebase."""
    repo = tmp_path / "child"
    repo.mkdir()
    (repo / ".ai").mkdir()
    (repo / ".ai" / "runtime").mkdir()
    (repo / ".ai" / "usage").mkdir()
    (repo / "features").mkdir()
    return repo


# ============================================================================
# Selftest Wrappers
# ============================================================================
# These wrappers allow running existing --selftest functions via pytest.
# Each wrapper imports the module and calls its selftest() function.
# This provides a unified test runner while preserving existing test logic.

SELFTEST_MODULES_TOOLS = [
    "orchestrator",
    "execution_pipeline",
    "tool_loop",
    "budget",
    "tool_broker",
    "gate_executor",
    "gitio",
    "lifecycle_store",
    "pr_open",
    "workitem",
    "run_plan",
    "ai_ops_run",
    "ai_ops_cli",
    "bench_lite",
    "gate_policy",
    "gate_result_v2",
    "storybook_adapter",
    "evolution_triggers",
    "cost_account",
    "model_comparison",
    "security_review_cascade",
    "usage_ledger",
    "session_telemetry",
    "session_telemetry_provider",
    "session_guardrails",
    "session_boundary",
    "delegation_advisor",
    "cost_method",
    "commit_policy",
    "branch_policy",
    "environment_map",
    "deploy_readiness",
    "economic_preflight",
    "engineering_advisor",
    "ui_readiness",
    "model_router",
    "provider_endpoints",
    "parallel_live",
    "repo_graph",
    "data_classification",
    "context_retrieval",
    "semantic_lite",
    "context_engine",
    "context_promotion_gate",
    "context_hybrid",
    "context_shadow",
    "retrieval_bench",
    "gate_runtime",
    "parallel_planner",
    "parallel_executor",
    "storybook_query",
    "seam_scan",
    "ui_evidence_collect",
    "project_detector",
    "evidence_collector",
    "active_work",
    "worktree",
    "merge_memory",
    "concurrency_preflight",
    "qual_run",
    "context_compiler",
    "spec_levels",
    "run_handoff",
    "atomic_planner",
    "security_pack",
    "security_scan",
    "generate_runtime",
    "generate_artifacts",
    "run_report",
    "effect_metrics",
    "architecture_baseline",
    "product_health",
    "preflight",
    "approvals",
    "review_branch",
    "workpackage_executor",
    "security_enforcement",
    "context_cost",
]

SELFTEST_MODULES_VALIDATION = [
    "validate_ai_first_registry",
    "validate_ai_first_workflows",
    "validate_ai_first_config",
    "validate_ai_first_providers",
    "ai_route",
    "ai_capability_selftest",
    "validate_stale_gates",
    "validate_runtime_surface",
    "validate_reviewer_result",
    "validate_workflow_gates",
    "validate_scenario_evidence",
    "validate_bootstrap_qualification",
    "validate_surface_wiring",
    "validate_storybook_evidence",
    "validate_architecture_decision",
    "validate_adr_registry",
    "validate_quality_attributes",
    "validate_feature_learning",
    "validate_learning_loop",
    "validate_context_architecture",
    "validate_loop_policy",
    "validate_work_graph",
    "validate_budget_contract",
    "validate_capability_scope",
    "validate_access_filter",
    "validate_provider_residency",
    "validate_model_roles",
    "validate_model_qualification",
    "validate_release_claims",
    "validate_engops_policy",
    "validate_regression_corpus",
    "validate_loop_trace",
    "validate_integration_trace",
    "validate_post_release_readout",
    "validate_python_compat",
    "validate_event_catalog",
    "validate_security_posture",
    "validate_duties",
    "validate_presets",
    "validate_agent_evals",
    "validate_openspec_change",
    "validate_feature_blueprint",
    "validate_cross_artifacts",
    "validate_knowledge_graph",
    "validate_references",
    "validate_claims",
    "validate_freshness",
    "validate_context_completeness",
    "validate_decisions",
    "validate_agents_checklist",
    "validate_package_boundaries",
    "validate_standalone_engine",
    "validate_qualification",
    "validate_promotion_qualification",
    "validate_stack_qualification",
    "validate_pipeline_e2e",
    "validate_supply_chain",
    "validate_memory_governance",
    "validate_key_lifecycle",
    "validate_requirements_artifact",
    "validate_plan_artifact",
    "validate_spec_artifact",
    "validate_container_assets",
    "validate_container_delivery",
    "validate_context_bundle",
    "validate_spec_coverage",
    "validate_run_handoff",
    "validate_security_domains",
    "validate_context_qualification",
    "validate_product_qualification",
]


def _run_selftest(module_name: str, module_dir: Path) -> bool:
    """Run a module's selftest() function and return True if it passed."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, module_dir / f"{module_name}.py")
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return False
    if hasattr(module, "selftest"):
        try:
            result = module.selftest()
            return result == 0
        except Exception:
            return False
    return False


# Generate pytest test functions for each selftest module
# These are collected by pytest and run as individual tests
def _make_selftest_test(module_name: str, module_dir: Path, category: str):
    """Create a pytest test function for a selftest module."""
    def test_func():
        assert _run_selftest(module_name, module_dir), f"{module_name} selftest failed"
    test_func.__name__ = f"test_selftest_{module_name}"
    test_func.__doc__ = f"Wrapper for {module_name}.selftest() — {category}"
    # Add markers for CI layer separation
    if module_name in ("orchestrator", "execution_pipeline", "preflight", "tool_broker",
                       "gate_executor", "ai_ops_run", "ai_ops_cli"):
        test_func.pytestmark = [pytest.mark.critical_path, pytest.mark.unit]
    else:
        test_func.pytestmark = [pytest.mark.unit]
    return test_func


# Register selftest wrappers as pytest tests
for _mod in SELFTEST_MODULES_TOOLS:
    _test = _make_selftest_test(_mod, TOOLS_DIR, "tools")
    globals()[_test.__name__] = _test

for _mod in SELFTEST_MODULES_VALIDATION:
    _test = _make_selftest_test(_mod, VALIDATION_DIR, "validation")
    globals()[_test.__name__] = _test


# ============================================================================
# Pytest markers for CI layer separation
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "critical_path: tests for critical execution path")
    config.addinivalue_line("markers", "unit: unit tests (fast, no external deps)")
    config.addinivalue_line("markers", "contract: contract tests (interface verification)")
    config.addinivalue_line("markers", "integration: integration tests (multi-module)")
    config.addinivalue_line("markers", "live: live tests (require external services)")
    config.addinivalue_line("markers", "regression: regression tests for known bugs")
    config.addinivalue_line("markers", "slow: tests that take >10 seconds")
