"""Гранулярные тесты product_templates (мигрировано из test_product_templates_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import product_templates as PT

REG = AR.load()


def _write_passport(path, version=1, drop_section=None):
    art = AR.artifact(REG, "product_passport")
    lines = [] if version is None else [f"<!-- template-version: {version} -->"]
    lines.append("# Product Passport")
    for sec in art["structure"]["required_sections"]:
        if sec == drop_section:
            continue
        lines.append(f"## {sec}")
        lines.append("наполнено фактом")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── positive ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPositive:
    def test_real_templates_cover_registry_and_are_valid(self):
        assert PT.check(REG) == []

    def test_every_registry_template_file_exists(self):
        for a in AR.artifacts(REG):
            tpl = a.get("template")
            if tpl:
                assert (PT.PKG / tpl["path"]).is_file(), f"нет файла шаблона для {a['id']}"

    def test_full_instance_is_valid(self, tmp_path):
        d = tmp_path / ".ai-ops"
        d.mkdir()
        _write_passport(d / "PRODUCT_PASSPORT.md", version=1)
        art = AR.artifact(REG, "product_passport")
        assert PT.state_of(tmp_path, art, REG)["state"] == PT.VALID


# ── fail-closed ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFailClosed:
    def test_check_flags_missing_template(self, tmp_path):
        errs = PT.check(REG, pkg_root=tmp_path)
        assert any("шаблон не найден" in x for x in errs)

    def test_check_flags_missing_required_section(self, tmp_path):
        tdir = tmp_path / "templates" / "product-layer"
        tdir.mkdir(parents=True)
        (tdir / "PRODUCT_PASSPORT.md").write_text(
            "<!-- template-version: 1 -->\n# П\n## Owner и команда\n", encoding="utf-8")
        reg = {"registry_type": "artifact-registry", "artifacts": [{
            "id": "product_passport", "kind": "document", "format": "markdown",
            "template": {"path": "templates/product-layer/PRODUCT_PASSPORT.md", "version": 1},
            "structure": {"required_sections": ["Owner и команда", "Риски и зависимости"]}}]}
        errs = PT.check(reg, pkg_root=tmp_path)
        assert any("Риски и зависимости" in x for x in errs)

    def test_version_bump_without_migration_is_flagged(self, tmp_path):
        tdir = tmp_path / "templates" / "product-layer"
        tdir.mkdir(parents=True)
        (tdir / "P.md").write_text("<!-- template-version: 2 -->\n# П\n", encoding="utf-8")
        reg = {"registry_type": "artifact-registry", "artifacts": [{
            "id": "product_passport", "kind": "document", "format": "markdown",
            "template": {"path": "templates/product-layer/P.md", "version": 2},
            "structure": {}}]}
        errs = PT.check(reg, pkg_root=tmp_path)
        assert any("миграци" in x and "v1->v2" in x for x in errs)

    def test_missing_instance_is_missing(self, tmp_path):
        art = AR.artifact(REG, "product_passport")
        assert PT.state_of(tmp_path, art, REG)["state"] == PT.MISSING


# ── side-effect ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSideEffect:
    def test_incomplete_instance_is_invalid(self, tmp_path):
        d = tmp_path / ".ai-ops"
        d.mkdir()
        _write_passport(d / "PRODUCT_PASSPORT.md", version=1, drop_section="Риски и зависимости")
        art = AR.artifact(REG, "product_passport")
        st = PT.state_of(tmp_path, art, REG)
        assert st["state"] == PT.INVALID
        assert "Риски и зависимости" in st["reason"]

    def test_outdated_version_is_outdated(self, tmp_path):
        d = tmp_path / ".ai-ops"
        d.mkdir()
        art = dict(AR.artifact(REG, "product_passport"))
        art["template"] = dict(art["template"], version=2)
        _write_passport(d / "PRODUCT_PASSPORT.md", version=1)
        assert PT.state_of(tmp_path, art, REG)["state"] == PT.OUTDATED

    def test_yaml_missing_field_is_invalid(self, tmp_path):
        d = tmp_path / ".ai-ops"
        d.mkdir()
        (d / "POLICY.yaml").write_text("template_version: 1\nschema_version: 1\n", encoding="utf-8")
        art = AR.artifact(REG, "policy")
        st = PT.state_of(tmp_path, art, REG)
        assert st["state"] == PT.INVALID
