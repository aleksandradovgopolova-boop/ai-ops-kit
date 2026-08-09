"""Селфтест context_retrieval, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_retrieval import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    RetrievalCache,
    build_view,
    full_text_search,
    role_allowed_classes,
    yaml,
)


@pytest.mark.slow
def test_context_retrieval_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "a.py").write_text("# keyword foo appears foo twice\ndef alpha():\n    return 'foo'\n", encoding="utf-8")
        (root / "tools" / "b.py").write_text("# data-class: confidential\n# foo here once\n", encoding="utf-8")
        (root / "tools" / "c.py").write_text("# foo but has a secret sk-ant-api03xxxxxxxx\n", encoding="utf-8")
        (root / "tools" / "d.py").write_text("# nothing relevant here\n", encoding="utf-8")

        res = full_text_search(root, "foo", ("tools",))
        expect("full-text: a.py ранжирован выше (больше hits), d.py не найден",
               res[0]["file"] == "tools/a.py" and all(r["file"] != "tools/d.py" for r in res))

        # v3.6.7: full-text больше не Python-only — TS/React/docs/JSON тоже сканируются
        (root / "ui").mkdir()
        (root / "ui" / "Widget.tsx").write_text("// foo component\nexport const Widget = () => 'foo';\n", encoding="utf-8")
        (root / "ui" / "notes.md").write_text("# foo doc\n", encoding="utf-8")
        rts = full_text_search(root, "foo", ("ui",))
        expect("full-text охватывает .tsx и .md (не только .py)",
               {"ui/Widget.tsx", "ui/notes.md"} <= {r["file"] for r in rts})

        # v3.6.7d: vendored/generated каталоги исключены (node_modules и т.п.)
        (root / "node_modules" / "pkg").mkdir(parents=True)
        (root / "node_modules" / "pkg" / "index.js").write_text("// foo vendored\n", encoding="utf-8")
        rex = full_text_search(root, "foo", ("",))
        expect("full-text НЕ заходит в node_modules (hard-exclude)",
               all("node_modules" not in r["file"] for r in rex))

        # planner: allowed {public, internal}
        v = build_view(root, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        inc = {i["file"] for i in v["included"]}
        exa = {e["file"] for e in v["excluded_access"]}
        expect("planner видит internal a.py", "tools/a.py" in inc)
        expect("planner НЕ видит confidential b.py (access-filter)", "tools/b.py" in exa)
        expect("секрет c.py исключён ВСЕГДА (никогда в контекст)", "tools/c.py" in exa)

        # executor: allowed adds confidential -> b.py включён, но c.py (secret) всё равно нет
        v2 = build_view(root, "foo", "executor", {"public", "internal", "confidential"}, 10000)
        inc2 = {i["file"] for i in v2["included"]}
        exa2 = {e["file"] for e in v2["excluded_access"]}
        expect("executor видит confidential b.py", "tools/b.py" in inc2)
        expect("секрет c.py исключён и для executor (secret никогда)", "tools/c.py" in exa2)

        # budget: крошечный бюджет -> часть уходит в excluded_budget
        vb = build_view(root, "foo", "executor", {"public", "internal", "confidential"}, budget_tokens=1)
        expect("бюджет=1 -> включён максимум один файл, остальное excluded_budget",
               len(vb["included"]) <= 1 and (len(vb["excluded_budget"]) >= 1 or len(vb["included"]) == 0)
               and vb["total_tokens"] <= 1)

        # deny-by-default: пустой allowed -> ничего не включается
        vd = build_view(root, "foo", "nobody", set(), 10000)
        expect("deny-by-default: allowed пуст -> included пуст", vd["included"] == [])

        expect("cache_key содержит repo+sha+role+view",
               all(x in v["cache_key"] for x in ("repo:", "sha:", "role:", "view:")))

        # --- v3.6.3 cache trust-fixes ---
        def _afp(rules):
            return {"id": "AFP-T", "kind": "AccessFilterPolicy", "rules": rules}
        afp_wide = _afp([{"role": "executor", "allowed_classes": ["public", "internal", "confidential"]}])
        afp_narrow = _afp([{"role": "executor", "allowed_classes": ["public", "internal"]}])

        cache = RetrievalCache()
        vw, hw = cache.get_or_build(root, "foo", "executor", afp_wide, 10000, sha="s1")
        _, hw2 = cache.get_or_build(root, "foo", "executor", afp_wide, 10000, sha="s1")
        expect("cache: повтор (repo+sha+policy) -> hit, retrieval не пере-строен",
               hw is False and hw2 is True and cache.builds == 1)
        expect("wide-policy: confidential b.py включён в view", "tools/b.py" in {i["file"] for i in vw["included"]})

        # P0: ужесточение policy при тех же sha/query/budget -> НЕ старый permissive view
        vn, hn = cache.get_or_build(root, "foo", "executor", afp_narrow, 10000, sha="s1")
        expect("P0 access-leak: ужесточение policy -> cache MISS (не отдаёт старый view)", hn is False)
        expect("P0: после ужесточения confidential b.py НЕ в view (нет утечки)",
               "tools/b.py" not in {i["file"] for i in vn["included"]})

        # lookup ДО retrieval: hit не пере-строит
        builds_before = cache.builds
        cache.get_or_build(root, "foo", "executor", afp_narrow, 10000, sha="s1")
        expect("cache: hit НЕ пере-строит retrieval (builds не растёт)", cache.builds == builds_before)

        # exact-revision binding: без sha не кэшируем
        c2 = RetrievalCache()
        c2.get_or_build(root, "foo", "executor", afp_wide, 10000, sha=None)
        c2.get_or_build(root, "foo", "executor", afp_wide, 10000, sha=None)
        expect("exact-revision: без sha НЕ кэшируем (2 miss/2 build, 0 hit)",
               c2.misses == 2 and c2.builds == 2 and c2.hits == 0)

        # repo identity: одинаковое имя каталога, разные пути -> разные ключи
        expect("repo identity: одинаковое имя, разные пути -> разные ключи",
               cache.cache_key("/x/proj", "foo", "executor", afp_wide, 10000, "s1")
               != cache.cache_key("/y/proj", "foo", "executor", afp_wide, 10000, "s1"))
        # смена sha -> другой ключ
        expect("exact-revision: смена sha -> другой ключ",
               cache.cache_key(root, "foo", "executor", afp_wide, 10000, "s1")
               != cache.cache_key(root, "foo", "executor", afp_wide, 10000, "s2"))

    # интеграция с реальным AFP-001 (v3.4.2): роли резолвятся
    afp_p = PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"
    if afp_p.exists():
        afp = yaml.safe_load(afp_p.read_text(encoding="utf-8"))
        expect("AFP-001: planner -> {public, internal}",
               role_allowed_classes(afp, "planner") == {"public", "internal"})
        expect("AFP-001: security_reviewer включает confidential",
               "confidential" in role_allowed_classes(afp, "security_reviewer"))

    assert ok, "перенесённый селфтест context_retrieval: см. строки FAIL в выводе"
