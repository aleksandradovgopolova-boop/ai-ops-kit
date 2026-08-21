"""Граф зависимостей backlog (PR-17): блокирующие, критический путь, циклы, скрытые, dangling.

Синтетические классифицированные задачи (dict-форма) — живого GitHub нет. Каждый механизм проверен
на графе, где он должен сработать, и на графе, где не должен.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import backlog_depgraph as dg


def _node(number, deps=None, title=""):
    return {"number": number, "dependencies": deps or [], "title": title or f"t{number}"}


@pytest.mark.unit
def test_edges_and_blocking():
    # 2 и 3 зависят от 1 → 1 блокирует двоих.
    g = dg.build([_node(1), _node(2, [1]), _node(3, [1])])
    assert set(g.edges) == {(2, 1), (3, 1)}
    assert g.blocking[0]["number"] == 1 and g.blocking[0]["dependents"] == 2
    assert g.blocking[0]["blocks"] == [2, 3]


@pytest.mark.unit
def test_critical_path_longest_chain():
    # 4→3→2→1 — цепочка длины 4.
    g = dg.build([_node(1), _node(2, [1]), _node(3, [2]), _node(4, [3])])
    assert g.critical_path == [4, 3, 2, 1]
    assert not g.cycles


@pytest.mark.unit
def test_cycle_detected_and_blocks_critical_path():
    g = dg.build([_node(1, [2]), _node(2, [1])])
    assert g.cycles and sorted(g.cycles[0]) == [1, 2]
    assert g.critical_path == []        # с циклом критический путь не считаем (доставить нельзя)


@pytest.mark.unit
def test_hidden_transitive_dependency():
    # 1 зависит от 2, 2 от 3; 1 про 3 прямо не знает → скрытая.
    g = dg.build([_node(1, [2]), _node(2, [3]), _node(3)])
    hidden = {t["number"]: t["hidden"] for t in g.transitive}
    assert hidden.get(1) == [3]


@pytest.mark.unit
def test_no_hidden_when_declared():
    g = dg.build([_node(1, [2, 3]), _node(2, [3]), _node(3)])
    assert all(t["number"] != 1 for t in g.transitive)   # 1 уже объявил 3 напрямую


@pytest.mark.unit
def test_dangling_reference_outside_set():
    g = dg.build([_node(1, [99]), _node(2)])
    assert g.dangling == [{"number": 1, "missing": [99]}]
    assert g.edges == []                # ребро на 99 не строим — его нет в наборе


@pytest.mark.unit
def test_accepts_classification_objects():
    from ai_ops_kit.planning.backlog_classify import Classification
    c1 = Classification(number=1, title="a", type="feature", area="x", status="open",
                        priority="unset", milestone=None, impact="unknown", urgency="unknown",
                        effort="unknown", confidence="low", strategic_alignment="unknown",
                        dependencies=[2])
    c2 = Classification(number=2, title="b", type="feature", area="x", status="open",
                        priority="unset", milestone=None, impact="unknown", urgency="unknown",
                        effort="unknown", confidence="low", strategic_alignment="unknown")
    g = dg.build([c1, c2])
    assert g.edges == [(1, 2)]


class _FakeClient:
    def __init__(self, res):
        self._res = res
        self.repo = "o/r"

    def issues(self, state="open"):
        return self._res


@pytest.mark.unit
def test_graph_from_backlog_unavailable():
    from ai_ops_kit.integrations.github import FetchResult
    g = dg.graph_from_backlog(client=_FakeClient(FetchResult(False, reason="нет доступа")))
    assert g.ok is False and "нет доступа" in g.reason
