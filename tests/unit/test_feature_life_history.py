"""Десять вопросов жизни фичи — ДОКАЗАТЕЛЬСТВО МЕХАНИЗМА на фикстуре.

Приёмка направления `product-memory-org-intelligence` дословно: на ОДНОЙ реальной фиче кит отвечает
на десять вопросов её жизни ИЗ СВЯЗАННЫХ УЛИК, а не генерацией. Полевая приёмка на реальной фиче
ii-sreda остаётся за владельцем (см. `qualification/TEN-QUESTIONS-MECHANISM-2026-09-28.md`); здесь
доказывается сам МЕХАНИЗМ на синтетике источников кита:

  * функция с ПОЛНОЙ историей (цель+исход, решение, работа/PR, ревью, урок с гипотезой/выводами/
    следующим шагом, аудитория) -> отвечены все десять, у каждого ответа есть улика (id узла/ребра);
  * функция с пробелами -> недостающие вопросы честно «неизвестно» с указанием, какого звена не
    хватает, а НЕ выдуманным ответом;
  * функции нет в графе -> все десять «неизвестно» по одной причине (строить не из чего).

Новый модуль грузится по пути (spec_from_file_location) — поведенческий тест, чистота корня.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import knowledge_graph as kg  # noqa: E402
from ai_ops_kit.validation import validate_knowledge_graph as vkg  # noqa: E402

# Механизм живёт в сателлите обхода графа; грузим его по пути (поведенческий тест, чистота корня).
_FLH_PATH = PKG_ROOT / "ai_ops_kit" / "intelligence" / "knowledge_graph_query.py"
_spec = importlib.util.spec_from_file_location("_flh_under_test", _FLH_PATH)
flh = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_flh_under_test", flh)
_spec.loader.exec_module(flh)


def _answer(graph, feature, child_root=None, **kw):
    """Собрать поля первоисточника фасадом (если дан корень) и ответить на десять вопросов."""
    source = kg.feature_life_source(graph, feature, child_root) if child_root is not None else None
    return flh.answer_ten_questions(graph, feature, source=source, **kw)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture()
def child(tmp_path: Path) -> Path:
    """Child с ДВУМЯ функциями: express-checkout — полная история; wishlist — сплошные пробелы."""
    root = tmp_path / "child"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [
            {"id": "grow-repeat-purchases", "outcome": {"repeat_rate_up": True}},
        ],
        "work": [
            {"id": "checkout-speedup", "goal": "grow-repeat-purchases", "title": "Ускорить чекаут"},
        ],
    })
    # Полная история: паспорт объявляет цель, решение, построившую работу, аудиторию + метрику.
    _write(root / "features" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Экспресс-чекаут",
                    "status": "in-progress", "current_stage": "analytics",
                    "audience": "повторные покупатели с сохранённым адресом"},
        "links": {"goal": "grow-repeat-purchases",
                  "decision": "ep-2026-08-01-fast-checkout",
                  "built_by": "checkout-vertical-slice"},
        "metrics": [{"id": "checkout-conversion", "name": "checkout_started -> completed"}],
        "artifacts": {},
    })
    # Пробел: только id функции, ни цели, ни решения, ни аудитории, ни урока, ни ревью.
    _write(root / "features" / "wishlist" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "wishlist", "name": "Список желаний",
                    "status": "planned", "current_stage": "discovery"},
        "links": {},
        "artifacts": {},
    })
    # Решение, из которого функция появилась.
    _write(root / "decisions" / "registry.yaml", {
        "episodes": [
            {"id": "ep-2026-08-01-fast-checkout",
             "decision": "убрать шаг адреса для повторных покупателей"},
        ],
    })
    # История работ (built_by резолвится в узел work с PR).
    _write(root / "history" / "plan-history.yaml", {
        "work": [
            {"id": "checkout-vertical-slice", "title": "Чекаут одной вертикалью", "pr": "742"},
        ],
    })
    # Урок с гипотезой, выводами, выбранным решением и следующим шагом.
    _write(root / "product-learning" / "FL-010.yaml", {
        "schema_version": 1, "kind": "FeatureLearning", "id": "FL-010",
        "feature": "express-checkout",
        "hypothesis": "устаревший сохранённый адрес — главная фрикция повторной покупки",
        "learnings": ["адрес правда был фрикцией", "самовывоз просят реже, чем думали"],
        "follow_up": ["добавить быстрый выбор из истории адресов"],
        "solution_options": [
            {"option": "убрать шаг адреса для повторных", "chosen": True,
             "reason": "самый короткий путь к завершению покупки"},
            {"option": "переписать весь чекаут", "chosen": False,
             "reason": "дорого и рискованно на этом шаге"},
        ],
    })
    # Персистентный вердикт ревью (пишет путь ревью, не писатель): «проверили машиной».
    _write(root / "features" / "express-checkout" / "review" / "verdict.yaml", {
        "schema_version": 1, "kind": "review-verdict", "feature": "express-checkout",
        "verified": True, "reviewed_revision": "abc1234",
        "checked_by": {"deterministic": ["tests-green"], "ai_judgment": [], "human": []},
    })
    return root


# ── Полная история: все десять отвечены из улик ───────────────────────────────────────────────────


def test_full_history_answers_all_ten_from_linked_evidence(child: Path):
    """На фиче с полной историей отвечены все десять вопросов, и у каждого есть улика в графе."""
    graph = kg.build_graph(child)
    # Реальный сдвиг метрики и следующий шаг обычно даёт слой CLI из контракта; здесь передаём явно,
    # чтобы вопросы 8 и 10 отвечались измеренным/выведенным, как в бою.
    measured = {"measured": True, "verdict": "met", "baseline": "40%", "value": "48%",
                "target": "45%"}
    nxt = {"action": "добавить быстрый выбор адреса", "because": "цель взята, а адрес всё ещё трение"}
    res = _answer(graph, "express-checkout", child_root=child,
                                   measured_outcome=measured, next_action=nxt)

    assert res["total"] == 10
    assert res["complete"] is True, [q for q in res["questions"] if not q["answered"]]
    assert res["answered_count"] == 10

    # Порядок вопросов — дословный порядок приёмки.
    assert [q["id"] for q in res["questions"]] == [k for k, _ in flh.TEN_QUESTIONS]

    by_id = {q["id"]: q for q in res["questions"]}
    # Каждый ответ подтверждён уликой (id узла/ребра), а не пуст.
    for q in res["questions"]:
        assert q["answered"] is True
        assert q["evidence"], q["id"]
        assert q["unknown_reason"] is None

    # Точечно: улика реально указывает на связанные сущности графа.
    assert "ep-2026-08-01-fast-checkout" in by_id["why_arose"]["evidence"]
    assert "grow-repeat-purchases" in by_id["problem"]["evidence"]
    assert "повторные покупатели" in by_id["audience"]["answer"]
    assert "фрикция" in by_id["hypothesis"]["answer"]
    assert "самый короткий путь" in by_id["solution_rationale"]["answer"]
    assert "742" in by_id["built"]["answer"]
    assert "машина" in by_id["proven"]["answer"]
    assert "48%" in by_id["after_release"]["answer"]
    assert "фрикцией" in by_id["learnings"]["answer"]
    assert "быстрый выбор" in by_id["next"]["answer"]


def test_evidence_ids_exist_in_the_graph(child: Path):
    """Улики — не украшение: каждый id-узла из evidence реально есть в собранном графе."""
    graph = kg.build_graph(child)
    node_ids = {n["id"] for n in graph["nodes"]}
    res = _answer(graph, "express-checkout", child_root=child)
    for q in res["questions"]:
        if not q["answered"]:
            continue
        for ev in q["evidence"]:
            # Улика — либо id узла, либо строка ребра «a -rel-> b», путь к артефакту или маркер.
            if ev is None or "->" in ev or "/" in ev or ev in ("measured_outcome", "next_action"):
                continue
            assert ev in node_ids, f"{q['id']}: улика {ev!r} не найдена среди узлов графа"


def test_without_child_root_source_bound_questions_are_honest_unknowns(child: Path):
    """Без корня репозитория граф один не несёт гипотезу/аудиторию/выводы — честное «неизвестно».

    Связь урока с функцией граф видит (ребро feeds), но САМИ поля живут в первоисточнике; молчаливо
    выдумывать их из графа нельзя, поэтому причина прямо зовёт дать child_root."""
    graph = kg.build_graph(child)
    res = _answer(graph, "express-checkout")  # без child_root
    by_id = {q["id"]: q for q in res["questions"]}
    # Вопросы из графа — по-прежнему отвечены.
    assert by_id["why_arose"]["answered"] and by_id["problem"]["answered"]
    assert by_id["built"]["answered"] and by_id["proven"]["answered"]
    # А вопросы из первоисточника — честный пробел с адресом причины, не выдумка.
    for qid in ("audience", "hypothesis", "solution_rationale", "learnings"):
        assert not by_id[qid]["answered"]
        assert "child_root" in by_id[qid]["unknown_reason"]


# ── Пробелы: честное «неизвестно», а не выдумка ───────────────────────────────────────────────────


def test_gaps_are_honest_unknowns_not_invented(child: Path):
    """У функции без истории недостающие вопросы «неизвестно» с причиной, ответ НЕ выдуман."""
    graph = kg.build_graph(child)
    res = _answer(graph, "wishlist", child_root=child)

    assert res["complete"] is False
    # Ни одного выдуманного ответа: где не отвечено — answer пуст, причина названа.
    for q in res["questions"]:
        if not q["answered"]:
            assert q["answer"] is None
            assert q["unknown_reason"]
            assert q["evidence"] == []

    by_id = {q["id"]: q for q in res["questions"]}
    # Проверяем, что причина указывает НА НЕДОСТАЮЩЕЕ ЗВЕНО, а не общая отписка.
    assert "motivates" in by_id["why_arose"]["unknown_reason"]
    assert "feeds" in by_id["hypothesis"]["unknown_reason"]
    assert "audience" in by_id["audience"]["unknown_reason"]
    assert "builds" in by_id["built"]["unknown_reason"]
    assert "reviewed" in by_id["proven"]["unknown_reason"]


def test_unknown_feature_reports_all_ten_unknown_by_one_reason(child: Path):
    """Функции нет в графе -> все десять «неизвестно» по одной причине (строить не из чего)."""
    graph = kg.build_graph(child)
    res = _answer(graph, "no-such-feature")

    assert res["verdict"] == "unknown"
    assert res["answered_count"] == 0
    assert len(res["questions"]) == 10
    reasons = {q["unknown_reason"] for q in res["questions"]}
    assert len(reasons) == 1
    assert "нет в графе" in reasons.pop()


# ── Целостность: обогащённый граф всё ещё валиден ─────────────────────────────────────────────────


def test_enriched_graph_still_passes_integrity(child: Path, tmp_path: Path):
    """Новые атрибуты узлов (audience/hypothesis/…) не ломают ссылочную целостность графа."""
    import tempfile
    graph = kg.build_graph(child)
    # blueprint-пути делаем абсолютными, как это делает CLI перед валидацией.
    graph_dir = child / "knowledge"
    for n in graph["nodes"]:
        if n.get("blueprint"):
            n["blueprint"] = str((graph_dir / n["blueprint"]).resolve())
    types, rels = vkg.load_dictionary()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "graph.yaml"
        p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
        errors = vkg.validate_graph(p, types, rels)
    assert errors == [], errors
