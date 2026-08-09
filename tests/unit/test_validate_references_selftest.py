"""Селфтест validate_references, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_references import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    check,
    tempfile,
)


@pytest.mark.slow
def test_validate_references_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1) реальный пакет: ссылок быть не должно
    real = check(PKG)
    expect("реальный пакет без висячих ссылок", real == [])

    # 2) искусственный слом: гейт видят падающим (принцип team-os)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "registry").mkdir(parents=True)
        (root / "quality").mkdir()
        (root / "manifest").mkdir()
        (root / "rules").mkdir()
        (root / "skills").mkdir()
        (root / "registry" / "agents.yaml").write_text(
            "agents:\n  - id: real-agent\n", encoding="utf-8")
        (root / "quality" / "gates.yaml").write_text(
            "gates:\n  real_gate: {id: real_gate}\n", encoding="utf-8")
        (root / "manifest" / "ai-ops-manifest.yaml").write_text(
            "skills:\n  shipped:\n    - id: real-skill\n      path: skills/real-skill/SKILL.md\n"
            "update_policy:\n  updater: installer/does_not_exist.py\n",   # протухший путь
            encoding="utf-8")
        (root / "skills" / "real-skill").mkdir()
        (root / "skills" / "real-skill" / "SKILL.md").write_text(
            "---\nname: real-skill\nchecklist: rules/missing.yaml\n---\n", encoding="utf-8")
        (root / "registry" / "workflows.yaml").write_text(
            "workflows:\n"
            "  W:\n"
            "    quality_gates: [ghost_gate]\n"
            "    stages:\n"
            "      - {id: s1, owner: ghost-agent, uses_skills: [ghost-skill]}\n",
            encoding="utf-8")
        f = check(root)
        kinds = {x["kind"] for x in f}
        expect("ловит несуществующий gate", "gate" in kinds)
        expect("ловит несуществующего agent", "agent" in kinds)
        expect("ловит несуществующий skill", "skill" in kinds)
        expect("ловит битый checklist-путь", "path" in kinds)
        expect("deep-research (внешний) НЕ ложно-битый",
               all(x["ref"] != "deep-research" for x in f))
        expect("ловит протухший путь в манифесте", "manifest-path" in kinds)

    assert ok, "перенесённый селфтест validate_references: см. строки FAIL в выводе"
