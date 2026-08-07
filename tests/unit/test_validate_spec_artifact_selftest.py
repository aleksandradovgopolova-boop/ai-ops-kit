"""Селфтест validate_spec_artifact, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_spec_artifact import (  # noqa: F401 — имена, которые использует тело
    Path,
    check,
    provided_evidence,
    render,
)


@pytest.mark.slow
def test_validate_spec_artifact_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"schema_version": 1, "kind": "spec-change", "capability": "pricing",
            "why": "нужна утилита цены", "what_changes": ["добавить formatPrice"],
            "tasks": ["реализовать", "покрыть тестом"],
            "requirements": [{"name": "Price formatting",
                              "text": "The system SHALL format an integer price with thousand separators.",
                              "scenarios": [{"name": "Thousands", "when": "formatPrice(1000)", "then": "returns 1 000"}]}]}
    expect("валидный spec-change -> без ошибок", check(good) == [])
    expect("валидный -> requirements_covered предоставлен", provided_evidence(good) == ["requirements_covered"])
    expect("плохой capability -> ошибка", any("capability" in e for e in check({**good, "capability": "Bad Cap"})))
    expect("требование без scenarios -> ошибка",
           any("scenarios" in e for e in check({**good, "requirements": [{"name": "x", "text": "SHALL y"}]})))
    expect("scenario без then -> ошибка",
           any("when + then" in e for e in check({**good, "requirements": [
               {"name": "x", "text": "SHALL y", "scenarios": [{"when": "a"}]}]})))
    expect("невалидный -> evidence пуст", provided_evidence({"kind": "spec-change"}) == [])

    # render пишет корректный OpenSpec-markdown
    with tempfile.TemporaryDirectory() as td:
        written = render(good, Path(td) / "openspec", "feat-x")
        expect("render: 3 файла (proposal/tasks/spec)", len(written) == 3)
        spec_txt = (Path(td) / "openspec" / "changes" / "feat-x" / "specs" / "pricing" / "spec.md").read_text(encoding="utf-8")
        expect("render: spec содержит '## ADDED Requirements'", "## ADDED Requirements" in spec_txt)
        expect("render: spec содержит '### Requirement:' и WHEN/THEN",
               "### Requirement: Price formatting" in spec_txt and "- WHEN" in spec_txt and "- THEN" in spec_txt)
        prop = (Path(td) / "openspec" / "changes" / "feat-x" / "proposal.md").read_text(encoding="utf-8")
        expect("render: proposal содержит Why/What Changes/Impact",
               "## Why" in prop and "## What Changes" in prop and "## Impact" in prop)

    assert ok, "перенесённый селфтест validate_spec_artifact: см. строки FAIL в выводе"
