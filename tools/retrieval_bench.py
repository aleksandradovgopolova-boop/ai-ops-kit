#!/usr/bin/env python3
"""retrieval_bench.py (v3.6.2) — оффлайн golden-корпус precision/recall retrieval-стратегий.

Закрывает research-gap FL-003 / RR-009 (сравнить retrieval-стратегии под бюджет) — но ЧЕСТНО:
измеряет то, что уже реализовано БЕЗ vector-DB — full-text vs graph-augmented (full-text +
соседи по Repository Graph: зависимости и зависимые). Семантическая стратегия появится в цепочке
позже (semantic fallback) и войдёт в тот же Bench.

Метрики на golden-корпусе (query -> known relevant files): precision/recall/F1 (macro-avg).
Гипотеза (FL-003): граф-дополнение поднимает recall на релевантных-по-зависимости файлах, у которых
мало ключевых слов, не разрушая precision.

CLI:  retrieval_bench.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))
import context_retrieval as cr   # noqa: E402
import repo_graph as rg          # noqa: E402


def _fulltext(root, query, subdirs, k=3):
    return [r["file"] for r in cr.full_text_search(root, query, subdirs)[:k]]


def _graph_augmented(root, query, subdirs, k=3):
    ft = _fulltext(root, query, subdirs, k)
    if not ft:
        return []
    g = rg.build_graph(root, subdirs)
    top = ft[0]
    neighbors = set(rg.impact(g, top)) | set(g.get("import_edges", {}).get(top, []))
    return ft + [n for n in sorted(neighbors) if n not in ft]


def _metrics(retrieved, relevant):
    ret, rel = set(retrieved), set(relevant)
    tp = len(ret & rel)
    precision = tp / len(ret) if ret else 0.0
    recall = tp / len(rel) if rel else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def run_bench(root, golden, subdirs):
    strategies = {"fulltext": _fulltext, "graph_augmented": _graph_augmented}
    report = {}
    for name, fn in strategies.items():
        per_q, ps, rs, fs = [], [], [], []
        for case in golden:
            retrieved = fn(root, case["query"], subdirs)
            m = _metrics(retrieved, case["relevant"])
            per_q.append({"query": case["query"], **m, "retrieved": retrieved})
            ps.append(m["precision"]); rs.append(m["recall"]); fs.append(m["f1"])
        n = len(golden) or 1
        report[name] = {"precision": round(sum(ps) / n, 3), "recall": round(sum(rs) / n, 3),
                        "f1": round(sum(fs) / n, 3), "per_query": per_q}
    best = max(report, key=lambda s: report[s]["f1"])
    return {"kind": "retrieval-bench", "strategies": report, "best_by_f1": best}


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "repo").mkdir()
        # pricing: ключевые слова есть; checkout: ЗАВИСИТ от pricing, но без слова 'discount';
        # unrelated: ни слова, ни зависимости.
        (root / "repo" / "pricing.py").write_text(
            "def apply_discount(a):\n    # discount pricing logic\n    return a*0.9\n"
            "def total(a):\n    return a\n", encoding="utf-8")
        (root / "repo" / "checkout.py").write_text(
            "import pricing\n\ndef checkout(a):\n    return pricing.total(a)\n", encoding="utf-8")
        (root / "repo" / "unrelated.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
        golden = [{"query": "discount", "relevant": ["repo/pricing.py", "repo/checkout.py"]}]

        rep = run_bench(root, golden, ("repo",))
        ft = rep["strategies"]["fulltext"]
        ga = rep["strategies"]["graph_augmented"]
        expect("fulltext находит pricing.py (текстовый матч)",
               "repo/pricing.py" in ft["per_query"][0]["retrieved"])
        expect("fulltext НЕ находит checkout.py (нет ключевого слова) -> recall < 1",
               "repo/checkout.py" not in ft["per_query"][0]["retrieved"] and ft["recall"] < 1.0)
        expect("graph_augmented находит checkout.py по зависимости -> recall выше",
               "repo/checkout.py" in ga["per_query"][0]["retrieved"] and ga["recall"] > ft["recall"])
        expect("graph_augmented не тянет unrelated.py (precision держится)",
               "repo/unrelated.py" not in ga["per_query"][0]["retrieved"] and ga["precision"] >= 0.5)
        expect("best_by_f1 = graph_augmented (recall выше при сохранённой precision)",
               rep["best_by_f1"] == "graph_augmented")
        expect("метрики в [0,1]", 0 <= ft["f1"] <= 1 and 0 <= ga["f1"] <= 1)

    print("retrieval_bench selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
