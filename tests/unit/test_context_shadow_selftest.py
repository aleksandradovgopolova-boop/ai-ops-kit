"""Селфтест context_shadow, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_shadow import (  # noqa: F401 — имена, которые использует тело
    Path,
    build_shadow,
    ce,
    compare,
)


@pytest.mark.slow
def test_context_shadow_selftest():
    import tempfile
    import yaml
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def _mkrepo(root, with_policies=True):
        (root / "src").mkdir(parents=True)
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9  # discount\n", encoding="utf-8")
        (root / "src" / "order.py").write_text("import pricing\n# discount order flow\n", encoding="utf-8")
        (root / ".gitignore").write_text(".ai/\n", encoding="utf-8")
        pol = root / ".ai" / "policies"
        pol.mkdir(parents=True)
        (pol / "state.py").write_text("# discount secret internal state\n", encoding="utf-8")
        if with_policies:
            (pol / "access-filter.yaml").write_text(yaml.safe_dump({
                "id": "CHILD-AFP", "kind": "AccessFilterPolicy",
                "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}), encoding="utf-8")
            (pol / "data-classification.yaml").write_text(yaml.safe_dump({
                "id": "CHILD-DCP", "kind": "DataClassificationPolicy", "default_class": "internal"}),
                encoding="utf-8")
            (pol / "budget.yaml").write_text(yaml.safe_dump({
                "id": "CHILD-BUD", "kind": "BudgetContract",
                "scopes": [{"scope": "run", "token_budget": 15000}]}), encoding="utf-8")
        ce._git(root, "init", "-q")
        ce._git(root, "add", "src", ".gitignore")
        ce._git(root, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "init")
        _, head, _ = ce._git(root, "rev-parse", "HEAD")
        return head

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        head = _mkrepo(root)

        sh = build_shadow(root, "discount", role="executor", sha=head)
        expect("shadow: mode=shadow, execution_uses=v1 (не управляет прогоном)",
               sh["mode"] == "shadow" and sh["execution_uses"] == "context_compiler_v1")
        expect("shadow валиден + snapshot доказан (HEAD==sha, чистое дерево)",
               sh["valid"] is True and sh["snapshot_verified"] is True)
        expect("shadow строит ПОЛНУЮ цепочку (sources_used: fulltext + graph)",
               sh["sources_used"]["fulltext"] >= 1 and "graph_added" in sh["sources_used"])
        expect("shadow находит src/*.py по 'discount'", "src/order.py" in sh["included"])
        expect("shadow НЕ сканирует скрытые .ai/ (engine state вне контекста)",
               all(not f.startswith(".ai") for f in sh["included"]))
        expect("shadow budget взят из child BudgetContract (15000, не жёсткие 20000)",
               sh["budget_tokens"] == 15000)
        expect("shadow.cache_key привязан к sha + child-политикам (exact-revision, no demo)",
               f"sha:{head}" in sh["cache_key"] and "afp:CHILD-AFP" in sh["cache_key"])

        cmp = compare(sh, ["src/pricing.py", "docs/legacy.md"])
        expect("compare: overlap/v1_only/v2_only считаются",
               "src/pricing.py" in cmp["overlap"] and "docs/legacy.md" in cmp["v1_only"])

        # snapshot не доказан (грязное дерево) -> shadow невалиден
        (root / "src" / "pricing.py").write_text("# dirty change\n", encoding="utf-8")
        shd = build_shadow(root, "discount", sha=head)
        expect("грязное дерево -> shadow.valid=false (snapshot не доказан)", shd["valid"] is False)

        # без точного SHA shadow НЕ строится
        try:
            build_shadow(root, "discount", sha=None)
            expect("без SHA shadow НЕ строится -> ValueError", False)
        except ValueError:
            expect("без SHA shadow НЕ строится -> ValueError", True)

    # нет child-политики -> deny-by-default (никакого demo-fallback в runtime)
    with tempfile.TemporaryDirectory() as td2:
        r2 = Path(td2)
        head2 = _mkrepo(r2, with_policies=False)
        sh2 = build_shadow(r2, "discount", sha=head2)
        expect("нет child-AFP -> deny-by-default, ничего не включается (no demo policy в runtime)",
               sh2["included_count"] == 0)

    assert ok, "перенесённый селфтест context_shadow: см. строки FAIL в выводе"
