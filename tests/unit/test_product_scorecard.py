"""Карта продукта кита из 5 метрик — ДОКАЗАТЕЛЬСТВО, что кит мерит себя как продукт, честно.

Суть работы не «есть карта», а: три метрики (1 доля фич идея->релиз, 2 доля утверждений с evidence,
3 доля фич с полной историей жизни) СЧИТАЮТСЯ на реальных данных, а две (4 результат после релиза,
5 уроки->решения) честно рапортуют «не измерено» — потому что живой аналитики у самого кита нет, и
выдуманное число было бы враньём. Тест собирает синтетический репозиторий во временном каталоге и
проверяет каждое звено по отдельности и карту как целое.

Инвариант, который здесь и стережётся: ЧЕСТНОСТЬ ПРЕВЫШЕ ПОЛНОТЫ — нет данных -> `measured=False` с
причиной, НИКОГДА выдуманное значение.
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
from ai_ops_kit.intelligence import product_scorecard as ps  # noqa: E402
from ai_ops_kit.ui import presenter  # noqa: E402

pytestmark = pytest.mark.unit


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture()
def child(tmp_path: Path) -> Path:
    """Синтетический репозиторий: две реальные фичи + один учебный demo-паспорт.

    `f-full` — полная нить: решение (motivates) + работа/PR (builds) + ревью (reviewed) + нацелена
    на исход цели (targets). `f-partial` — только решение + работа (дошла до релиза, но без ревью и
    без исхода). `express-checkout` — demo-паспорт из examples/: в карте продукта КИТА не считается.
    """
    root = tmp_path / "repo"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "make-kit-a-product", "outcome": {"measured_as_product": True}}],
        "work": [{"id": "w-full", "goal": "make-kit-a-product", "title": "Собрать карту"}],
    })
    _write(root / "decisions" / "registry.yaml", {
        "schema_version": 1, "kind": "decision-registry",
        "episodes": [{"id": "ep-1", "decision": "Мерить кит как продукт, а не числом возможностей"}],
    })
    _write(root / "history" / "plan-history.yaml", {
        "schema_version": 1, "kind": "plan-history",
        "work": [{"id": "w-full", "title": "Собрать карту продукта", "pr": 100}],
    })
    # f-full: замкнуты все четыре звена нити.
    _write(root / "features" / "f-full" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "f-full", "name": "Полная фича", "current_stage": "delivery"},
        "links": {"goal": "make-kit-a-product", "decision": "ep-1", "built_by": 100},
        "artifacts": {},
    })
    _write(root / "features" / "f-full" / "review" / "verdict.yaml", {
        "schema_version": 1, "kind": "review-verdict", "feature": "f-full",
        "verified": True, "reviewed_revision": "abc123",
    })
    # f-partial: дошла до релиза (решение+работа), но без ревью и без исхода.
    _write(root / "features" / "f-partial" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "f-partial", "name": "Частичная фича", "current_stage": "delivery"},
        "links": {"decision": "ep-1", "built_by": 100},
        "artifacts": {},
    })
    # Учебный demo-паспорт: НЕ реальная фича кита — карта его не считает.
    _write(root / "examples" / "feature-blueprint-demo" / "express-checkout" / "blueprint.yaml", {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "express-checkout", "name": "Демо"},
        "links": {}, "artifacts": {},
    })
    return root


# ── Метрика 1: доля фич идея->релиз, СЧИТАЕТСЯ на реальных данных ──────────────────────────────────


def test_feature_completion_rate_is_measured_on_real_data(child: Path):
    """Обе реальные фичи имеют решение и работу -> дошли idea->release; demo не в знаменателе."""
    graph = kg.build_graph(child)
    m = ps.feature_completion_rate(graph)
    assert m["measured"] is True
    assert m["denominator"] == 2      # f-full + f-partial, express-checkout (demo) исключён
    assert m["numerator"] == 2
    assert m["value"] == 1.0
    # Оговорка про «автономность» названа прямо — доля не должна читаться шире, чем измерено.
    assert "caveat" in m


def test_feature_completion_rate_unmeasured_without_features(tmp_path: Path):
    """Нет паспортов фич -> честное «не измерено» с причиной, а не 0."""
    _write(tmp_path / "planning" / "plan.yaml", {"schema_version": 1, "kind": "delivery-plan"})
    m = ps.feature_completion_rate(kg.build_graph(tmp_path))
    assert m["measured"] is False
    assert m["value"] is None
    assert m["reason"]


# ── Метрика 2: доля утверждений с evidence — ДОЛЕЙ, не pass/fail ──────────────────────────────────


def test_evidence_coverage_is_a_ratio_not_pass_fail():
    """Из результатов проверок реестра честности считается ДОЛЯ ok, а не булев pass/fail."""
    results = [{"status": "ok"}, {"status": "ok"}, {"status": "drift"}, {"status": "error"}]
    m = ps.evidence_coverage(results)
    assert m["measured"] is True
    assert m["numerator"] == 2 and m["denominator"] == 4
    assert m["value"] == 0.5


def test_evidence_coverage_unmeasured_without_registry():
    """Реестр не прочитан (None) -> честное «не измерено», а не доля из воздуха."""
    m = ps.evidence_coverage(None)
    assert m["measured"] is False and m["value"] is None and m["reason"]


def test_evidence_coverage_unmeasured_on_empty_registry():
    """Пустой реестр -> доли нет -> «не измерено» (не 0/0)."""
    m = ps.evidence_coverage([])
    assert m["measured"] is False and m["reason"]


# ── Метрика 3: доля фич с полной историей жизни — агрегат поверх графа ─────────────────────────────


def test_product_memory_coverage_counts_only_full_story_features(child: Path):
    """Полная нить (решение+работа+ревью+исход) есть только у f-full -> 1 из 2."""
    graph = kg.build_graph(child)
    m = ps.product_memory_coverage(graph)
    assert m["measured"] is True
    assert m["numerator"] == 1 and m["denominator"] == 2
    assert m["value"] == 0.5


def test_product_memory_coverage_unmeasured_without_features(tmp_path: Path):
    """Нет фич -> «не измерено» с причиной, а не 0."""
    _write(tmp_path / "planning" / "plan.yaml", {"schema_version": 1, "kind": "delivery-plan"})
    m = ps.product_memory_coverage(kg.build_graph(tmp_path))
    assert m["measured"] is False and m["reason"]


# ── Метрики 4 и 5: КАРКАС — честно «не измерено» ──────────────────────────────────────────────────


def test_outcome_coverage_is_an_honest_unmeasured_scaffold():
    """Результат после релиза упирается в живую аналитику -> честное «не измерено», не число."""
    m = ps.outcome_coverage()
    assert m["measured"] is False
    assert m["value"] is None
    assert "аналитик" in m["reason"].lower()


def test_learning_to_decision_rate_is_an_honest_unmeasured_scaffold():
    """Замкнутой петли обучения нет -> честное «не измерено», не выдуманная доля."""
    m = ps.learning_to_decision_rate()
    assert m["measured"] is False and m["value"] is None and m["reason"]


# ── Карта как целое ──────────────────────────────────────────────────────────────────────────────


def test_scorecard_assembles_five_metrics_three_measured_two_scaffold(child: Path):
    """Карта собирается из 5 метрик: 3 считаемые дают значение, 2 каркасные — «не измерено»."""
    results = [{"status": "ok"}, {"status": "drift"}]
    card = ps.build_scorecard(child, claim_results=results)
    assert card["kind"] == "kit-product-scorecard"
    ids = [m["id"] for m in card["metrics"]]
    assert ids == ["feature_completion_rate", "evidence_coverage", "product_memory_coverage",
                   "outcome_coverage", "learning_to_decision_rate"]
    assert card["measured_count"] == 3
    assert card["unmeasured_count"] == 2
    # Каждая считаемая несёт число; каждая каркасная — причину, а не значение.
    by_id = {m["id"]: m for m in card["metrics"]}
    for mid in ("feature_completion_rate", "evidence_coverage", "product_memory_coverage"):
        assert by_id[mid]["value"] is not None
    for mid in ("outcome_coverage", "learning_to_decision_rate"):
        assert by_id[mid]["value"] is None and by_id[mid]["reason"]


def test_scorecard_metric_2_is_unmeasured_when_registry_missing(child: Path):
    """Без переданного реестра метрика 2 честно «не измерено» -> измеренных 2, каркас 3."""
    card = ps.build_scorecard(child, claim_results=None)
    by_id = {m["id"]: m for m in card["metrics"]}
    assert by_id["evidence_coverage"]["measured"] is False
    assert card["measured_count"] == 2


def test_scorecard_renders_measured_and_unmeasured_to_the_human(child: Path):
    """Человеку карта показывает и долю в процентах, и честное «не измерено» — не лог, не число-заглушку."""
    card = ps.build_scorecard(child, claim_results=[{"status": "ok"}])
    text = presenter.render(presenter.from_scorecard(card), audience="product")
    assert "не измерено" in text                # каркасные метрики честно названы неизмеренными
    assert "%" in text                          # измеренные метрики печатаются долей
    # Карта мерит себя как продукт, а не числом возможностей — это и есть заголовочный смысл.
    assert "как продукт" in text
