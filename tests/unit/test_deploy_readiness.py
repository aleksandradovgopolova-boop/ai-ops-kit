"""Unit tests for tools/deploy_readiness.py — deploy maturity assessment.

Tests the assess() function across the maturity ladder:
absent -> configured -> runnable -> verified, plus gate_status() and
should_run_deploy_readiness() applicability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import deploy_readiness as dr


@pytest.mark.unit
class TestAssessReturnsRequiredKeys:
    """assess() must return a DeployReadiness dict with all required keys."""

    def test_assess_returns_required_keys(self, tmp_path):
        rep = dr.assess(tmp_path)
        assert isinstance(rep, dict)
        assert rep["kind"] == "DeployReadiness"
        assert rep["deploy_maturity"] in dr.MATURITY
        assert "reason" in rep
        assert "config_markers" in rep
        assert "runnable_paths" in rep
        assert "rollback_declared" in rep
        assert "findings" in rep
        assert "environments" in rep
        assert "deploy_records" in rep
        assert "secret_names" in rep


@pytest.mark.unit
class TestMaturityLadder:
    """Tests for the maturity ladder: absent -> configured -> runnable -> verified."""

    def test_assess_clean_repo_absent(self, tmp_path):
        """Empty repo -> absent maturity."""
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "absent"
        assert "НОРМА" in rep["reason"]

    def test_assess_dockerfile_only_configured(self, tmp_path):
        """Dockerfile without executable path -> configured."""
        (tmp_path / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "configured"
        assert "Dockerfile" in rep["config_markers"]

    def test_assess_deploy_script_runnable(self, tmp_path):
        """Deploy script -> runnable maturity."""
        (tmp_path / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        (tmp_path / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "runnable"
        assert "deploy.sh" in rep["runnable_paths"]

    def test_assess_verified_full_ladder(self, tmp_path):
        """Runnable + rollback + evidence -> verified."""
        (tmp_path / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        (tmp_path / "rollback.sh").write_text("#!/bin/sh\necho undo\n", encoding="utf-8")
        rec_dir = tmp_path / ".ai" / "runtime" / "deploy"
        rec_dir.mkdir(parents=True)
        (rec_dir / "DEP-001.json").write_text('{"environment": "production"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "verified"
        assert rep["rollback_declared"] is True
        assert "rollback.sh" in rep["rollback_sources"]


@pytest.mark.unit
class TestShouldRunDeployReadiness:
    """Tests for should_run_deploy_readiness() — gate applicability."""

    def test_deployment_change_signal(self):
        run, why = dr.should_run_deploy_readiness([], {"deployment_change": True})
        assert run is True
        assert "deployment_change" in why

    def test_deploy_task_type(self):
        run, _ = dr.should_run_deploy_readiness([], {"task_type": "deploy"})
        assert run is True

    def test_dockerfile_change(self):
        run, _ = dr.should_run_deploy_readiness(["Dockerfile"])
        assert run is True

    def test_workflow_change(self):
        run, _ = dr.should_run_deploy_readiness([".github/workflows/deploy.yml"])
        assert run is True

    def test_normal_code_change_not_applicable(self):
        run, why = dr.should_run_deploy_readiness(["src/app.ts"], {"task_type": "ENGINEERING"})
        assert run is False
        assert "неприменим" in why


@pytest.mark.unit
class TestGateStatus:
    """Tests for gate_status() — maturity to verdict mapping."""

    def test_verified_pass(self):
        status, _ = dr.gate_status("verified")
        assert status == "pass"

    def test_runnable_pass(self):
        status, _ = dr.gate_status("runnable")
        assert status == "pass"

    def test_configured_fail(self):
        status, _ = dr.gate_status("configured")
        assert status == "fail"

    def test_absent_fail(self):
        status, _ = dr.gate_status("absent")
        assert status == "fail"

    def test_not_applicable(self):
        status, _ = dr.gate_status("verified", applicable=False)
        assert status == "not_applicable"


@pytest.mark.unit
class TestFindings:
    """Tests for findings — no_rollback_declared, records_without_path."""

    def test_runnable_without_rollback_finding(self, tmp_path):
        (tmp_path / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert any(f["rule"] == "no_rollback_declared" for f in rep["findings"])

    def test_records_without_path_finding(self, tmp_path):
        rec_dir = tmp_path / ".ai" / "runtime" / "deploy"
        rec_dir.mkdir(parents=True)
        (rec_dir / "DEP-001.json").write_text("{}", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert any(f["rule"] == "records_without_path" for f in rep["findings"])


@pytest.mark.unit
class TestCiDeployJobs:
    """Tests for CI-job detection as runnable path."""

    def test_ci_job_with_environment_and_steps(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps:\n      - run: ./ship.sh\n",
            encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "runnable"
        assert ".github/workflows/deploy.yml:ship" in rep["runnable_paths"]

    def test_ci_job_without_steps_not_runnable(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps: []\n",
            encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] != "runnable"


@pytest.mark.unit
class TestPackageJsonScripts:
    """Tests for package.json deploy/rollback script detection."""

    def test_deploy_script_detected(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts": {"deploy:prod": "vercel --prod"}}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert "package.json:scripts.deploy:prod" in rep["runnable_paths"]

    def test_rollback_script_detected(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts": {"rollback": "vercel rollback"}}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["rollback_declared"] is True

    def test_build_not_counted_as_deploy(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts": {"build": "tsc"}}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["runnable_paths"] == []

    def test_malformed_package_json_does_not_crash(self, tmp_path):
        (tmp_path / "package.json").write_text("{{ broken json", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] in dr.MATURITY


@pytest.mark.unit
class TestDeclarationTemplate:
    """Tests for declaration_template()."""

    def test_template_contains_rollback(self):
        tmpl = dr.declaration_template()
        assert "rollback:" in tmpl

    def test_template_no_shell_script(self):
        tmpl = dr.declaration_template()
        assert "#!/bin/sh" not in tmpl


@pytest.mark.unit
class TestPlatformHints:
    """Platform config markers are hints, not proof of deploy path."""

    def test_vercel_json_is_hint_not_proof(self, tmp_path):
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "configured"
        assert rep["deploy_path_unknown"] is True
        assert "vercel.json" in rep["platform_hints"]
