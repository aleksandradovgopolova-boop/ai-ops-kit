"""Селфтест context_engine, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_engine import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_BUDGET_TOKENS,
    Path,
    _git,
    budget_tokens_from,
    build_context,
    compare_v1,
    load_child_policies,
    yaml,
)


@pytest.mark.slow
def test_context_engine_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir(parents=True)
        # pricing.py + order.py (order импортит pricing -> граф-сосед); notes.md (docs); secret.py
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a * 0.9  # discount\n", encoding="utf-8")
        # order.py импортит pricing, но НЕ содержит слова 'discount' -> найдётся ТОЛЬКО через граф
        (root / "src" / "order.py").write_text("import pricing\n# fulfillment flow\n", encoding="utf-8")
        (root / "src" / "Widget.tsx").write_text("// discount widget\nexport const W = () => 'discount';\n", encoding="utf-8")
        (root / "docs.md").write_text("# discount guide\n", encoding="utf-8")
        (root / "secret.py").write_text("# token sk-ant-api03deadbeefdeadbeef discount\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# governing policy (mandatory v1) discount rules\n", encoding="utf-8")
        # политики CHILD (не демо кита)
        pol = root / ".ai" / "policies"
        pol.mkdir(parents=True)
        (pol / "access-filter.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-AFP", "kind": "AccessFilterPolicy",
            "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}), encoding="utf-8")
        (pol / "data-classification.yaml").write_text(yaml.safe_dump({
            "id": "CHILD-DCP", "kind": "DataClassificationPolicy", "default_class": "internal",
            "rules": [{"path_prefix": "secret.py", "class": "confidential"}]}), encoding="utf-8")

        afp, dcp, budget = load_child_policies(root)
        expect("load_child_policies читает CHILD AFP/DCP (не демо)",
               afp and afp["id"] == "CHILD-AFP" and dcp and dcp["id"] == "CHILD-DCP")

        # без sha -> отказ (exact-revision)
        try:
            build_context(root, "discount", "executor", sha=None, afp=afp, dcp=dcp)
            expect("без SHA -> ValueError", False)
        except ValueError:
            expect("без SHA -> ValueError (view не строится)", True)

        v = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                          budget_tokens=10000, v1_mandatory=["POLICY.md"])
        inc = {i["file"] for i in v["included"]}
        exa = {e["file"] for e in v["excluded_access"]}

        expect("полная цепочка: full-text охватывает .py/.tsx/.md",
               {"src/pricing.py", "src/Widget.tsx", "docs.md"} <= inc)
        expect("graph augmentation ДОБАВИЛ соседа order.py (импортит pricing) без ключевого слова 'discount' в имени",
               "src/order.py" in inc and v["sources_used"]["graph_added"] >= 1)
        expect("обязательный контекст v1 POLICY.md присутствует (source mandatory-v1, первым)",
               "POLICY.md" in inc and v["included"][0]["mandatory"] is True)
        # v3.7.0: denied-по-пути secret.py PRE-FILTERED — НЕ читается, НЕ в payload, НЕ в read_paths
        expect("denied-по-пути secret.py pre-filtered (не читается, имя не в role-facing payload)",
               "secret.py" in v["pre_filtered_denied"] and "secret.py" not in inc
               and "secret.py" not in exa and "secret.py" not in v["read_paths"])
        expect("каждый included несёт content_hash + sha + reason",
               all(i.get("content_hash") and i["sha"] == "abc123" and i.get("reason") for i in v["included"]))
        expect("cache_key привязан к sha + AFP + DCP child (не демо)",
               "sha:abc123" in v["cache_key"] and "afp:CHILD-AFP" in v["cache_key"]
               and "dcp:CHILD-DCP" in v["cache_key"])

        # graph/semantic ТОЛЬКО добавляют — детерминированные full-text не исчезают
        expect("graph/semantic не удаляют детерминированные full-text кандидаты",
               {"src/pricing.py", "docs.md"} <= inc)

        # обязательный контекст не теряется даже при крошечном бюджете
        vb = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                           budget_tokens=1, v1_mandatory=["POLICY.md"])
        expect("обязательный v1 не теряется на budget (включён, флаг over_budget)",
               any(i["file"] == "POLICY.md" and i.get("over_budget") for i in vb["included"]))

        # deny-by-default: нет AFP -> ничего не включается (никакого demo-fallback)
        vdeny = build_context(root, "discount", "executor", sha="abc123", afp=None, dcp=dcp)
        expect("нет AFP (child не дал политику) -> deny-by-default, included пуст (no demo)",
               vdeny["included"] == [])

        # условный semantic: узкий запрос с малым recall -> semantic задействован
        vsem = build_context(root, "rebate", "executor", sha="abc123", afp=afp, dcp=dcp)
        expect("узкий запрос (recall < floor) -> semantic_used=True с reason",
               vsem["sources_used"]["semantic_used"] is True and "floor" in vsem["sources_used"]["semantic_reason"])

        # широкий запрос с достаточным recall -> semantic НЕ вызывается
        vwide = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        expect("достаточный recall -> semantic НЕ вызывается (условность соблюдена)",
               vwide["sources_used"]["semantic_used"] is False)

        # сравнение с v1 (shadow)
        cmp = compare_v1(v, ["POLICY.md", "legacy/old.py"])
        expect("compare_v1: overlap/v1_only/v2_only",
               "POLICY.md" in cmp["overlap"] and "legacy/old.py" in cmp["v1_only"] and cmp["v2_only"])

        # === v3.6.7d: обязательный контекст блокирует view ===
        vmiss = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                              v1_mandatory=["does/not/exist.md"])
        expect("обязательный v1 отсутствует в snapshot -> valid=false (execution не получит контекст)",
               vmiss["valid"] is False and vmiss["mandatory_missing"] == ["does/not/exist.md"])
        vexcl = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp,
                              v1_mandatory=["secret.py"])
        expect("обязательный v1 запрещён access-policy (secret) -> valid=false",
               vexcl["valid"] is False and "secret.py" in vexcl["mandatory_excluded_access"])

        # budget из настоящего BudgetContract
        expect("budget_tokens_from читает scope run из контракта",
               budget_tokens_from({"scopes": [{"scope": "run", "token_budget": 1234}]}, "run") == 1234)
        expect("budget_tokens_from дефолт при отсутствии", budget_tokens_from(None) == DEFAULT_BUDGET_TOKENS)

        # .gitignore-aware исключения
        (root / ".gitignore").write_text("generated\n", encoding="utf-8")
        (root / "generated").mkdir()
        (root / "generated" / "big.py").write_text("# discount generated\n", encoding="utf-8")
        vgi = build_context(root, "discount", "executor", sha="abc123", afp=afp, dcp=dcp)
        expect(".gitignore-aware: каталог 'generated' исключён из retrieval",
               all("generated/" not in i["file"] for i in vgi["included"]))

    # === v3.6.7d: ДОКАЗАТЕЛЬСТВО snapshot через настоящий git ===
    with tempfile.TemporaryDirectory() as gtd:
        g = Path(gtd)
        (g / "app.py").write_text("# discount logic here\n", encoding="utf-8")
        pol = g / ".ai" / "policies"
        pol.mkdir(parents=True)
        (pol / "access-filter.yaml").write_text(yaml.safe_dump({
            "id": "G-AFP", "kind": "AccessFilterPolicy",
            "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}), encoding="utf-8")
        (g / ".gitignore").write_text(".ai/\n", encoding="utf-8")   # .ai/ — engine state, вне git (как в реальном child)
        _git(g, "init", "-q")
        _git(g, "add", "app.py", ".gitignore")
        rc, _, _ = _git(g, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "init")
        _, head, _ = _git(g, "rev-parse", "HEAD")
        if rc == 0 and head:
            afpg, _, _ = load_child_policies(g)
            vok = build_context(g, "discount", "executor", sha=head, afp=afpg, require_snapshot=True)
            expect("git snapshot: HEAD==sha + чистое дерево -> valid + snapshot_verified",
                   vok["valid"] is True and vok["snapshot_verified"] is True)
            vwrong = build_context(g, "discount", "executor", sha="0" * 40, afp=afpg, require_snapshot=True)
            expect("git snapshot: HEAD != sha -> valid=false (читается не тот snapshot)",
                   vwrong["valid"] is False and vwrong["snapshot_verified"] is False)
            (g / "app.py").write_text("# discount logic CHANGED (dirty)\n", encoding="utf-8")
            vdirty = build_context(g, "discount", "executor", sha=head, afp=afpg, require_snapshot=True)
            expect("git snapshot: грязное дерево -> valid=false (нельзя подписать dirty чужим SHA)",
                   vdirty["valid"] is False)

    assert ok, "перенесённый селфтест context_engine: см. строки FAIL в выводе"
