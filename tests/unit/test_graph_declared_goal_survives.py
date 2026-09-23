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
from ai_ops_kit.shared import review_verdict  # noqa: E402
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
        contains = [e for e in graph["edges"] if e["type"] == "contains"]
        assert contains, "рёбер contains нет вовсе — сторож проверял бы пустоту"
        for e in contains:
            assert ladder.index(types[e["from"]]) < ladder.index(types[e["to"]]), e


class TestAmbiguityAndLostLevelsAreNamed:
    """Разбор остатка ревью (#1103): молчаливого выбора и молчаливой потери звена быть не должно."""

    def test_goal_reachable_through_different_depths_is_ambiguous(self, tmp_path):
        """Цель напрямую и цель через инициативу — это ДВЕ цели, а не «одна прямая и неважно»."""
        root = _child_many(tmp_path / "child", {
            "aaa-direct": {"goal": "answer-from-our-documents", "epic": "epic-shared"},
            "bbb-deep": {"goal": "predictable-operation", "initiative": "init-x",
                         "epic": "epic-shared"},
            "mmm-silent": {"epic": "epic-shared"},
        }, TWO_GOALS)
        result = kg.trace(kg.build_graph(root), "mmm-silent")
        assert result["goal"] is None
        assert any("нескольким целям" in g for g in result["gaps"]), result["gaps"]

    def test_single_goal_through_initiative_still_found(self, tmp_path):
        """Обратная сторона: одна цель через инициативу по-прежнему находится (не регрессия)."""
        root = _child_many(tmp_path / "child", {
            "bbb-deep": {"goal": "answer-from-our-documents", "initiative": "init-x",
                         "epic": "epic-shared"},
            "mmm-silent": {"epic": "epic-shared"},
        }, PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "mmm-silent")
        assert result["goal"] == "answer-from-our-documents", result["gaps"]

    def test_level_named_after_a_feature_is_not_a_parent(self, tmp_path):
        """Эпик-тёзка настоящей функции не делает её эпиком: функция остаётся функцией."""
        root = _child_many(tmp_path / "child", {
            "library-view": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {"goal": "answer-from-our-documents"},
        }, PLAN_GOAL)
        types = {n["id"]: n["type"] for n in kg.build_graph(root)["nodes"]}
        assert types["zzz-other"] == "feature"

    def test_lost_level_is_named_in_gaps(self, tmp_path):
        """Потерянное звено НАЗВАНО: молча пропасть объявленный уровень не имеет права."""
        root = _child_many(tmp_path / "child", {
            "library-view": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {"goal": "answer-from-our-documents"},
        }, PLAN_GOAL)
        gaps = kg.trace(kg.build_graph(root), "library-view")["gaps"]
        assert any("zzz-other" in g and "связью не стал" in g for g in gaps), gaps

    def test_lost_level_is_explained_once(self, tmp_path):
        """Одна потеря — один пункт человеку: две формулировки про одно и то же не помогают."""
        root = _child_many(tmp_path / "child", {
            "library-view": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {"goal": "answer-from-our-documents"},
        }, PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "library-view")
        assert result["goal"] == "answer-from-our-documents"
        about_loss = [g for g in result["gaps"] if "zzz-other" in g or "пути нет" in g]
        assert len(about_loss) == 1, about_loss

    def test_chain_without_a_real_path_is_disclosed(self):
        """Граф пришёл извне: цель объявлена, а пути к ней нет — цепочка названа неполной по данным.

        `trace` работает над ЛЮБЫМ графом схемы (в том числе собранным прежней версией кита или
        поправленным руками), поэтому случай проверяется на графе, а не через сборщик.
        """
        graph = {"schema_version": 1, "kind": "knowledge-graph", "nodes": [
            {"id": "library-view", "type": "feature", "title": "Библиотека",
             "declared_goal": "answer-from-our-documents"},
            {"id": "answer-from-our-documents", "type": "goal", "title": "Ответ из документов"},
        ], "edges": []}
        result = kg.trace(graph, "library-view")
        assert result["goal"] == "answer-from-our-documents"
        assert any("пути нет" in g for g in result["gaps"]), result["gaps"]

    def test_graph_with_lost_level_still_validates(self, tmp_path):
        """Потеря звена не ломает граф: он остаётся валидным, разрыв назван, а не выброшен наружу."""
        root = _child_many(tmp_path / "child", {
            "library-view": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {"goal": "answer-from-our-documents"},
        }, PLAN_GOAL)
        graph_path = root / "knowledge" / "graph.yaml"
        _write(graph_path, kg.build_graph(root))
        types, rels = vkg.load_dictionary()
        assert vkg.validate_graph(graph_path, types, rels) == []


class TestNameConflictsInventNothing:
    """#1106: спор имён не рождает связь, которой никто не объявлял, и решается в пользу функции."""

    def test_epic_named_after_a_feature_makes_no_edge_to_it(self, tmp_path):
        """Тёзка стоит РЕБЁНКОМ: ребра «цель содержит чужую функцию» в графе быть не должно."""
        root = _child_many(tmp_path / "child", {
            "consumer": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {},
        }, PLAN_GOAL)
        edges = kg.build_graph(root)["edges"]
        assert {"from": "answer-from-our-documents", "type": "contains",
                "to": "zzz-other"} not in edges

    def test_feature_does_not_inherit_a_goal_through_its_namesake(self, tmp_path):
        """И цели соседа такая функция не получает: связи не было, значит и ответа нет."""
        root = _child_many(tmp_path / "child", {
            "consumer": {"goal": "answer-from-our-documents", "epic": "zzz-other"},
            "zzz-other": {},
        }, PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "zzz-other")
        assert result["goal"] is None
        assert result["verdict"] == "unmoored"

    def test_goal_in_plan_named_after_a_feature_leaves_the_feature_intact(self, tmp_path):
        """Цель плана — тёзка функции: в граф входит ФУНКЦИЯ, а не цель с чужими атрибутами."""
        root = _child_many(tmp_path / "child", {"library-view": {}}, [
            {"id": "library-view", "outcome": {"works": True}},
            {"id": "answer-from-our-documents", "outcome": {"answer_shows_its_basis": True}}])
        graph = kg.build_graph(root)
        types = {n["id"]: n["type"] for n in graph["nodes"]}
        assert types["library-view"] == "feature"

    def test_graph_with_goal_namesake_still_validates(self, tmp_path):
        """И граф остаётся валидным: раньше сборка отвечала про «устаревший реестр типов»."""
        root = _child_many(tmp_path / "child", {"library-view": {}}, [
            {"id": "library-view", "outcome": {"works": True}}])
        graph_path = root / "knowledge" / "graph.yaml"
        _write(graph_path, kg.build_graph(root))
        types, rels = vkg.load_dictionary()
        assert vkg.validate_graph(graph_path, types, rels) == []

    def test_work_named_after_a_feature_leaves_the_feature_intact(self, tmp_path):
        """Работа плана — тёзка функции: в граф входит ФУНКЦИЯ, а не инициатива."""
        root = _child_many(tmp_path / "child",
                           {"library-view": {"goal": "answer-from-our-documents"}}, PLAN_GOAL)
        _write(root / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
            "work": [{"id": "library-view", "goal": "answer-from-our-documents",
                      "title": "Сделать библиотеку"}]})
        graph = kg.build_graph(root)
        types = {n["id"]: n["type"] for n in graph["nodes"]}
        assert types["library-view"] == "feature"
        assert kg.trace(graph, "library-view")["goal"] == "answer-from-our-documents"

    def test_work_namesake_conflict_is_named(self, tmp_path):
        """И конфликт назван: человек узнает, что одна из двух сущностей осталась за графом."""
        root = _child_many(tmp_path / "child",
                           {"library-view": {"goal": "answer-from-our-documents"}}, PLAN_GOAL)
        _write(root / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
            "work": [{"id": "library-view", "goal": "answer-from-our-documents",
                      "title": "Сделать библиотеку"}]})
        gaps = kg.trace(kg.build_graph(root), "library-view")["gaps"]
        assert any("работа в плане" in g for g in gaps), gaps

    def test_work_without_a_resolvable_goal_reports_no_loss(self, tmp_path):
        """Работа-тёзка, которая узлом и не стала бы: терять нечего — и пробела быть не должно."""
        root = _child_many(tmp_path / "child",
                           {"library-view": {"goal": "answer-from-our-documents"}}, PLAN_GOAL)
        _write(root / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
            "work": [{"id": "library-view", "goal": "goal-that-does-not-exist",
                      "title": "Сделать библиотеку"}]})
        gaps = kg.trace(kg.build_graph(root), "library-view")["gaps"]
        assert not any("работа в плане" in g for g in gaps), gaps

    def test_graph_with_work_namesake_still_validates(self, tmp_path):
        """Раньше такой граф валидатор отвергал, указывая не на причину. Теперь он валиден."""
        root = _child_many(tmp_path / "child",
                           {"library-view": {"goal": "answer-from-our-documents",
                                             "epic": "epic-library"}}, PLAN_GOAL)
        _write(root / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
            "work": [{"id": "library-view", "goal": "answer-from-our-documents",
                      "title": "Сделать библиотеку"}]})
        graph_path = root / "knowledge" / "graph.yaml"
        _write(graph_path, kg.build_graph(root))
        types, rels = vkg.load_dictionary()
        assert vkg.validate_graph(graph_path, types, rels) == []

    def test_goal_named_after_a_feature_is_explained_once_and_precisely(self, tmp_path):
        """Цель — имя другой функции: причина названа ОДИН раз и та самая, а не «нет в плане»."""
        root = _child_many(tmp_path / "child", {
            "library-view": {"goal": "zzz-other"},
            "zzz-other": {"goal": "answer-from-our-documents"},
        }, PLAN_GOAL)
        gaps = kg.trace(kg.build_graph(root), "library-view")["gaps"]
        about = [g for g in gaps if "zzz-other" in g]
        assert len(about) == 1, about
        assert "имя другой сущности графа" in about[0], about

    def test_placeholder_goal_does_not_moor_a_silent_feature(self, tmp_path):
        """Функция без своей цели не швартуется к ЗАГЛУШКЕ — цели, которой нет в плане."""
        root = _child_many(tmp_path / "child", {
            "aaa-declares": {"goal": "goal-nonexistent", "epic": "epic-shared"},
            "mmm-silent": {"epic": "epic-shared"},
        }, PLAN_GOAL)
        result = kg.trace(kg.build_graph(root), "mmm-silent")
        assert result["goal"] is None
        assert result["verdict"] == "unmoored"

    def test_placeholder_goal_is_named_for_a_silent_feature(self, tmp_path):
        """И причина названа: выше есть только цель, которой нет в плане."""
        root = _child_many(tmp_path / "child", {
            "aaa-declares": {"goal": "goal-nonexistent", "epic": "epic-shared"},
            "mmm-silent": {"epic": "epic-shared"},
        }, PLAN_GOAL)
        gaps = kg.trace(kg.build_graph(root), "mmm-silent")["gaps"]
        assert any("goal-nonexistent" in g and "нет в плане" in g for g in gaps), gaps

    def test_dead_end_names_a_node_without_parents(self):
        """Тупиком назван узел, у которого родителей НЕТ, а не тот, чьих родителей уже видели.

        Форма — «ромб с общим верхом»: у `feat` два родителя, короткая ветка `s` (сам верх) и
        длинная `a → b → s`. Прежний код отдавал победу самому длинному пути и называл тупиком `b`,
        у которого родитель есть; верный ответ — `s`.
        """
        nodes = [{"id": n, "type": t} for n, t in
                 [("feat", "feature"), ("s", "epic"), ("a", "epic"), ("b", "epic")]]
        edges = [{"from": "s", "type": "contains", "to": "feat"},
                 {"from": "a", "type": "contains", "to": "feat"},
                 {"from": "b", "type": "contains", "to": "a"},
                 {"from": "s", "type": "contains", "to": "b"}]
        graph = {"schema_version": 1, "kind": "knowledge-graph", "nodes": nodes, "edges": edges}
        reversed_graph = {**graph, "edges": list(reversed(edges))}
        gaps = kg.trace(graph, "feat")["gaps"]
        assert any("«s»" in g for g in gaps), gaps
        assert not any("«b»" in g for g in gaps), gaps
        assert gaps == kg.trace(reversed_graph, "feat")["gaps"]


def _graph_with_every_branch(root: Path) -> dict:
    """Синтетический child, где срабатывают ВСЕ ветки сборщика, пишущие атрибуты на узлы.

    Данных самого кита для сторожа мало: в них не рождаются ни `broken_links`, ни
    `name_taken_in_plan`, ни узел `review` — то есть ровно те атрибуты, ради которых он заведён.
    """
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan", "goals": PLAN_GOAL,
        "work": [{"id": "library-view", "goal": "answer-from-our-documents", "title": "Работа"},
                 {"id": "real-work", "goal": "answer-from-our-documents", "title": "Инициатива"}]})
    _write(root / "features" / "library-view" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "library-view", "name": "Библиотека", "status": "in-progress",
                    "current_stage": "delivery"},
        "links": {"goal": "answer-from-our-documents", "epic": "zzz-other",
                  "decision": "ep-2026-01-01-some", "built_by": 42},
        "metrics": [{"name": "Открытий в неделю"}]})
    _write(root / "features" / "zzz-other" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "zzz-other", "name": "Тёзка", "status": "in-progress",
                    "current_stage": "delivery"},
        "links": {"goal": "goal-that-does-not-exist"}})
    _write(root / "features" / "library-view" / "review" / "verdict.yaml", {
        "kind": review_verdict.RECORD_KIND, "feature": "library-view", "verified": True,
        "reviewed_by": "машина", "reviewed_revision": "abc1234"})
    _write(root / "product-learning" / "FL-001.yaml", {
        "id": "FL-001", "feature": "library-view", "learnings": ["Урок"],
        "derived_from_outcome": "answer-from-our-documents-outcome"})
    return kg.build_graph(root)


def test_every_node_attribute_is_declared_in_the_registry(tmp_path):
    """Сторож: атрибут, который сборщик пишет на узле, объявлен в словаре сущностей.

    Реестр — источник истины; до сих пор совпадение держалось на договорённости, и ревью дважды
    ловило атрибут, заведённый мимо словаря.
    """
    declared = yaml.safe_load((PKG_ROOT / "registry" / "entities.yaml").read_text(encoding="utf-8"))
    allowed = {t: set((spec or {}).get("attributes") or [])
               for t, spec in (declared.get("entity_types") or {}).items()}
    common = {"id", "type", "title", "ref"}
    graphs = [kg.build_graph(PKG_ROOT), _graph_with_every_branch(tmp_path / "child")]
    seen_attrs, unknown = set(), set()
    for node in [n for g in graphs for n in g["nodes"]]:
        extra = set(node) - common - allowed.get(node["type"], set())
        seen_attrs |= {a for a in set(node) - common}
        unknown |= {f"{node['type']}.{a}" for a in extra}
    assert not unknown, f"атрибуты узлов вне registry/entities.yaml: {sorted(unknown)}"
    # Сторож обязан ВИДЕТЬ спорные атрибуты, иначе он зелёный просто потому, что их не встретил.
    assert {"broken_links", "name_taken_in_plan", "declared_goal", "unresolved",
            "verified"} <= seen_attrs, sorted(seen_attrs)


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
