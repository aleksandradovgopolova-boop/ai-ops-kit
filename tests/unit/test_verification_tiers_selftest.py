"""Селфтест verification_tiers, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from verification_tiers import (  # noqa: F401 — имена, которые использует тело
    IMPACT_DOCS_ONLY,
    IMPACT_TARGETED_TESTS_FOUND,
    IMPACT_TARGETED_TESTS_NOT_FOUND,
    Path,
    decide_tier,
    select_tests,
)


@pytest.mark.slow
def test_verification_tiers_selftest():
    """Selftest: контракты и логика."""
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1. decide_tier: критическая инфраструктура -> full
    tier = decide_tier(["tools/orchestrator.py"])
    expect("decide_tier: orchestrator.py -> full", tier == "full")

    # 2. decide_tier: документация -> skip (v3.27.3 WP4)
    tier = decide_tier(["README.md", "docs/guide.md"])
    expect("decide_tier: docs -> skip", tier == "skip")

    # 3. decide_tier: много файлов -> module
    tier = decide_tier([f"tools/file{i}.py" for i in range(25)])
    expect("decide_tier: 25 files -> module", tier == "module")

    # 4. decide_tier: обычный файл -> affected
    tier = decide_tier(["tools/usage_ledger.py"])
    expect("decide_tier: обычный файл -> affected", tier == "affected")

    # 5. decide_tier: force_tier
    tier = decide_tier(["README.md"], force_tier="full")
    expect("decide_tier: force_tier=full -> full", tier == "full")

    # 6. decide_tier: lifecycle_intent (v3.27.3 WP4)
    tier = decide_tier(["tools/usage_ledger.py"], lifecycle_intent="explore")
    expect("decide_tier: lifecycle_intent=explore -> skip", tier == "skip")
    tier = decide_tier(["tools/usage_ledger.py"], lifecycle_intent="merge_candidate")
    expect("decide_tier: lifecycle_intent=merge_candidate -> full", tier == "full")

    # 7. select_tests: skip tier для docs (v3.27.3 WP4)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        result = select_tests(["README.md"], str(root))
        expect("select_tests: docs -> skip tier", result["tier"] == "skip")
        expect("select_tests: docs -> impact_status=docs_only", result["impact_status"] == IMPACT_DOCS_ONLY)

    # 8. select_tests: impact_unknown (v3.27.3 WP4)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
        # Нет тестов -> impact_unknown
        result = select_tests(["tools/module.py"], str(root))
        expect("select_tests: нет тестов -> impact_status=targeted_tests_not_found",
               result["impact_status"] == IMPACT_TARGETED_TESTS_NOT_FOUND)

    # 9. select_tests: targeted tests found
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
        (root / "tools" / "test_module.py").write_text("import module\ndef test_func(): assert module.func() == 1\n", encoding="utf-8")
        result = select_tests(["tools/module.py"], str(root))
        expect("select_tests: affected tier", result["tier"] == "affected")
        expect("select_tests: test_module.py в affected_tests", "tools/test_module.py" in (result["affected_tests"] or []))
        expect("select_tests: impact_status=targeted_tests_found", result["impact_status"] == IMPACT_TARGETED_TESTS_FOUND)

    # 10. select_tests: full для критической инфраструктуры
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "orchestrator.py").write_text("def run(): pass\n", encoding="utf-8")
        result = select_tests(["tools/orchestrator.py"], str(root))
        expect("select_tests: orchestrator -> full tier", result["tier"] == "full")
        expect("select_tests: full_command=True", result["full_command"] is True)

    assert ok, "перенесённый селфтест verification_tiers: см. строки FAIL в выводе"
