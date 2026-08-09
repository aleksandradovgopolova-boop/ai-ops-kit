"""Селфтест context_cost, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_cost import (  # noqa: F401 — имена, которые использует тело
    Path,
    estimate,
    estimate_tokens,
    summary_line,
)


@pytest.mark.slow
def test_context_cost_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # кириллица дороже латиницы в оценке
    expect("кириллица оценивается дороже латиницы (посимвольно)",
           estimate_tokens("абвг" * 25) > estimate_tokens("abcd" * 25))
    expect("пустой текст -> 0 токенов", estimate_tokens("") == 0)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cc = root / ".ai/project/context/product"
        cc.mkdir(parents=True)
        (cc.parent / "now.md").write_text("---\nread_tier: 1\n---\n" + "снимок " * 50, encoding="utf-8")
        (cc / "ProductStatus.md").write_text("---\nread_tier: 1\n---\n" + "статус " * 50, encoding="utf-8")
        (cc / "MetricCatalog.md").write_text("---\nread_tier: 3\n---\n" + "метрика " * 500, encoding="utf-8")
        (root / "CLAUDE.md").write_text("правила " * 30, encoding="utf-8")
        sk = root / ".claude/skills/demo"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: demo\ndescription: короткое описание скилла\n---\n# тело",
                                     encoding="utf-8")
        (root / ".ai-ops.yaml").write_text("context_budget:\n  session_start_tokens: 200\n", encoding="utf-8")

        rep = estimate(td)
        tier1_paths = [i["path"] for i in rep["items"] if i["bucket"] == "tier1_context"]
        expect("ярус 1 включает now.md + ProductStatus.md", len(tier1_paths) == 2)
        expect("ярус 3 (MetricCatalog) НЕ входит в стартовый набор",
               not any("MetricCatalog" in p for p in tier1_paths))
        expect("CLAUDE.md учтён", "claude_md" in rep["buckets"])
        expect("описание скилла учтено (по frontmatter description)",
               rep["buckets"].get("skill_descriptions", 0) > 0)
        expect("бюджет читается из .ai-ops.yaml (200)", rep["budget"] == 200)
        expect("превышение малого бюджета детектируется",
               rep["total_tokens"] > 200 and rep["within_budget"] is False)
        expect("--budget override работает", estimate(td, budget=10_000)["within_budget"] is True)
        expect("summary_line непустая", "стоимость старта" in summary_line(td))

    assert ok, "перенесённый селфтест context_cost: см. строки FAIL в выводе"
