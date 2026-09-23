"""Объявленная цель функции не теряется по дороге в историю продукта.

ПОВОД (замер на реальной дочке, 21.09 → разбор 23.09). Все функции `ii-sreda` объявляют в паспорте
и цель, и эпик, но не инициативу — такого уровня у продукта просто нет. Лестница `contains`
связывала только СМЕЖНЫЕ уровни, поэтому до цели нить не доходила и `trace` отвечал «функция не
привязана ни к одной цели» — при том, что цель НАЗВАНА автором. Второй разрыв там же: ссылка на
цель, которой нет в плане, тихо создавала узел-заглушку, и граф выглядел целым.

Здесь проверяется ровно это поведение:
  * positive     — паспорт с целью и эпиком без инициативы даёт связь до цели, и `trace` её называет;
  * fail-closed  — ссылка на несуществующую цель НЕ выдаётся за швартовку: вердикт остаётся
                   `unmoored`, причина названа, заглушка целью не становится;
  * side-effect  — связь реально появляется в СОБРАННОМ графе (ребро есть в `edges`), а не только в
                   ответе обхода; и собранный граф проходит валидатор ссылочной целостности.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import knowledge_graph as kg  # noqa: E402
from ai_ops_kit.ui import presenter_graph  # noqa: E402
from ai_ops_kit.validation import validate_knowledge_graph as vkg  # noqa: E402


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _child(root: Path, *, feature_links: dict, goals: list) -> Path:
    """Синтетический child с одним паспортом функции и заданными целями плана."""
    _write(root / "planning" / "plan.yaml",
           {"schema_version": 1, "kind": "delivery-plan", "goals": goals})
    _write(root / "features" / "library-view" / "blueprint.yaml",
           {"schema_version": 1, "kind": "feature-blueprint",
            "feature": {"id": "library-view", "name": "Библиотека документов",
                        "status": "in-progress", "current_stage": "delivery"},
            "links": feature_links})
    return root


PLAN_GOAL = [{"id": "answer-from-our-documents", "outcome": {"answer_shows_its_basis": True}}]

TWO_GOALS = [{"id": "answer-from-our-documents", "outcome": {"answer_shows_its_basis": True}},
             {"id": "predictable-operation", "outcome": {"service_survives_reboot": False}}]


def _child_many(root: Path, features: dict, goals: list) -> Path:
    """Синтетический child с НЕСКОЛЬКИМИ паспортами: `{id функции: links}`.

    Общий эпик у функций с разными целями — не выдуманный случай: именно так выглядит продукт, где
    эпик объявляют паспорта соседних функций, а собственного источника у эпика нет.
    """
    _write(root / "planning" / "plan.yaml",
           {"schema_version": 1, "kind": "delivery-plan", "goals": goals})
    for fid, links in features.items():
        _write(root / "features" / fid / "blueprint.yaml",
               {"schema_version": 1, "kind": "feature-blueprint",
                "feature": {"id": fid, "name": fid, "status": "in-progress",
                            "current_stage": "delivery"},
                "links": links})
    return root


class TestDeclaredGoalReachesTheFeature:
    """positive: пропущенный уровень лестницы нить до цели не рвёт."""

    def test_goal_and_epic_without_initiative_still_reach_the_goal(self, tmp_path):
        """Паспорт объявил цель и эпик; инициативы у продукта нет — цель всё равно найдена."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents", "epic": "epic-library"},
                      goals=PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["goal"] == "answer-from-our-documents", result["gaps"]
        assert result["verdict"] != "unmoored"
        assert [c["id"] for c in result["chain"]] == [
            "answer-from-our-documents", "epic-library", "library-view"]

    def test_goal_alone_reaches_the_feature(self, tmp_path):
        """Ни инициативы, ни эпика — одна объявленная цель тоже связывается напрямую."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents"}, goals=PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["goal"] == "answer-from-our-documents", result["gaps"]

    def test_declared_goal_brings_the_promised_outcome(self, tmp_path):
        """Найденная цель тянет за собой обещанный результат (ребро targets), а не только имя."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents", "epic": "epic-library"},
                      goals=PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["outcome"] is not None
        assert result["outcome"]["id"] == "answer-from-our-documents-outcome"


class TestMissingGoalIsNamedNotFaked:
    """fail-closed: несуществующая цель не превращается в «всё хорошо»."""

    def test_reference_to_absent_goal_stays_unmoored(self, tmp_path):
        """Паспорт сослался на цель, которой нет в плане: швартовкой заглушка не считается."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "goal-fast-quality-results", "epic": "epic-library"},
                      goals=PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["goal"] is None
        assert result["verdict"] == "unmoored"
        assert result["unresolved_goal"] == "goal-fast-quality-results"

    def test_absent_goal_is_named_in_gaps(self, tmp_path):
        """Разрыв НАЗВАН: молчание скрыло бы, что цель существует только в ссылке."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "goal-fast-quality-results"}, goals=PLAN_GOAL)
        gaps = kg.trace(kg.build_graph(root), "library-view")["gaps"]
        assert any("goal-fast-quality-results" in g and "нет в плане" in g for g in gaps), gaps

    def test_human_answer_says_which_goal_is_missing(self, tmp_path):
        """Человеку названа ПРИЧИНА обрыва, а не общее «ни к какой цели не привязана»."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "goal-fast-quality-results"}, goals=PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        summary = presenter_graph.from_graph_trace(result)["summary"]
        assert "goal-fast-quality-results" in summary
        assert "нет в плане продукта" in summary

    def test_existing_goal_is_not_marked_unresolved(self, tmp_path):
        """Обратная сторона: настоящая цель плана пометки о разрыве не получает."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents"}, goals=PLAN_GOAL)
        graph = kg.build_graph(root)
        goal_node = next(n for n in graph["nodes"] if n["id"] == "answer-from-our-documents")
        assert "unresolved" not in goal_node


class TestTheLinkIsReallyInTheGraph:
    """side-effect proof: связь появилась в собранном графе, а не только в ответе обхода."""

    def test_edge_goal_contains_epic_is_emitted(self, tmp_path):
        """В `edges` есть ребро цель→эпик — обход читает граф, а не додумывает на лету."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents", "epic": "epic-library"},
                      goals=PLAN_GOAL)
        edges = kg.build_graph(root)["edges"]
        assert {"from": "answer-from-our-documents", "type": "contains",
                "to": "epic-library"} in edges

    def test_built_graph_passes_reference_validator(self, tmp_path):
        """Новые пары лестницы объявлены в словаре: валидатор принимает собранный граф."""
        root = _child(tmp_path / "child",
                      feature_links={"goal": "answer-from-our-documents", "epic": "epic-library"},
                      goals=PLAN_GOAL)
        graph_path = root / "knowledge" / "graph.yaml"
        _write(graph_path, kg.build_graph(root))
        types, rels = vkg.load_dictionary()
        assert vkg.validate_graph(graph_path, types, rels) == []


class TestSharedEpicDoesNotLendSomeoneElsesGoal:
    """Общий эпик не делает чужую цель своей — разбор находок независимого ревью PR #1102."""

    def test_each_feature_keeps_its_own_declared_goal(self, tmp_path):
        """Две функции одного эпика с РАЗНЫМИ целями: каждая служит своей, а не соседской."""
        root = _child_many(tmp_path / "child", {
            "aaa-first": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "zzz-second": {"goal": "predictable-operation", "epic": "epic-shared"},
        }, TWO_GOALS)
        graph = kg.build_graph(root)
        assert kg.trace(graph, "aaa-first")["goal"] == "answer-from-our-documents"
        assert kg.trace(graph, "zzz-second")["goal"] == "predictable-operation"

    def test_outcome_belongs_to_the_same_goal_as_the_chain(self, tmp_path):
        """Один ответ не смешивает две цели: обещанный результат — от той же цели, что названа."""
        root = _child_many(tmp_path / "child", {
            "aaa-first": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "zzz-second": {"goal": "predictable-operation", "epic": "epic-shared"},
        }, TWO_GOALS)
        result = kg.trace(kg.build_graph(root), "zzz-second")
        assert result["outcome"]["id"] == "predictable-operation-outcome"
        assert result["chain"][0]["id"] == "predictable-operation"

    def test_broken_reference_is_not_rescued_by_a_neighbour(self, tmp_path):
        """Сломанная ссылка на цель не «чинится» подъёмом через общий эпик к цели соседа."""
        root = _child_many(tmp_path / "child", {
            "aaa-real": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "zzz-broken": {"goal": "goal-nonexistent", "epic": "epic-shared"},
        }, PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "zzz-broken")
        assert result["goal"] is None
        assert result["verdict"] == "unmoored"
        assert result["unresolved_goal"] == "goal-nonexistent"

    def test_ambiguous_inheritance_is_named_not_guessed(self, tmp_path):
        """Функция без объявленной цели в эпике двух целей: неоднозначность названа, выбора нет."""
        root = _child_many(tmp_path / "child", {
            "aaa-first": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "mmm-silent": {"epic": "epic-shared"},
            "zzz-second": {"goal": "predictable-operation", "epic": "epic-shared"},
        }, TWO_GOALS)
        result = kg.trace(kg.build_graph(root), "mmm-silent")
        assert result["goal"] is None
        assert any("нескольким целям" in g for g in result["gaps"]), result["gaps"]

    def test_namesake_of_another_node_is_not_a_goal(self, tmp_path):
        """Цель-тёзка работы плана (узел типа initiative) целью не считается и связью не станет."""
        root = _child_many(tmp_path / "child", {"library-view": {"goal": "checkout-speedup"}},
                           PLAN_GOAL)
        _write(root / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
            "work": [{"id": "checkout-speedup", "goal": "answer-from-our-documents",
                      "title": "Ускорить чекаут"}]})
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["goal"] is None
        assert result["unresolved_goal"] == "checkout-speedup"

    def test_no_contains_edge_points_up_the_ladder(self, tmp_path):
        """Граница лестницы на РЕАЛЬНОМ графе: ни одно ребро contains не идёт снизу вверх."""
        root = _child_many(tmp_path / "child", {
            "aaa-first": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "zzz-second": {"goal": "predictable-operation", "initiative": "init-x",
                           "epic": "epic-shared"},
        }, TWO_GOALS)
        graph = kg.build_graph(root)
        types = {n["id"]: n["type"] for n in graph["nodes"]}
        ladder = kg.CONTAINS_LADDER
        for e in [e for e in graph["edges"] if e["type"] == "contains"]:
            assert ladder.index(types[e["from"]]) < ladder.index(types[e["to"]]), e


@pytest.mark.parametrize("blueprint", sorted(
    (PKG_ROOT / "features").glob("*/blueprint.yaml")), ids=lambda p: p.parent.name)
def test_kit_own_features_declare_their_goal(blueprint):
    """Паспорта самого кита называют цель: иначе нить его собственной истории обрывается."""
    links = (yaml.safe_load(blueprint.read_text(encoding="utf-8")) or {}).get("links") or {}
    assert links.get("goal"), f"{blueprint.parent.name}: в links нет goal"


def test_kit_own_features_are_moored_to_a_real_goal():
    """И эта цель — настоящая: сославшись на несуществующую, кит соврал бы про самого себя."""
    graph = kg.build_graph(PKG_ROOT)
    unmoored = []
    for node in graph["nodes"]:
        if node.get("type") != "feature" or not node.get("blueprint", "").startswith("../features/"):
            continue
        result = kg.trace(graph, node["id"])
        if result["goal"] is None:
            unmoored.append((node["id"], result["unresolved_goal"], result["gaps"]))
    assert not unmoored, f"функции кита без цели: {unmoored}"
