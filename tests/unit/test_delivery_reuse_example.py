"""Полный offline-проход и измерение реальных исполнений до/после reuse."""
import pytest

from ai_ops_kit.devtools.delivery_reuse_probe import run_example


@pytest.mark.slow
@pytest.mark.unit
def test_complete_flow_reduces_actual_check_executions(tmp_path):
    result = run_example(tmp_path)
    assert result["requested_checks"] == result["baseline_executions"] == 6
    assert result["executions_with_reuse"] == 2 and result["reused_results"] == 4
    assert result["deploy_executions"] == 1 and result["repeat_action"] == "reconcile"
    assert result["release_status"] == result["repeat_status"] == "PASS"
    assert result["external_ci_verified"] is False and result["external_public_verified"] is False
