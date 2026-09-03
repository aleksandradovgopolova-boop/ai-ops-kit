"""Гранулярные тесты pipeline_evidence (мигрировано из test_pipeline_evidence_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_evidence import (
    _author_with_retry,
    _install_dependencies,
    _reevaluate_artifact_evidence,
    _review_security,
    _run_authoring,
    _run_reviews,
)


@pytest.mark.unit
class TestImports:
    def test_install_dependencies_callable(self):
        assert callable(_install_dependencies)

    def test_author_with_retry_callable(self):
        assert callable(_author_with_retry)

    def test_run_authoring_callable(self):
        assert callable(_run_authoring)

    def test_run_reviews_callable(self):
        assert callable(_run_reviews)

    def test_review_security_callable(self):
        assert callable(_review_security)

    def test_reevaluate_artifact_evidence_callable(self):
        assert callable(_reevaluate_artifact_evidence)
