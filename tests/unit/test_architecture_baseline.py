"""Гранулярные тесты architecture_baseline (мигрировано из test_architecture_baseline_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from architecture_baseline import (
    AXES,
    Path,
    analyze,
    check,
)


@pytest.mark.unit
class TestAnalyzeEmptyRepo:
    @pytest.fixture
    def baseline(self, tmp_path):
        return analyze(str(tmp_path), sha="deadbeef")

    def test_all_12_axes_present(self, baseline):
        assert all(ax in baseline for ax in AXES)

    def test_check_valid_on_empty_tree(self, baseline):
        assert check(baseline) == []

    def test_module_map_not_detected(self, baseline):
        assert baseline["module_map"]["top_level_code_dirs"] == "not_detected"

    def test_risk_for_missing_adr(self, baseline):
        assert any("ADR" in r for r in baseline["risks"])

    def test_sha_marked(self, baseline):
        assert baseline["sha"] == "deadbeef"


@pytest.mark.unit
class TestAnalyzeRealTree:
    @pytest.fixture
    def baseline(self, tmp_path):
        root = tmp_path
        (root / "src" / "features").mkdir(parents=True)
        (root / "src" / "shared").mkdir(parents=True)
        (root / "src" / "features" / "api.ts").write_text(
            "import { z } from 'zod';\nconst r = router.get('/x', () => {});\n", encoding="utf-8")
        (root / "package.json").write_text(
            '{"dependencies":{"anthropic":"^1","zod":"^3"},"devDependencies":{"vitest":"^1"}}',
            encoding="utf-8")
        (root / "migrations").mkdir()
        (root / "Dockerfile").write_text("FROM node", encoding="utf-8")
        return analyze(str(root), sha="abc123")

    def test_fsd_boundary_detected(self, baseline):
        assert "FSD (feature-sliced)" in baseline["boundaries"]["detected"]

    def test_node_deps_counted(self, baseline):
        assert baseline["dependencies"]["node"]["dependencies"] == 2

    def test_express_route_detected(self, baseline):
        assert "express route" in baseline["api_surface"]

    def test_migrations_detected(self, baseline):
        assert "migrations" in baseline["data_and_migrations"]["migration_dirs"]

    def test_anthropic_sdk_integration(self, baseline):
        assert "anthropic" in baseline["integrations"]["sdk_providers"]

    def test_dockerfile_in_deployment(self, baseline):
        assert "Dockerfile" in baseline["deployment"]["deploy_configs"]

    def test_input_validation_present(self, baseline):
        assert baseline["security_boundaries"]["input_validation_present"]

    def test_check_valid_on_real_tree(self, baseline):
        assert check(baseline) == []


@pytest.mark.unit
class TestSecretsHonesty:
    def test_env_only_names_no_secret_values(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "ANTHROPIC_API_KEY=sk-REAL-SECRET-VALUE\nDB_URL=x\n", encoding="utf-8")
        b = analyze(str(tmp_path))
        names = b["integrations"].get("env_var_names", [])
        assert "ANTHROPIC_API_KEY" in names
        assert not any("sk-REAL" in str(x) for x in names)
