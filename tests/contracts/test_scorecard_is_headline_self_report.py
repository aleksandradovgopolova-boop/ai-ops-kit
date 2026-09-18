"""Самоотчёт кита о СЕБЕ ведёт картой из 5 метрик, а не числом возможностей.

ПОВОД (ревью 17.09, `qualification/KIT-AS-PRODUCT-METRICS-MEASUREMENT-2026-09-17.md`): кит уходит от
меры «число возможностей» (34 команды, 36 гейтов, 89 валидаторов) как ГЛАВНОГО показателя развития
и мерит себя как ПРОДУКТ пятью метриками (`intelligence/product_scorecard`). Счёт возможностей не
удаляется — он остаётся видимым как «ширина», но перестаёт быть заглавной мерой.

Эти тесты держат сдвиг честным:
  * самоотчёт (`self_report`) ВЕДЁТ картой (`headline.scorecard`), счёт — вспомогательно (`breadth`);
  * счёт возможностей ПРИСУТСТВУЕТ (не удалён), но не в заглавной части;
  * «не измерено» честно пробрасывается в карту (метрики 4/5 — каркас с причиной);
  * состав карты на committed-странице синхронен с реальной картой (не разойдётся молча);
  * страница ведёт разделом главной меры ПЕРЕД разделом ширины.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.devtools import capability_inventory as ci

PKG_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.contract
def test_self_report_leads_with_the_scorecard_not_capability_count():
    """`self_report` — заглавная мера первой: `headline.scorecard` (карта из 5 метрик), потом `breadth`."""
    rep = ci.self_report()
    assert rep["kind"] == "kit-self-report"
    # Порядок ключей смысловой: заглавная мера идёт РАНЬШЕ ширины.
    keys = list(rep.keys())
    assert keys.index("headline") < keys.index("breadth"), (
        "самоотчёт обязан вести заглавной мерой (headline) прежде ширины (breadth)")
    assert rep["headline"]["measure"] == "kit-product-scorecard"
    sc = rep["headline"]["scorecard"]
    assert sc["kind"] == "kit-product-scorecard"
    assert len(sc["metrics"]) == 5, "карта продукта — ровно 5 метрик"


@pytest.mark.contract
def test_capability_count_is_still_present_but_only_as_breadth():
    """Счёт возможностей НЕ удалён — он виден как «ширина», а НЕ как заглавная мера."""
    rep = ci.self_report()
    # Ширина несёт прежний счёт возможностей — он остаётся видимым.
    counts = rep["breadth"]["counts"]
    for key in ("commands", "gates_total", "roles"):
        assert counts.get(key, 0) >= 1, f"счёт «{key}» должен остаться видимым как ширина"
    # …но заглавная часть НЕ ведёт числом возможностей: в headline нет счётчиков.
    assert "counts" not in rep["headline"], "число возможностей не смеет быть заглавной мерой"
    assert rep["headline"]["measure"] != "capability-count"


@pytest.mark.contract
def test_unmeasured_metrics_carry_an_honest_reason():
    """«Не измерено» честно пробрасывается: метрики 4/5 — каркас с причиной, а не выдуманное число."""
    sc = ci.kit_scorecard()
    by_id = {m["id"]: m for m in sc["metrics"]}
    for mid in ("outcome_coverage", "learning_to_decision_rate"):
        m = by_id[mid]
        assert m["measured"] is False, f"{mid} у самого кита пока не измеряется (нет живой аналитики)"
        assert m["value"] is None
        assert (m.get("reason") or "").strip(), f"{mid}: «не измерено» без причины — немой отказ"


@pytest.mark.contract
def test_evidence_coverage_is_injected_from_the_registry_at_this_layer():
    """Метрика 2 измерена, потому что реестр честности прочитан ЗДЕСЬ и инъектирован в карту.

    Это доказывает соблюдение слоёв: `intelligence` не импортирует `validation`; реестр читает
    entrypoint (`_kit_claim_results`) и передаёт результат в `build_scorecard`. Реестр
    `knowledge/claims.yaml` в репозитории кита есть — значит метрика 2 не «не прочитан на слое».
    """
    assert (PKG_ROOT / "knowledge" / "claims.yaml").is_file()
    assert ci._kit_claim_results() is not None, "реестр честности кита обязан читаться на этом слое"
    sc = ci.kit_scorecard()
    ev = next(m for m in sc["metrics"] if m["id"] == "evidence_coverage")
    assert ev["measured"] is True, (
        "реестр честности прочитан и инъектирован — метрика 2 обязана быть измерена, а не «не прочитан»")


@pytest.mark.contract
def test_static_metric_mirror_stays_in_sync_with_the_real_scorecard():
    """Зеркало состава карты на странице (`SCORECARD_METRICS`) не расходится с реальной картой.

    Страница ведёт СОСТАВОМ карты без впечатывания живых чисел; если `product_scorecard` сменит набор
    метрик, а зеркало — нет, страница солгала бы о составе. Тест ловит расхождение по id и порядку.
    """
    mirror_ids = [mid for mid, _title, _meaning in ci.SCORECARD_METRICS]
    real_ids = [m["id"] for m in ci.kit_scorecard()["metrics"]]
    assert mirror_ids == real_ids, (
        "SCORECARD_METRICS на странице разошёлся с составом build_scorecard — синхронизируйте зеркало")


@pytest.mark.contract
def test_page_leads_with_the_headline_measure_before_breadth():
    """`docs/capability-map.md` ведёт разделом главной меры ПЕРЕД разделом ширины."""
    text = (PKG_ROOT / ci.PAGE_REL).read_text(encoding="utf-8")
    headline_h = "## Главная мера — карта продукта кита (5 метрик)"
    breadth_h = "## Ширина возможностей (контекст, не главная мера)"
    assert headline_h in text and breadth_h in text
    assert text.index(headline_h) < text.index(breadth_h), (
        "страница обязана вести главной мерой (карта) прежде ширины (счёт возможностей)")
    # Все пять метрик названы в заглавном разделе.
    for _mid, title, _meaning in ci.SCORECARD_METRICS:
        assert title in text, f"метрика «{title}» не названа на странице главной меры"
