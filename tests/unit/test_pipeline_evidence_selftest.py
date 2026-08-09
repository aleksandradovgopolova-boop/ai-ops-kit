"""Селфтест pipeline_evidence, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from pipeline_evidence import (  # noqa: F401 — имена, которые использует тело
    _author_with_retry,
    _install_dependencies,
    _reevaluate_artifact_evidence,
    _review_security,
    _run_authoring,
    _run_reviews,
)


@pytest.mark.slow
def test_pipeline_evidence_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("pipeline_evidence: imports work", True)
    expect("pipeline_evidence: _install_dependencies is callable", callable(_install_dependencies))
    expect("pipeline_evidence: _author_with_retry is callable", callable(_author_with_retry))
    expect("pipeline_evidence: _run_authoring is callable", callable(_run_authoring))
    expect("pipeline_evidence: _run_reviews is callable", callable(_run_reviews))
    expect("pipeline_evidence: _review_security is callable", callable(_review_security))
    expect("pipeline_evidence: _reevaluate_artifact_evidence is callable", callable(_reevaluate_artifact_evidence))

    assert ok, "перенесённый селфтест pipeline_evidence: см. строки FAIL в выводе"
