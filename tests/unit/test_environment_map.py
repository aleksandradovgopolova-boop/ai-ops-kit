"""Гранулярные тесты environment_map (мигрировано из test_environment_map_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json

import pytest

from environment_map import (
    Path,
    assess,
    kind_of,
    summary_line,
)


@pytest.mark.unit
class TestKindOf:
    def test_production(self):
        assert kind_of("prod-eu") == "production" and kind_of("production") == "production"

    def test_staging(self):
        assert kind_of("staging") == "staging" and kind_of("uat") == "staging"

    def test_preview(self):
        assert kind_of("preview") == "preview"

    def test_unknown_name(self):
        assert kind_of("зелёный") == "unknown"

    def test_empty_name(self):
        assert kind_of(None) == "unknown" and kind_of("") == "unknown"


@pytest.mark.unit
class TestAssessEmptyRepo:
    def test_empty_repo_not_detected(self, tmp_path):
        rep = assess(tmp_path)
        assert rep["environments_status"] == "not_detected"
        assert rep["environments"] == []
        assert rep["findings"] == []

    def test_summary_honest(self, tmp_path):
        assert "not_detected" in summary_line(tmp_path)


@pytest.mark.unit
class TestAssessCIEnvironments:
    @pytest.fixture
    def repo_with_workflow(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "name: deploy\n"
            "on: {push: {branches: [main]}}\n"
            "jobs:\n"
            "  ship:\n"
            "    environment: production\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: ./deploy.sh\n"
            "        env: {TOKEN: '${{ secrets.DEPLOY_TOKEN }}'}\n", encoding="utf-8")
        return tmp_path

    def test_ci_environment_detected(self, repo_with_workflow):
        rep = assess(repo_with_workflow)
        assert [e["name"] for e in rep["environments"]] == ["production"]

    def test_kind_production(self, repo_with_workflow):
        rep = assess(repo_with_workflow)
        assert rep["environments"][0]["kind"] == "production"

    def test_source_workflow_job(self, repo_with_workflow):
        rep = assess(repo_with_workflow)
        assert rep["environments"][0]["sources"] == [".github/workflows/deploy.yml:ship"]

    def test_detected_not_declared_finding(self, repo_with_workflow):
        rep = assess(repo_with_workflow)
        assert any(f["rule"] == "detected_not_declared" for f in rep["findings"])

    def test_secret_names_collected(self, repo_with_workflow):
        rep = assess(repo_with_workflow)
        assert rep["secret_names"] == ["DEPLOY_TOKEN"]

    def test_summary_shows_undeclared(self, repo_with_workflow):
        assert "не объявлено: production" in summary_line(repo_with_workflow)

    def test_declared_and_detected(self, repo_with_workflow):
        (repo_with_workflow / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n"
            "    - {name: production, kind: production, approvers: [owner]}\n", encoding="utf-8")
        rep = assess(repo_with_workflow)
        assert rep["environments"][0]["status"] == "declared_and_detected"
        assert rep["findings"] == []

    def test_production_without_approvers(self, repo_with_workflow):
        (repo_with_workflow / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n    - {name: production}\n", encoding="utf-8")
        assert any(f["rule"] == "production_without_approvers" for f in assess(repo_with_workflow)["findings"])

    def test_declared_not_detected(self, repo_with_workflow):
        (repo_with_workflow / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n"
            "    - {name: production, approvers: [owner]}\n    - {name: staging, approvers: [owner]}\n",
            encoding="utf-8")
        rep = assess(repo_with_workflow)
        assert any(f["rule"] == "declared_not_detected" and f["environment"] == "staging"
                   for f in rep["findings"])


@pytest.mark.unit
class TestAssessEnvFiles:
    def test_env_staging_detected(self, tmp_path):
        (tmp_path / ".env.staging").write_text("API_URL=https://x\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert [e["name"] for e in rep["environments"]] == ["staging"]

    def test_env_example_not_environment(self, tmp_path):
        (tmp_path / ".env.example").write_text("# комментарий\nANTHROPIC_API_KEY=sk-СЕКРЕТНОЕ\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert all(e["name"] != "example" for e in rep["environments"])

    def test_secret_names_from_env_example(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "# комментарий\nANTHROPIC_API_KEY=sk-СЕКРЕТНОЕ-ЗНАЧЕНИЕ-НЕ-ДОЛЖНО-УТЕЧЬ\n"
            "EMPTY=\nBAD LINE WITHOUT EQ\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert rep["secret_names"] == ["ANTHROPIC_API_KEY", "EMPTY"]

    def test_secret_values_not_in_report(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "ANTHROPIC_API_KEY=sk-СЕКРЕТНОЕ-ЗНАЧЕНИЕ-НЕ-ДОЛЖНО-УТЕЧЬ\n", encoding="utf-8")
        rep = assess(tmp_path)
        blob = json.dumps(rep, ensure_ascii=False)
        assert "СЕКРЕТНОЕ" not in blob and "sk-" not in blob

    def test_bad_line_does_not_break(self, tmp_path):
        (tmp_path / ".env.example").write_text("BAD LINE WITHOUT EQ\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert "BAD" not in rep["secret_names"]


@pytest.mark.unit
class TestAssessRobustness:
    def test_broken_workflow_does_not_crash(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "broken.yml").write_text("{{ это не yaml\n", encoding="utf-8")
        (wf / "ok.yml").write_text("jobs:\n  a:\n    environment: {name: staging}\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert [e["name"] for e in rep["environments"]] == ["staging"]

    def test_environment_list_parsed(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ok.yml").write_text("jobs:\n  a:\n    environment: {name: staging}\n", encoding="utf-8")
        (wf / "list.yml").write_text("jobs:\n  b:\n    environment: [prod-a]\n", encoding="utf-8")
        assert any(e["name"] == "prod-a" for e in assess(tmp_path)["environments"])

    def test_broken_ai_ops_yaml(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ok.yml").write_text("jobs:\n  a:\n    environment: {name: staging}\n", encoding="utf-8")
        (tmp_path / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        assert assess(tmp_path)["counts"]["declared"] == 0


@pytest.mark.unit
class TestAssessConfigFormats:
    def test_string_environments(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [prod, staging]\n", encoding="utf-8")
        rep = assess(tmp_path)
        assert {e["name"] for e in rep["environments"]} == {"prod", "staging"}

    def test_unknown_kind_in_config(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n    - {name: x, kind: чепуха}\n",
            encoding="utf-8")
        assert assess(tmp_path)["environments"][0]["kind"] == "unknown"
