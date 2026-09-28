"""Проходы сборки Knowledge Graph получают ДАННЫЕ, а не корень репозитория (#1134).

Прежде проходы обучения и ревью сами делали `glob` и читали файлы, а паспорта функций и план —
получали прочитанное. Теперь чтение диска живёт в одном месте (`_load_sources`), и каждый проход
проверяется на синтетике без раскладки на диске: путь в записях не существует, а любая попытка
прохода открыть файл роняет тест (`_no_disk`), а не даёт пустой результат по пустому каталогу.
Сборка целиком (`build_graph` над каталогом) — в `test_knowledge_graph.py`.
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


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


_NOWHERE = Path("/nonexistent-kg-1134")


@pytest.fixture()
def _no_disk(monkeypatch):
    """Любая попытка прохода прочитать файл или сделать glob — падение теста, а не пустой результат."""
    def _boom(*_a, **_k):
        raise AssertionError("проход полез на диск: данные должны прийти от загрузки источников")
    monkeypatch.setattr(kg, "_load_yaml", _boom)
    monkeypatch.setattr(Path, "glob", _boom)
    monkeypatch.setattr(Path, "read_text", _boom)
    monkeypatch.setattr(Path, "is_dir", _boom)


def _builder_with_feature(fid: str = "express-checkout") -> kg._Builder:
    b = kg._Builder()
    b.node(fid, "feature", title="Экспресс-чекаут")
    return b


def test_learning_pass_builds_insight_from_given_record_without_disk(_no_disk):
    b = _builder_with_feature()
    fl_path = _NOWHERE / "product-learning" / "FL-001.yaml"
    record = {"id": "FL-001", "feature": "express-checkout", "learnings": ["Повторы выросли"]}

    kg._learning_pass(b, [(fl_path, record)], _NOWHERE / "knowledge",
                      {"express-checkout": "grow-outcome"})

    insight = b.nodes["fl-001"]
    assert insight["type"] == "insight"
    assert insight["title"] == "Повторы выросли"
    assert insight["ref"] == "../product-learning/FL-001.yaml"
    assert {"from": "fl-001", "type": "feeds", "to": "express-checkout"} in b.edges
    assert {"from": "fl-001", "type": "derived-from", "to": "grow-outcome"} in b.edges


def test_learning_pass_declared_outcome_edge_without_disk(_no_disk):
    b = kg._Builder()
    record = {"id": "FL-002", "hypothesis": "Гипотеза", "derived_from_outcome": "Grow-Outcome"}

    kg._learning_pass(b, [(_NOWHERE / "product-learning" / "FL-002.yaml", record)],
                      _NOWHERE / "knowledge", {})

    assert b.nodes["fl-002"]["title"] == "Гипотеза"
    assert b.edges == [{"from": "fl-002", "type": "derived-from", "to": "grow-outcome"}]


def test_learning_pass_skips_record_without_id(_no_disk):
    b = kg._Builder()
    kg._learning_pass(b, [(_NOWHERE / "product-learning" / "FL-x.yaml", {"learnings": ["x"]})],
                      _NOWHERE / "knowledge", {})
    assert b.nodes == {} and b.edges == []


def test_learning_pass_does_not_feed_unknown_feature(_no_disk):
    b = kg._Builder()
    kg._learning_pass(b, [(_NOWHERE / "FL-003.yaml", {"id": "FL-003", "feature": "ghost"})],
                      _NOWHERE / "knowledge", {"ghost": "some-outcome"})
    assert "fl-003" in b.nodes
    assert b.edges == [], "урок к функции, которой нет в графе, не цепляется"


def test_review_pass_builds_review_node_from_given_record_without_disk(_no_disk):
    b = _builder_with_feature()
    record = {"kind": review_verdict.RECORD_KIND, "feature": "express-checkout", "verified": True,
              "reviewed_revision": "abc1234"}

    kg._review_pass(b, [record])

    node = b.nodes["review-express-checkout"]
    assert node["type"] == "review"
    assert node["verified"] is True
    assert node["reviewed_revision"] == "abc1234"
    assert node["ref"] == "features/express-checkout/review/verdict.yaml"
    assert node["title"] == review_verdict.node_title(record)
    assert b.edges == [{"from": "review-express-checkout", "type": "reviewed",
                        "to": "express-checkout"}]


def test_review_pass_skips_record_without_feature(_no_disk):
    b = kg._Builder()
    kg._review_pass(b, [{"kind": review_verdict.RECORD_KIND, "verified": True}])
    assert b.nodes == {} and b.edges == []


def test_review_pass_unverified_record_keeps_false(_no_disk):
    b = kg._Builder()
    kg._review_pass(b, [{"kind": review_verdict.RECORD_KIND, "feature": "f"}])
    assert b.nodes["review-f"]["verified"] is False
    assert "reviewed_revision" not in b.nodes["review-f"]


def test_feature_pass_consumes_sources_without_disk(_no_disk):
    """Паспорт из переданных данных: узел, лестница, метрика, исход, решение, работа по № PR."""
    b = kg._Builder()
    b.node("grow", "goal")
    bp = {"feature": {"id": "express-checkout", "name": "Экспресс-чекаут"},
          "links": {"goal": "grow", "epic": "checkout", "decision": "dp-1", "built_by": 42},
          "metrics": [{"name": "repeat_rate"}]}
    src = kg._Sources(plan={}, blueprints=[(_NOWHERE / "features" / "ec" / "blueprint.yaml", bp)],
                      feature_ids={"express-checkout"}, decisions={"dp-1": "Решили ускорить"},
                      history_works={"w-1": {"title": "Работа", "pr": "42"}},
                      history_pr_index={"42": "w-1"}, learnings=[], review_records=[])
    ctx = kg._PlanContext(goal_outcome={"grow": "grow-outcome"}, name_taken_in_plan={},
                          name_conflict_dropped={})

    outcome = kg._feature_pass(b, src, ctx, _NOWHERE / "knowledge")

    assert outcome == {"express-checkout": "grow-outcome"}
    feat = b.nodes["express-checkout"]
    assert feat["blueprint"] == "../features/ec/blueprint.yaml"
    assert feat["declared_goal"] == "grow"
    metric = "express-checkout-repeat-rate"   # id проходит через _slug: `_` -> `-`
    for edge in ({"from": "grow", "type": "contains", "to": "checkout"},
                 {"from": "checkout", "type": "contains", "to": "express-checkout"},
                 {"from": "express-checkout", "type": "measured-by", "to": metric},
                 {"from": "express-checkout", "type": "targets", "to": "grow-outcome"},
                 {"from": "grow-outcome", "type": "measured-by", "to": metric},
                 {"from": "dp-1", "type": "motivates", "to": "express-checkout"},
                 {"from": "w-1", "type": "builds", "to": "express-checkout"}):
        assert edge in b.edges, edge
    assert b.nodes["w-1"]["pr"] == "42"


def test_feature_losses_names_plan_namesake_on_feature():
    b = kg._Builder()
    b.node("f", "feature")
    ctx = kg._PlanContext(goal_outcome={}, name_taken_in_plan={"f": {"работа", "цель"}},
                          name_conflict_dropped={"f": 3})
    kg._feature_losses(b, {"id": "f"}, "f", [], ctx)
    assert b.nodes["f"]["name_taken_in_plan"] == "цель и работа"
    assert b.nodes["f"]["name_conflict_dropped"] == 3
    assert "broken_links" not in b.nodes["f"]


def test_feature_losses_silent_without_conflict():
    b = kg._Builder()
    b.node("f", "feature")
    kg._feature_losses(b, {"id": "f"}, "f", [], kg._PlanContext({}, {}, {}))
    assert b.nodes["f"] == {"id": "f", "type": "feature"}


def test_plan_pass_returns_named_context():
    b = kg._Builder()
    plan = {"goals": [{"id": "grow", "outcome": {"up": True}}, {"id": "f"}],
            "work": [{"id": "w", "goal": "f"}]}
    ctx = kg._plan_pass(b, plan, {"f"})
    assert isinstance(ctx, kg._PlanContext)
    assert ctx.goal_outcome == {"grow": "grow-outcome"}
    assert ctx.name_taken_in_plan == {"f": {"цель"}}
    assert ctx.name_conflict_dropped == {"f": 1}


def test_load_sources_reads_learnings_and_reviews(tmp_path: Path):
    """Загрузка источников — единственное место чтения: выводы по имени, чужой kind отброшен."""
    root = tmp_path / "child"
    _write(root / "product-learning" / "FL-2.yaml", {"id": "FL-2"})
    _write(root / "product-learning" / "FL-1.yaml", {"id": "FL-1"})
    _write(root / "features" / "a" / "review" / "verdict.yaml",
           {"kind": review_verdict.RECORD_KIND, "feature": "a"})
    _write(root / "features" / "b" / "review" / "verdict.yaml", {"kind": "something-else"})
    _write(root / "features" / "a" / "blueprint.yaml", {"feature": {"id": "A"}})

    src = kg._load_sources(root)

    assert [p.name for p, _ in src.learnings] == ["FL-1.yaml", "FL-2.yaml"]
    assert src.review_records == [{"kind": review_verdict.RECORD_KIND, "feature": "a"}]
    assert src.feature_ids == {"a"}
    assert src.plan == {} and src.decisions == {} and src.history_works == {}


def test_load_sources_on_empty_repo_is_empty(tmp_path: Path):
    src = kg._load_sources(tmp_path)
    assert src.learnings == [] and src.review_records == [] and src.blueprints == []
