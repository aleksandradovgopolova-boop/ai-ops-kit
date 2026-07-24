#!/usr/bin/env python3
"""context_engine.py (v3.6.7) — единый канонический оркестратор Context Engine v2.

Ревью владельца по v3.6.6: shadow подключал только `build_view()` (full-text role view), а не всю
retrieval-цепочку (Repository Graph, graph-augmentation, semantic-lite, cache в shadow не входили), и
работал на ДЕМО-политике кита без DataClassificationPolicy. Здесь — ОДИН слой, собирающий полную
цепочку перед промоушеном в боевой runtime:

    обязательный контекст v1 (policy/spec/decisions)
    + full-text кандидаты
    + Repository Graph augmentation (соседи по импортам/обратным зависимостям)
    + УСЛОВНЫЙ semantic-lite (только при недостаточном детерминированном recall)
    -> access-filter (AFP роли, DataClassificationPolicy — политики CHILD-репо, НЕ демо)
    -> rerank
    -> budget
    -> role view

Инварианты (fail-closed перед боевым включением):
  - без ТОЧНОГО SHA view НЕ строится (нельзя доказать привязку к ревизии) -> ValueError;
  - обязательный контекст v1 НЕЛЬЗЯ потерять на rerank/budget (только access-filter: secret никогда);
  - graph и semantic ТОЛЬКО ДОБАВЛЯЮТ кандидатов, не удаляют детерминированные;
  - semantic вызывается ТОЛЬКО при недостаточном детерминированном recall;
  - у каждого источника — reason, content-hash и точный SHA;
  - политики берутся у CHILD-репо (load_child_policies), demo-политик в runtime нет.

Только stdlib + pyyaml.  CLI: context_engine.py <child_root> --query ".." --role executor --sha SHA | --selftest
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))
import context_retrieval as cr   # noqa: E402
import repo_graph                # noqa: E402
import semantic_lite             # noqa: E402

SEMANTIC_RECALL_FLOOR = 3        # < столько детерминированных кандидатов -> recall недостаточен


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:12]


def _hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in Path(rel).parts)


def load_child_policies(child_root):
    """Политики CHILD-репо (НЕ демо кита): .ai/policies/{access-filter,data-classification,budget}.yaml.
    Отсутствует -> None (deny-by-default в build_context; никакого demo-fallback в runtime)."""
    base = Path(child_root) / ".ai" / "policies"

    def _load(name):
        p = base / name
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
        except OSError:
            return None
    return _load("access-filter.yaml"), _load("data-classification.yaml"), _load("budget.yaml")


def build_context(child_root, query, role, *, sha, afp, dcp=None, budget_tokens=20000,
                  v1_mandatory=None, repo_id=None, semantic_recall_floor=SEMANTIC_RECALL_FLOOR):
    """Собрать полный Context Engine v2 view. sha ОБЯЗАТЕЛЕН (иначе ValueError)."""
    if not sha:
        raise ValueError("context_engine: без точного SHA view не строится (exact-revision binding)")
    root = Path(child_root)
    allowed = cr.role_allowed_classes(afp, role) if afp else set()   # deny-by-default

    # --- источник 1: обязательный контекст v1 (policy/spec/decisions) — нельзя потерять ---
    cand = {}   # rel -> {"file","sources":set,"score","mandatory"}
    for rel in (v1_mandatory or []):
        cand[rel] = {"file": rel, "sources": {"mandatory-v1"}, "score": 10_000, "mandatory": True}

    # --- источник 2: full-text (broad exts: TS/React/docs/JSON, не только Python) ---
    ft = cr.full_text_search(root, query, subdirs=("",))
    for r in ft:
        c = cand.setdefault(r["file"], {"file": r["file"], "sources": set(), "score": 0, "mandatory": False})
        c["sources"].add("fulltext")
        c["score"] = max(c["score"], r["score"]) if not c["mandatory"] else c["score"]
    deterministic_count = len([1 for r in ft])

    # --- источник 3: Repository Graph augmentation (только ДОБАВЛЯЕТ соседей .py) ---
    graph_added = 0
    try:
        graph = repo_graph.build_graph(root, subdirs=("",))
    except Exception:
        graph = {"import_edges": {}}
    ft_files = [r["file"] for r in ft]
    for rel in ft_files:
        if not rel.endswith(".py"):
            continue
        neighbors = set(graph.get("import_edges", {}).get(rel, []))   # forward: что импортит rel
        neighbors |= set(repo_graph.impact(graph, rel))               # reverse: кто зависит от rel
        for nb in neighbors:
            if _hidden(nb) or nb in cand:
                continue
            cand[nb] = {"file": nb, "sources": {"graph"}, "score": 0, "mandatory": False}
            graph_added += 1

    # --- источник 4: УСЛОВНЫЙ semantic-lite (только при недостаточном детерминированном recall) ---
    semantic_used, semantic_reason = False, "детерминированный recall достаточен"
    if deterministic_count < semantic_recall_floor:
        semantic_used = True
        semantic_reason = f"детерминированных кандидатов {deterministic_count} < floor {semantic_recall_floor}"
        try:
            idx = semantic_lite.build_index(root, subdirs=("",))
            for r in semantic_lite.search(idx, query, k=5):
                if _hidden(r["file"]):
                    continue
                c = cand.setdefault(r["file"], {"file": r["file"], "sources": set(), "score": 0,
                                                "mandatory": False})
                c["sources"].add("semantic")
        except Exception:
            semantic_reason += " (semantic-индекс не построен: нет подходящих файлов)"

    # --- access-filter (AFP роли + DataClassificationPolicy child) + классификация ---
    included, excl_access, excl_budget, mandatory_missing = [], [], [], []
    resolved = []
    for rel, c in cand.items():
        f = root / rel
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            if c["mandatory"]:
                mandatory_missing.append(rel)
            continue
        data_class = cr.classify(content, path=rel, policy=dcp)
        if data_class == "secret" or data_class not in allowed:
            excl_access.append({"file": rel, "data_class": data_class, "mandatory": c["mandatory"],
                                "sources": sorted(c["sources"])})
            continue
        resolved.append({"file": rel, "sources": sorted(c["sources"]), "mandatory": c["mandatory"],
                         "score": c["score"], "data_class": data_class,
                         "tokens": cr._tokens(content), "content_hash": _hash(content), "sha": sha})

    # --- rerank: обязательные первыми (стабильно), затем по score desc, файл для детерминизма ---
    resolved.sort(key=lambda x: (0 if x["mandatory"] else 1, -x["score"], x["file"]))

    # --- budget: обязательные включаются ВСЕГДА (даже сверх бюджета -> флаг); остальное до лимита ---
    total = 0
    for item in resolved:
        item = dict(item)
        item["reason"] = _reason(item)
        if item["mandatory"]:
            total += item["tokens"]
            item["over_budget"] = total > budget_tokens
            included.append(item)
        elif total + item["tokens"] <= budget_tokens:
            total += item["tokens"]
            item["over_budget"] = False
            included.append(item)
        else:
            excl_budget.append({"file": item["file"], "tokens": item["tokens"]})

    afp_id, afp_hash = cr._policy_fingerprint(afp)
    dcp_id, dcp_hash = cr._policy_fingerprint(dcp)
    allowed_h = hashlib.sha256(",".join(sorted(allowed)).encode()).hexdigest()[:8]
    repo = cr._repo_identity(root, repo_id)
    return {
        "kind": "context-engine-view", "schema": "v2-orchestrated", "role": role, "query": query,
        "repo": repo, "sha": sha,
        "sources_used": {"mandatory_v1": len(v1_mandatory or []), "fulltext": deterministic_count,
                         "graph_added": graph_added, "semantic_used": semantic_used,
                         "semantic_reason": semantic_reason},
        "included": included, "excluded_access": excl_access, "excluded_budget": excl_budget,
        "mandatory_missing": sorted(mandatory_missing),
        "total_tokens": total, "budget_tokens": budget_tokens,
        "cache_key": "|".join([f"repo:{repo}", f"sha:{sha}", f"afp:{afp_id}:{afp_hash}",
                               f"dcp:{dcp_id}:{dcp_hash}", f"allowed:{allowed_h}", f"role:{role}",
                               f"q:{query}", f"b:{budget_tokens}",
                               f"idx:{cr.RETRIEVAL_INDEX_VERSION}"]),
    }


def _reason(item):
    src = ",".join(item["sources"])
    if item["mandatory"]:
        return f"обязательный контекст v1 ({src}) — не теряется на rerank/budget"
    return f"кандидат из [{src}] (score={item['score']})"


def compare_v1(view, v1_files):
    """Сравнение полной v2-цепочки с боевым v1: overlap / только v1 / только v2."""
    v2 = {i["file"] for i in view.get("included", [])}
    v1 = set(v1_files or [])
    return {"overlap": sorted(v1 & v2), "v1_only": sorted(v1 - v2), "v2_only": sorted(v2 - v1),
            "v1_count": len(v1), "v2_count": len(v2)}


def selftest():
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
        expect("секрет исключён access-filter ВСЕГДА (secret никогда в контекст)", "secret.py" in exa)
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

    print("context_engine selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1

    def _opt(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    child = args[0]
    afp, dcp, _ = load_child_policies(child)
    view = build_context(child, _opt("--query", ""), _opt("--role", "executor"),
                         sha=_opt("--sha"), afp=afp, dcp=dcp)
    print(json.dumps(view, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
