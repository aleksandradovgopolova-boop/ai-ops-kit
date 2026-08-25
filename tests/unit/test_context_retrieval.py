"""Гранулярные тесты context_retrieval (мигрировано из test_context_retrieval_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from context_retrieval import (
    PKG,
    Path,
    RetrievalCache,
    build_view,
    full_text_search,
    role_allowed_classes,
    yaml,
)


@pytest.fixture
def search_repo(tmp_path):
    root = tmp_path
    (root / "tools").mkdir()
    (root / "tools" / "a.py").write_text("# keyword foo appears foo twice\ndef alpha():\n    return 'foo'\n", encoding="utf-8")
    (root / "tools" / "b.py").write_text("# data-class: confidential\n# foo here once\n", encoding="utf-8")
    (root / "tools" / "c.py").write_text("# foo but has a secret sk-ant-api03xxxxxxxx\n", encoding="utf-8")
    (root / "tools" / "d.py").write_text("# nothing relevant here\n", encoding="utf-8")
    return root


@pytest.mark.unit
class TestFullTextSearch:
    def test_ranking_and_exclusion(self, search_repo):
        res = full_text_search(search_repo, "foo", ("tools",))
        assert res[0]["file"] == "tools/a.py"
        assert all(r["file"] != "tools/d.py" for r in res)

    def test_tsx_and_md_covered(self, search_repo):
        (search_repo / "ui").mkdir()
        (search_repo / "ui" / "Widget.tsx").write_text("// foo component\nexport const Widget = () => 'foo';\n", encoding="utf-8")
        (search_repo / "ui" / "notes.md").write_text("# foo doc\n", encoding="utf-8")
        rts = full_text_search(search_repo, "foo", ("ui",))
        assert {"ui/Widget.tsx", "ui/notes.md"} <= {r["file"] for r in rts}

    def test_node_modules_excluded(self, search_repo):
        (search_repo / "node_modules" / "pkg").mkdir(parents=True)
        (search_repo / "node_modules" / "pkg" / "index.js").write_text("// foo vendored\n", encoding="utf-8")
        rex = full_text_search(search_repo, "foo", ("",))
        assert all("node_modules" not in r["file"] for r in rex)


@pytest.mark.unit
class TestBuildView:
    def test_planner_sees_internal(self, search_repo):
        v = build_view(search_repo, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        inc = {i["file"] for i in v["included"]}
        assert "tools/a.py" in inc

    def test_planner_excludes_confidential(self, search_repo):
        v = build_view(search_repo, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        exa = {e["file"] for e in v["excluded_access"]}
        assert "tools/b.py" in exa

    def test_secret_always_excluded(self, search_repo):
        v = build_view(search_repo, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        exa = {e["file"] for e in v["excluded_access"]}
        assert "tools/c.py" in exa

    def test_executor_sees_confidential(self, search_repo):
        v = build_view(search_repo, "foo", "executor", {"public", "internal", "confidential"}, 10000)
        inc = {i["file"] for i in v["included"]}
        assert "tools/b.py" in inc

    def test_secret_excluded_for_executor(self, search_repo):
        v = build_view(search_repo, "foo", "executor", {"public", "internal", "confidential"}, 10000)
        exa = {e["file"] for e in v["excluded_access"]}
        assert "tools/c.py" in exa

    def test_tiny_budget(self, search_repo):
        vb = build_view(search_repo, "foo", "executor", {"public", "internal", "confidential"}, budget_tokens=1)
        assert len(vb["included"]) <= 1
        assert (len(vb["excluded_budget"]) >= 1 or len(vb["included"]) == 0)
        assert vb["total_tokens"] <= 1

    def test_deny_by_default(self, search_repo):
        vd = build_view(search_repo, "foo", "nobody", set(), 10000)
        assert vd["included"] == []

    def test_cache_key_components(self, search_repo):
        v = build_view(search_repo, "foo", "planner", {"public", "internal"}, budget_tokens=10000)
        assert all(x in v["cache_key"] for x in ("repo:", "sha:", "role:", "view:"))


@pytest.mark.unit
class TestRetrievalCache:
    @pytest.fixture
    def afp_policies(self):
        def _afp(rules):
            return {"id": "AFP-T", "kind": "AccessFilterPolicy", "rules": rules}
        return {
            "wide": _afp([{"role": "executor", "allowed_classes": ["public", "internal", "confidential"]}]),
            "narrow": _afp([{"role": "executor", "allowed_classes": ["public", "internal"]}]),
        }

    def test_cache_hit(self, search_repo, afp_policies):
        cache = RetrievalCache()
        vw, hw = cache.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha="s1")
        _, hw2 = cache.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha="s1")
        assert hw is False and hw2 is True and cache.builds == 1

    def test_wide_policy_includes_confidential(self, search_repo, afp_policies):
        cache = RetrievalCache()
        vw, _ = cache.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha="s1")
        assert "tools/b.py" in {i["file"] for i in vw["included"]}

    def test_narrower_policy_cache_miss(self, search_repo, afp_policies):
        cache = RetrievalCache()
        cache.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha="s1")
        vn, hn = cache.get_or_build(search_repo, "foo", "executor", afp_policies["narrow"], 10000, sha="s1")
        assert hn is False
        assert "tools/b.py" not in {i["file"] for i in vn["included"]}

    def test_hit_does_not_rebuild(self, search_repo, afp_policies):
        cache = RetrievalCache()
        cache.get_or_build(search_repo, "foo", "executor", afp_policies["narrow"], 10000, sha="s1")
        builds_before = cache.builds
        cache.get_or_build(search_repo, "foo", "executor", afp_policies["narrow"], 10000, sha="s1")
        assert cache.builds == builds_before

    def test_no_sha_no_cache(self, search_repo, afp_policies):
        c = RetrievalCache()
        c.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha=None)
        c.get_or_build(search_repo, "foo", "executor", afp_policies["wide"], 10000, sha=None)
        assert c.misses == 2 and c.builds == 2 and c.hits == 0


@pytest.mark.unit
class TestCacheKey:
    def test_different_paths_different_keys(self):
        def _afp(rules):
            return {"id": "AFP-T", "kind": "AccessFilterPolicy", "rules": rules}
        afp = _afp([{"role": "executor", "allowed_classes": ["public", "internal", "confidential"]}])
        cache = RetrievalCache()
        assert (cache.cache_key("/x/proj", "foo", "executor", afp, 10000, "s1")
                != cache.cache_key("/y/proj", "foo", "executor", afp, 10000, "s1"))

    def test_sha_change_different_key(self):
        def _afp(rules):
            return {"id": "AFP-T", "kind": "AccessFilterPolicy", "rules": rules}
        afp = _afp([{"role": "executor", "allowed_classes": ["public", "internal", "confidential"]}])
        cache = RetrievalCache()
        assert (cache.cache_key("/proj", "foo", "executor", afp, 10000, "s1")
                != cache.cache_key("/proj", "foo", "executor", afp, 10000, "s2"))


@pytest.mark.unit
class TestRoleAllowedClasses:
    def test_planner_classes(self):
        afp_p = PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"
        if afp_p.exists():
            afp = yaml.safe_load(afp_p.read_text(encoding="utf-8"))
            assert role_allowed_classes(afp, "planner") == {"public", "internal"}

    def test_security_reviewer_includes_confidential(self):
        afp_p = PKG / "examples" / "access-filter-demo" / "AFP-001.yaml"
        if afp_p.exists():
            afp = yaml.safe_load(afp_p.read_text(encoding="utf-8"))
            assert "confidential" in role_allowed_classes(afp, "security_reviewer")
