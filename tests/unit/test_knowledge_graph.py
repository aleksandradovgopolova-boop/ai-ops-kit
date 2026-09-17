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


# ── «Зачем функция существует»: связь РЕШЕНИЕ → ФУНКЦИЯ из истории, а не пересказ кода ──────────────


@pytest.fixture()
def child_decision(tmp_path: Path) -> Path:
    """Синтетический child с журналом решений: одна функция ссылается на решение, другая — нет.

    express-checkout объявляет `links.decision: ep-...` -> в графе появляется узел решения и ребро
    decision -motivates-> feature. wishlist решения не объявляет -> ребра нет (честно: причина не
    записана). Это доказывает и «зачем» из истории, и инвариант «нет ссылки — нет связи».
    """
    root = tmp_path / "child_dec"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
        "work": [],
    })
    _write(root / "decisions" / "registry.yaml", {
        "schema_version": 1, "kind": "decisions-registry",
        "episodes": [
            {"id": "ep-2026-08-14-product-os",
             "question": "Куда идёт кит после закрытия quality-контура?",
             "decision": "Владелец объявил Product OS: одна вертикальная функция целиком.",
             "reason": "Разрыв между обещанным и исполняемым закрывается одной функцией.",
             "reversibility": "two-way", "date": "2026-08-14"},
        ],
        "principles": [
            {"id": "dp-004",
             "principle": "Оптимизируем расстояние от намерения до проверенного результата."},
        ],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        "links": {"goal": "grow-repeat-purchases", "decision": "ep-2026-08-14-product-os"},
        "artifacts": {},
    })
    _write(root / "features" / "wishlist" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "wishlist", "name": "Список желаний",
                    "status": "planned", "current_stage": "discovery"},
        "links": {},
        "artifacts": {},
    })
    return root


def test_decision_edge_built_from_blueprint_link(child_decision: Path):
    """Ссылка `links.decision` -> узел decision (текст решения) + ребро decision -motivates-> feature."""
    graph = kg.build_graph(child_decision)
    by_id = {n["id"]: n for n in graph["nodes"]}

    # Узел решения появился из decisions/registry.yaml с ЧЕЛОВЕЧЕСКИМ текстом, а не пересказом кода.
    assert "ep-2026-08-14-product-os" in by_id
    dnode = by_id["ep-2026-08-14-product-os"]
    assert dnode["type"] == "decision"
    assert "Product OS" in dnode["title"]

    # Ребро decision -motivates-> feature построено.
    assert {"from": "ep-2026-08-14-product-os", "type": "motivates",
            "to": "express-checkout"} in graph["edges"]


def test_trace_reports_why_a_feature_exists_from_decision(child_decision: Path):
    """`trace` называет РЕШЕНИЕ, из которого функция появилась — ответ на «зачем она есть»."""
    graph = kg.build_graph(child_decision)
    result = kg.trace(graph, "express-checkout")

    assert result["decision"] is not None
    assert result["decision"]["id"] == "ep-2026-08-14-product-os"
    assert "Product OS" in result["decision"]["title"]


def test_no_decision_link_means_no_edge_and_not_a_gap(child_decision: Path):
    """Нет ссылки в blueprint -> нет ребра motivates. Это честная неизвестность, а НЕ пробел."""
    graph = kg.build_graph(child_decision)
    motivates_to_wishlist = [e for e in graph["edges"]
                             if e["type"] == "motivates" and e["to"] == "wishlist"]
    assert motivates_to_wishlist == []

    result = kg.trace(graph, "wishlist")
    assert result["decision"] is None
    # Отсутствие «зачем» из истории не объявляется пробелом: причина может быть просто не записана.
    assert not any("motivates" in g or "решени" in g for g in result["gaps"])


def test_broken_decision_ref_is_rejected_by_validator(tmp_path: Path):
    """Ссылка на несуществующее решение оставляет висящее ребро -> validate_knowledge_graph краснит."""
    root = tmp_path / "child_broken"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "decisions" / "registry.yaml", {
        "schema_version": 1, "kind": "decisions-registry", "episodes": [],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        # Ссылка на решение, которого в реестре НЕТ — сломанная декларация.
        "links": {"goal": "grow-repeat-purchases", "decision": "ep-does-not-exist"},
        "artifacts": {},
    })
    graph = kg.build_graph(root)

    # Ребро выпущено (декларация есть), но узла решения нет — граф не сходится сам с собой.
    assert {"from": "ep-does-not-exist", "type": "motivates",
            "to": "express-checkout"} in graph["edges"]
    assert "ep-does-not-exist" not in {n["id"] for n in graph["nodes"]}

    graph_dir = root / "knowledge"
    for n in graph["nodes"]:
        if n.get("blueprint"):
            n["blueprint"] = str((graph_dir / n["blueprint"]).resolve())
    types, rels = vkg.load_dictionary()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "graph.yaml"
        p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
        errors = vkg.validate_graph(p, types, rels)
    assert any("ep-does-not-exist" in e for e in errors), \
        f"валидатор обязан поймать висящую ссылку на решение: {errors}"


def test_decision_graph_passes_validator_when_ref_resolves(child_decision: Path):
    """Граф с валидной ссылкой на решение проходит ссылочную целостность validate_knowledge_graph."""
    graph = kg.build_graph(child_decision)
    graph_dir = child_decision / "knowledge"
    for n in graph["nodes"]:
        if n.get("blueprint"):
            n["blueprint"] = str((graph_dir / n["blueprint"]).resolve())
    types, rels = vkg.load_dictionary()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "graph.yaml"
        p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
        errors = vkg.validate_graph(p, types, rels)
    assert errors == [], f"граф с решением не прошёл валидатор: {errors}"


# ── «Что построило функцию»: связь РАБОТА/PR → ФУНКЦИЯ из истории, а не пересказ кода ──────────────


def _validate_built(root: Path, graph: dict) -> list[str]:
    """Прогнать собранный граф через validate_knowledge_graph (blueprint-пути -> абсолютные)."""
    graph_dir = root / "knowledge"
    for n in graph["nodes"]:
        if n.get("blueprint"):
            n["blueprint"] = str((graph_dir / n["blueprint"]).resolve())
    types, rels = vkg.load_dictionary()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "graph.yaml"
        p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
        return vkg.validate_graph(p, types, rels)


@pytest.fixture()
def child_work(tmp_path: Path) -> Path:
    """Child с историей работ: одна функция ссылается на работу по id, вторая — по № PR, третья — нет.

    express-checkout объявляет `built_by: [checkout-speedup]` -> узел work + ребро work -builds->
    feature. quick-buy объявляет `built_by: 991` (№ PR той же работы) -> резолвится в тот же узел.
    wishlist не объявляет built_by -> ребра нет (честно: история не записала, кто построил).
    """
    root = tmp_path / "child_work"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "history" / "plan-history.yaml", {
        "schema_version": 1, "kind": "delivery-plan-history",
        "work": [
            {"id": "checkout-speedup", "title": "Ускорить чекаут", "pr": 991,
             "status": "done", "result": "ЗАКРЫТО: чекаут ускорен, конверсия выросла."},
        ],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        "links": {"goal": "grow-repeat-purchases", "built_by": ["checkout-speedup"]},
        "artifacts": {},
    })
    _write(root / "features" / "quick-buy" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "quick-buy", "name": "Покупка в один клик",
                    "status": "in-progress", "current_stage": "delivery"},
        "links": {"built_by": 991},   # ссылка по НОМЕРУ PR, а не по id работы
        "artifacts": {},
    })
    _write(root / "features" / "wishlist" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "wishlist", "name": "Список желаний",
                    "status": "planned", "current_stage": "discovery"},
        "links": {},
        "artifacts": {},
    })
    return root


def test_builds_edge_from_blueprint_link(child_work: Path):
    """Ссылка `links.built_by` -> узел work (название + PR) + ребро work -builds-> feature."""
    graph = kg.build_graph(child_work)
    by_id = {n["id"]: n for n in graph["nodes"]}

    assert "checkout-speedup" in by_id
    wnode = by_id["checkout-speedup"]
    assert wnode["type"] == "work"
    assert wnode["title"] == "Ускорить чекаут"
    assert wnode["pr"] == "991"

    assert {"from": "checkout-speedup", "type": "builds",
            "to": "express-checkout"} in graph["edges"]


def test_built_by_by_pr_number_resolves_to_the_same_work(child_work: Path):
    """Ссылка `built_by` номером PR резолвится в тот же узел работы, что и ссылка по id."""
    graph = kg.build_graph(child_work)
    # quick-buy сослалась на PR 991 -> ребро из работы checkout-speedup (её PR), не из узла «991».
    assert {"from": "checkout-speedup", "type": "builds", "to": "quick-buy"} in graph["edges"]
    assert "991" not in {n["id"] for n in graph["nodes"]}


def test_no_built_by_means_no_edge_and_not_a_gap(child_work: Path):
    """Нет ссылки в blueprint -> нет ребра builds. Честная неизвестность, а НЕ пробел."""
    graph = kg.build_graph(child_work)
    builds_to_wishlist = [e for e in graph["edges"]
                          if e["type"] == "builds" and e["to"] == "wishlist"]
    assert builds_to_wishlist == []

    result = kg.trace(graph, "wishlist")
    assert result["built_by"] == []
    assert not any("builds" in g or "построил" in g for g in result["gaps"])


def test_trace_reports_what_built_a_feature(child_work: Path):
    """`trace` называет РАБОТУ (и PR), построившую функцию — ответ на «что построили и где»."""
    graph = kg.build_graph(child_work)
    result = kg.trace(graph, "express-checkout")
    assert result["built_by"]
    first = result["built_by"][0]
    assert first["id"] == "checkout-speedup"
    assert first["title"] == "Ускорить чекаут"
    assert first["pr"] == "991"


def test_broken_built_by_ref_is_rejected_by_validator(tmp_path: Path):
    """Ссылка на несуществующую работу оставляет висящее ребро -> validate_knowledge_graph краснит."""
    root = tmp_path / "child_work_broken"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "history" / "plan-history.yaml", {
        "schema_version": 1, "kind": "delivery-plan-history", "work": [],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        "links": {"built_by": ["work-does-not-exist"]},
        "artifacts": {},
    })
    graph = kg.build_graph(root)

    assert {"from": "work-does-not-exist", "type": "builds",
            "to": "express-checkout"} in graph["edges"]
    assert "work-does-not-exist" not in {n["id"] for n in graph["nodes"]}

    errors = _validate_built(root, graph)
    assert any("work-does-not-exist" in e for e in errors), \
        f"валидатор обязан поймать висящую ссылку на работу: {errors}"


def test_work_graph_passes_validator_when_ref_resolves(child_work: Path):
    """Граф с валидной ссылкой на работу проходит ссылочную целостность validate_knowledge_graph."""
    graph = kg.build_graph(child_work)
    errors = _validate_built(child_work, graph)
    assert errors == [], f"граф с работой не прошёл валидатор: {errors}"


# ── «Чему научились по результату»: явная связь УРОК → OUTCOME (декларация, не косвенный вывод) ─────


@pytest.fixture()
def child_learning(tmp_path: Path) -> Path:
    """Child, где урок ЯВНО объявляет outcome, из которого извлечён (без совпадения по feature).

    FL-010 объявляет `derived_from_outcome: grow-repeat-purchases-outcome` -> ребро insight
    -derived-from-> outcome, хотя его `feature` не совпадает ни с одним узлом функции (косвенной
    привязки нет — работает только декларация).
    """
    root = tmp_path / "child_learning"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "product-learning" / "FL-010.yaml", {
        "schema_version": 1, "kind": "FeatureLearning", "id": "FL-010",
        "feature": "architecture:some-module",       # НЕ узел-функция графа -> feeds не сработает
        "learnings": ["Повторные покупки растут при сохранённом адресе"],
        "derived_from_outcome": "grow-repeat-purchases-outcome",
    })
    return root


def test_learning_derived_from_outcome_edge_is_declared(child_learning: Path):
    """`derived_from_outcome` -> ребро insight -derived-from-> outcome напрямую (без косвенного вывода)."""
    graph = kg.build_graph(child_learning)
    ids = {n["id"] for n in graph["nodes"]}
    assert "fl-010" in ids
    assert {"from": "fl-010", "type": "derived-from",
            "to": "grow-repeat-purchases-outcome"} in graph["edges"]
    # Косвенной привязки по feature нет: feeds к функции не появилось.
    assert [e for e in graph["edges"] if e["from"] == "fl-010" and e["type"] == "feeds"] == []


def test_learning_graph_passes_validator_when_outcome_ref_resolves(child_learning: Path):
    """Граф с явной ссылкой урок->outcome проходит validate_knowledge_graph."""
    graph = kg.build_graph(child_learning)
    errors = _validate_built(child_learning, graph)
    assert errors == [], f"граф с уроком->outcome не прошёл валидатор: {errors}"


def test_broken_derived_from_outcome_ref_is_rejected_by_validator(tmp_path: Path):
    """Ссылка урока на несуществующий outcome оставляет висящее ребро -> валидатор краснит."""
    root = tmp_path / "child_learning_broken"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "product-learning" / "FL-011.yaml", {
        "schema_version": 1, "kind": "FeatureLearning", "id": "FL-011",
        "feature": "architecture:some-module",
        "learnings": ["Урок из несуществующего исхода"],
        "derived_from_outcome": "no-such-outcome",
    })
    graph = kg.build_graph(root)
    assert {"from": "fl-011", "type": "derived-from", "to": "no-such-outcome"} in graph["edges"]
    assert "no-such-outcome" not in {n["id"] for n in graph["nodes"]}

    errors = _validate_built(root, graph)
    assert any("no-such-outcome" in e for e in errors), \
        f"валидатор обязан поймать висящую ссылку урока на outcome: {errors}"


def test_no_derived_from_outcome_field_means_no_declared_edge(tmp_path: Path):
    """Нет поля `derived_from_outcome` и нет совпадения по feature -> объявленного ребра нет."""
    root = tmp_path / "child_learning_none"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "product-learning" / "FL-012.yaml", {
        "schema_version": 1, "kind": "FeatureLearning", "id": "FL-012",
        "feature": "architecture:some-module",
        "learnings": ["Урок без объявленного исхода"],
    })
    graph = kg.build_graph(root)
    derived = [e for e in graph["edges"] if e["from"] == "fl-012" and e["type"] == "derived-from"]
    assert derived == []


# ── «Кто/что проверил функцию»: связь REVIEW-ВЕРДИКТ → ФУНКЦИЯ из персистентной записи ─────────────


@pytest.fixture()
def child_review(tmp_path: Path) -> Path:
    """Child, где у одной функции ЕСТЬ персистентный review-вердикт, а у другой — нет.

    express-checkout несёт `features/express-checkout/review/verdict.yaml` (проверено машиной и
    независимым ревьюером) -> узел review + ребро review -reviewed-> feature. wishlist записи не имеет
    -> ребра нет (честно: проверки могло не быть, это НЕ пробел).
    """
    root = tmp_path / "child_review"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics"},
        "links": {"goal": "grow-repeat-purchases"},
        "artifacts": {},
    })
    _write(root / "features" / "wishlist" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "wishlist", "name": "Список желаний",
                    "status": "planned", "current_stage": "discovery"},
        "links": {},
        "artifacts": {},
    })
    _write(root / "features" / "express-checkout" / "review" / "verdict.yaml", {
        "schema_version": 1, "kind": "review-verdict", "feature": "express-checkout",
        "reviewed_revision": "abc1234", "reviewed_at": "2026-09-17T00:00:00+00:00",
        "verified": True,
        "checked_by": {"deterministic": ["implementation_verification"],
                       "ai_judgment": ["code_review"], "human": []},
        "reason": "есть детерминированная опора (implementation_verification) — verified",
    })
    return root


def test_review_edge_built_from_persistent_record(child_review: Path):
    """Запись review/verdict.yaml -> узел review (кем проверено) + ребро review -reviewed-> feature."""
    graph = kg.build_graph(child_review)
    by_id = {n["id"]: n for n in graph["nodes"]}

    assert "review-express-checkout" in by_id
    rnode = by_id["review-express-checkout"]
    assert rnode["type"] == "review"
    assert rnode["verified"] is True
    # Заголовок называет, КЕМ проверено — машиной и независимым ревьюером.
    assert "машина" in rnode["title"] and "независимый ревьюер" in rnode["title"]

    assert {"from": "review-express-checkout", "type": "reviewed",
            "to": "express-checkout"} in graph["edges"]


def test_trace_reports_who_checked_a_feature(child_review: Path):
    """`trace` называет, КТО проверил функцию — ответ на «кто/что проверил» из истории, не из прогона."""
    graph = kg.build_graph(child_review)
    result = kg.trace(graph, "express-checkout")
    assert result["review"] is not None
    assert result["review"]["verified"] is True
    assert "машина" in result["review"]["title"]
    assert result["review"]["reviewed_revision"] == "abc1234"


def test_no_review_record_means_no_edge_and_not_a_gap(child_review: Path):
    """Нет записи -> нет ребра reviewed. Честная неизвестность (проверки могло не быть), а НЕ пробел."""
    graph = kg.build_graph(child_review)
    reviewed_to_wishlist = [e for e in graph["edges"]
                            if e["type"] == "reviewed" and e["to"] == "wishlist"]
    assert reviewed_to_wishlist == []

    result = kg.trace(graph, "wishlist")
    assert result["review"] is None
    assert not any("reviewed" in g or "провер" in g for g in result["gaps"])


def test_review_graph_passes_validator_when_feature_resolves(child_review: Path):
    """Граф с валидной записью review проходит ссылочную целостность validate_knowledge_graph."""
    graph = kg.build_graph(child_review)
    errors = _validate_built(child_review, graph)
    assert errors == [], f"граф с review-вердиктом не прошёл валидатор: {errors}"


def test_broken_review_ref_is_rejected_by_validator(tmp_path: Path):
    """Запись, ссылающаяся на несуществующую фичу, оставляет висящее ребро -> валидатор краснит."""
    root = tmp_path / "child_review_broken"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}}],
    })
    # Запись review есть, а blueprint функции — НЕТ: сломанная запись.
    _write(root / "features" / "ghost-feature" / "review" / "verdict.yaml", {
        "schema_version": 1, "kind": "review-verdict", "feature": "ghost-feature",
        "reviewed_revision": "def5678", "reviewed_at": "2026-09-17T00:00:00+00:00",
        "verified": False,
        "checked_by": {"deterministic": [], "ai_judgment": ["code_review"], "human": []},
        "reason": "принял независимый ревьюер",
    })
    graph = kg.build_graph(root)

    assert {"from": "review-ghost-feature", "type": "reviewed",
            "to": "ghost-feature"} in graph["edges"]
    assert "ghost-feature" not in {n["id"] for n in graph["nodes"]}

    errors = _validate_built(root, graph)
    assert any("ghost-feature" in e for e in errors), \
        f"валидатор обязан поймать висящую ссылку review на фичу: {errors}"
