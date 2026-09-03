"""Гранулярные тесты pipeline_git (мигрировано из test_pipeline_git_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_git import (
    _git,
    _has_changes,
    _resolve_base,
    _tree_clean,
)


@pytest.mark.unit
class TestImports:
    def test_git_callable(self):
        assert callable(_git)

    def test_has_changes_callable(self):
        assert callable(_has_changes)

    def test_tree_clean_callable(self):
        assert callable(_tree_clean)

    def test_resolve_base_callable(self):
        assert callable(_resolve_base)
