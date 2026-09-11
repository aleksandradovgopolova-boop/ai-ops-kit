"""Knowledge Graph как ЗАПРАШИВАЕМАЯ технология — ДОКАЗАТЕЛЬСТВО ЦЕННОСТИ.

Суть работы — не «есть граф», а «граф отвечает на РЕАЛЬНЫЙ вопрос за один проход». Вопрос «зачем
существует функция и подтвердилась ли её ценность» сегодня собирается руками из ТРЁХ файлов: цель и
её outcome — в `planning/plan.yaml`, сама функция — в `features/<id>/blueprint.yaml`, вывод из
данных — в `product-learning/FL-*.yaml`. Тест собирает граф из синтетики этих трёх источников во
временном каталоге и проверяет:

  * `trace(feature)` отвечает на вопрос, который иначе требует чтения трёх файлов — цепочка
    цель→…→функция→исход + вердикт;
  * `gaps()` находит НЕПОКРЫТЫЙ измеримым результатом исход и функцию без результата;
  * отсутствие источника -> честный ПРОБЕЛ, а не выдуманная связь;
  * собранный граф проходит `validate_knowledge_graph` (ссылочная целостность).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import knowledge_graph as kg  # noqa: E402
from ai_ops_kit.validation import validate_knowledge_graph as vkg  # noqa: E402


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture()
def child(tmp_path: Path) -> Path:
    """Синтетический child: две цели (одна с достигнутым исходом), две функции, один вывод.

    express-checkout — полностью проведена: цель -> initiative -> epic -> feature, метрика,
    нацелена на исход цели. wishlist — функция БЕЗ метрики и без цепочки: честный пробел.
    reduce-support-load — цель с исходом, на который НЕ нацелена ни одна функция: непокрытый исход.
    """
    root = tmp_path / "child"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [
            {"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}},
            {"id": "reduce-support-load", "outcome": {"tickets_down": False}},
        ],
        "work": [
            {"id": "checkout-speedup", "goal": "grow-repeat-purchases", "title": "Ускорить чекаут"},
        ],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        "links": {"goal": "grow-repeat-purchases", "initiative": "checkout-q3",
                  "epic": "checkout-epic"},
        "metrics": [{"id": "checkout-conversion", "name": "checkout_started -> completed"}],
        "artifacts": {},
    })
    _write(root / "features" / "wishlist" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "wishlist", "name": "Список желаний",
                    "status": "planned", "current_stage": "discovery"},
        # Ни цели, ни метрики — функция объявлена, но ни к какому измеримому результату не привязана.
        "links": {},
        "artifacts": {},
    })
    _write(root / "product-learning" / "FL-001.yaml", {
        "schema_version": 1, "kind": "FeatureLearning", "id": "FL-001",
        "feature": "express-checkout",
        "learnings": ["Главная фрикция — устаревший сохранённый адрес"],
    })
    return root


# ── Ценность: один вопрос вместо трёх файлов ──────────────────────────────────────────────────────


def test_trace_answers_why_a_feature_exists_from_one_graph(child: Path):
    """`trace` за один проход даёт цепочку цель→…→функция→исход — то, что иначе читается из 3 файлов."""
    graph = kg.build_graph(child)
    result = kg.trace(graph, "express-checkout")

    # Цепочка ведёт ВВЕРХ до цели (из plan.yaml) и заканчивается запрошенной функцией (из blueprint).
    chain_ids = [c["id"] for c in result["chain"]]
    assert chain_ids[0] == "grow-repeat-purchases"
    assert chain_ids[-1] == "express-checkout"
    assert result["chain"][0]["type"] == "goal"
    assert result["goal"] == "grow-repeat-purchases"

    # Вперёд — к исходу (из plan.yaml outcome), измеренному метрикой (из blueprint).
    assert result["outcome"]["id"] == "grow-repeat-purchases-outcome"
    assert result["outcome"]["verdict"] == "met"
    assert "checkout-conversion" in result["outcome"]["measured_by"]

    # Полная цепочка с измеренным исходом — вердикт «подтверждено», пробелов нет.
    assert result["verdict"] == "confirmed"
    assert result["gaps"] == []


def test_gaps_finds_uncovered_outcome_and_feature_without_result(child: Path):
    """`gaps` находит непокрытый исход и функцию без измеримого результата."""
    graph = kg.build_graph(child)
    g = kg.gaps(graph)

    # Исход цели reduce-support-load не измеряется ни одной метрикой (ни одна функция на него не
    # нацелена) -> непокрытый исход.
    uncovered = {o["id"] for o in g["outcomes_without_metric"]}
    assert "reduce-support-load-outcome" in uncovered
    # А покрытый исход express-checkout в список НЕ попадает.
    assert "grow-repeat-purchases-outcome" not in uncovered

    # wishlist объявлена, но ни на какой исход не нацелена -> функция без результата.
    no_result = {f["id"] for f in g["features_without_outcome"]}
    assert "wishlist" in no_result
    assert "express-checkout" not in no_result


def test_missing_source_is_an_honest_gap_not_an_invented_link(child: Path):
    """Нет источника -> нет связи. wishlist без метрики/цепочки — НАЗВАННЫЙ пробел, не выдумка."""
    graph = kg.build_graph(child)
    result = kg.trace(graph, "wishlist")

    # У wishlist нет ребра targets (blueprint не дал ни метрики, ни полной цепочки к исходу).
    assert result["outcome"] is None
    assert result["verdict"] in ("no-outcome", "unmoored")
    assert any("targets" in gap or "outcome" in gap for gap in result["gaps"])

    # Связь НЕ выдумана: в графе нет ребра targets из wishlist.
    targets = [e for e in graph["edges"] if e["type"] == "targets" and e["from"] == "wishlist"]
    assert targets == []


def test_unknown_feature_reports_gap_without_crashing(child: Path):
    graph = kg.build_graph(child)
    result = kg.trace(graph, "no-such-feature")
    assert result["verdict"] == "unknown"
    assert result["chain"] == []
    assert result["gaps"] and "нет в графе" in result["gaps"][0]


def test_insight_links_only_to_existing_nodes(child: Path):
    """FL-узел даёт ребро только к существующей функции/исходу — иначе dangling reference."""
    graph = kg.build_graph(child)
    ids = {n["id"] for n in graph["nodes"]}
    assert "fl-001" in ids
    feeds = [e for e in graph["edges"] if e["from"] == "fl-001" and e["type"] == "feeds"]
    assert {"from": "fl-001", "type": "feeds", "to": "express-checkout"} in feeds
    # derived-from к исходу той функции (insight выведен из измеримого результата).
    derived = [e for e in graph["edges"] if e["from"] == "fl-001" and e["type"] == "derived-from"]
    assert derived and derived[0]["to"] == "grow-repeat-purchases-outcome"


# ── Целостность: собранный граф валиден по общему валидатору ───────────────────────────────────────


def test_built_graph_passes_validate_knowledge_graph(child: Path):
    """Граф, собранный сборщиком, проходит ссылочную целостность validate_knowledge_graph."""
    graph = kg.build_graph(child)
    # blueprint-пути в графе — относительно child/knowledge; приводим к абсолютным для проверки.
    graph_dir = child / "knowledge"
    for n in graph["nodes"]:
        if n.get("blueprint"):
            n["blueprint"] = str((graph_dir / n["blueprint"]).resolve())
    types, rels = vkg.load_dictionary()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "graph.yaml"
        p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
        errors = vkg.validate_graph(p, types, rels)
    assert errors == [], f"собранный граф не прошёл валидатор: {errors}"


def test_empty_repo_yields_empty_but_valid_graph(tmp_path: Path):
    """Нет источников — граф пустой по узлам, но структурно валиден (kind/schema_version)."""
    graph = kg.build_graph(tmp_path)
    assert graph["kind"] == "knowledge-graph"
    assert graph["schema_version"] == 1
    assert graph["nodes"] == []
    assert graph["edges"] == []
