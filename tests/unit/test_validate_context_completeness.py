"""Гранулярные тесты validate_context_completeness (миграция с селфтеста)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_context_completeness import (
    PKG,
    check_completeness,
    required_docs,
    yaml,
)


@pytest.mark.unit
@pytest.mark.slow
class TestContextCompleteness:

    def test_empty_repo_all_missing(self):
        req = ["product/ProductStatus.md", "now.md"]
        with tempfile.TemporaryDirectory() as td:
            r = check_completeness(td, required=req)
            assert r["missing"] == req and not r["complete"]

    def test_both_in_project_context_complete(self):
        req = ["product/ProductStatus.md", "now.md"]
        with tempfile.TemporaryDirectory() as td:
            pc = Path(td) / ".ai/project/context"
            (pc / "product").mkdir(parents=True)
            (pc / "product" / "ProductStatus.md").write_text("x", encoding="utf-8")
            (pc / "now.md").write_text("x", encoding="utf-8")
            r = check_completeness(td, required=req)
            assert r["complete"] and not r["missing"]

    def test_custom_context_partial(self):
        req = ["product/ProductStatus.md", "now.md"]
        with tempfile.TemporaryDirectory() as td:
            cc = Path(td) / ".ai/custom/context"
            cc.mkdir(parents=True)
            (cc / "now.md").write_text("x", encoding="utf-8")
            r = check_completeness(td, required=req)
            assert "now.md" in r["present"] and "product/ProductStatus.md" in r["missing"]

    def test_required_docs_reads_kit_manifest(self):
        assert len(required_docs()) >= 1

    def test_managed_only_not_counted(self):
        req = ["product/ProductStatus.md", "now.md"]
        with tempfile.TemporaryDirectory() as td:
            mc = Path(td) / ".ai/managed/context"
            (mc / "product").mkdir(parents=True)
            (mc / "product" / "ProductStatus.md").write_text("x", encoding="utf-8")
            (mc / "now.md").write_text("x", encoding="utf-8")
            r = check_completeness(td, required=req)
            assert r["missing"] == req

    def test_all_kit_context_templates_have_read_tier(self):
        """v3.13.0 Startup Context Budget: все шаблоны context/ размечены read_tier."""
        missing_tier = []
        ctx = PKG / "context"
        if ctx.is_dir():
            for p in sorted(ctx.rglob("*.md")):
                txt = p.read_text(encoding="utf-8", errors="replace")
                fm = {}
                if txt.startswith("---"):
                    seg = txt.split("---", 2)
                    if len(seg) >= 3:
                        try:
                            fm = yaml.safe_load(seg[1]) or {}
                        except yaml.YAMLError:
                            fm = {}
                if fm.get("read_tier") not in (1, 2, 3):
                    missing_tier.append(p.relative_to(ctx).as_posix())
        assert not missing_tier, f"без read_tier: {', '.join(missing_tier)}"
