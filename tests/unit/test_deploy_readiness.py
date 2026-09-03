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

from ai_ops_kit.gates import deploy_readiness as dr


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

    def test_vercel_json_reason_does_not_claim_deploy_path(self, tmp_path):
        """Инструмент НЕ утверждает, что поставку ведёт найденная платформа."""
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert "ведёт" not in rep["reason"]
        assert "путь существует" not in rep["reason"]

    def test_hint_named_as_hint_not_proof(self, tmp_path):
        """Подсказка названа подсказкой, а не доказательством."""
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert "НЕ следует, что деплой идёт через них" in rep["reason"]
        assert "наследием" in rep["reason"]

    def test_honest_fork_no_delivery_or_outside_repo(self, tmp_path):
        """Честная развилка: поставки нет вовсе, либо она вне репозитория."""
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert "поставки нет вовсе, либо она производится вне репозитория" in rep["reason"]

    def test_single_deploy_path_unknown_finding_not_proof(self, tmp_path):
        """Ровно одна находка deploy_path_unknown с пометкой «не доказательство»."""
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = dr.assess(tmp_path)
        f = [x for x in rep["findings"] if x["rule"] == "deploy_path_unknown"]
        assert len(f) == 1
        assert "не доказательство" in f[0]["detail"]

    def test_declared_command_and_rollback_clear_unknown(self, tmp_path):
        """Объявленные deploy_command+rollback снимают незнание пути -> runnable."""
        (tmp_path / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  deploy: {deploy_command: vercel deploy --prod, "
            "rollback: vercel rollback}\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "runnable"
        assert rep["deploy_path_unknown"] is False
        assert not any(x["rule"] == "deploy_path_unknown" for x in rep["findings"])


@pytest.mark.unit
class TestMaturityConstant:
    """Все ступени лестницы объявлены и в правильном порядке."""

    def test_maturity_tuple(self):
        assert dr.MATURITY == ("absent", "configured", "runnable", "verified")


@pytest.mark.unit
class TestShouldRunAdditional:
    """Дополнительные триггеры применимости гейта."""

    def test_new_service_signal(self):
        assert dr.should_run_deploy_readiness([], {"new_service": True})[0] is True

    def test_terraform_change(self):
        assert dr.should_run_deploy_readiness(["infra/main.tf"])[0] is True

    def test_k8s_manifest_change(self):
        assert dr.should_run_deploy_readiness(["k8s/app.yaml"])[0] is True


@pytest.mark.unit
class TestSummaryLine:
    """summary_line() честно сообщает состояние поставки."""

    def test_absent_summary_says_norm(self, tmp_path):
        """Пустой репозиторий -> «норма» в summary_line (absent не маскируется)."""
        assert "норма" in dr.summary_line(tmp_path)

    def test_runnable_summary_reports_missing_rollback(self, tmp_path):
        """runnable без отката -> summary_line сообщает про отсутствующий откат."""
        (tmp_path / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        assert "откат не объявлен" in dr.summary_line(tmp_path)


@pytest.mark.unit
class TestDockerfileOnlyReason:
    """Dockerfile-only: путь неизвестен, платформенных подсказок нет, честный текст."""

    def test_dockerfile_only_path_unknown_no_hints(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_path_unknown"] is True
        assert rep["platform_hints"] == []
        assert "НЕ следует" not in rep["reason"]
        assert "НЕТ" in rep["reason"]


@pytest.mark.unit
class TestRecordsWithoutPath:
    """DEP-записи без исполняемого пути не дают verified."""

    def test_records_without_path_not_verified(self, tmp_path):
        rec_dir = tmp_path / ".ai" / "runtime" / "deploy"
        rec_dir.mkdir(parents=True)
        (rec_dir / "DEP-001.json").write_text("{}", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] != "verified"


@pytest.mark.unit
class TestConfigDeploy:
    """deploy_command/rollback из .ai-ops.yaml как источник исполняемого пути."""

    def test_deploy_command_from_config(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [production]\n"
            "  deploy: {deploy_command: make deploy, rollback: make rollback}\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert "config:deploy_command" in rep["runnable_paths"]

    def test_rollback_from_config(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [production]\n"
            "  deploy: {deploy_command: make deploy, rollback: make rollback}\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["rollback_declared"] is True

    def test_config_without_records_runnable_not_verified(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [production]\n"
            "  deploy: {deploy_command: make deploy, rollback: make rollback}\n", encoding="utf-8")
        rep = dr.assess(tmp_path)
        assert rep["deploy_maturity"] == "runnable"

    def test_malformed_config_does_not_crash(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        assert dr.assess(tmp_path)["deploy_maturity"] in dr.MATURITY
