"""Тесты Risk Management (PR-16): риски выводятся из health/drift, каждый с mitigation;
unknown — слепая зона, а не риск; зелёное — не риск."""
from __future__ import annotations

from ai_ops_kit.intelligence import drift_artifacts as da
from ai_ops_kit.intelligence import health_common as hc
from ai_ops_kit.intelligence import risk_register as rr


def _health(scope, signals):
    return hc.build_report(f"{scope}-health-report", signals, scope=scope)


def _drift(pairs):
    unver = [p.pair for p in pairs if p.status == da.UNKNOWN]
    return {"kind": da.KIND, "pairs": [p.as_dict() for p in pairs], "unverified": unver}


def _reports(product=None, tech=None, delivery=None, drift=None):
    return {
        "product": product or _health("product", [hc.Signal("m", hc.GREEN, "ок")]),
        "tech": tech or _health("tech", [hc.Signal("ci", hc.GREEN, "ок")]),
        "delivery": delivery or _health("delivery", [hc.Signal("blocked_work", hc.GREEN, "ок")]),
        "drift": drift or _drift([]),
    }


def test_all_green_no_drift_yields_no_risks(tmp_path):
    rep = rr.risk_register(tmp_path, reports=_reports())
    assert rep["risks"] == []
    assert rep["count_by_severity"] == {"high": 0, "medium": 0}


def test_red_tech_signal_is_high_technical_risk_with_mitigation(tmp_path):
    tech = _health("tech", [hc.Signal("ci", hc.RED, "последний прогон CI красный")])
    rep = rr.risk_register(tmp_path, reports=_reports(tech=tech))
    assert len(rep["risks"]) == 1
    risk = rep["risks"][0]
    assert risk["category"] == "technical"
    assert risk["severity"] == "high"
    assert risk["source"] == "health:tech:ci"
    assert risk["mitigation"].strip()          # действие предложено


def test_yellow_signal_is_medium_risk(tmp_path):
    delivery = _health("delivery", [hc.Signal("blocked_work", hc.YELLOW, "2 из 5 работ ждут")])
    rep = rr.risk_register(tmp_path, reports=_reports(delivery=delivery))
    assert rep["risks"][0]["severity"] == "medium"
    assert rep["risks"][0]["category"] == "delivery"


def test_deps_signal_maps_to_dependency_category(tmp_path):
    tech = _health("tech", [hc.Signal("dependencies", hc.YELLOW, "4 устаревших")])
    rep = rr.risk_register(tmp_path, reports=_reports(tech=tech))
    assert rep["risks"][0]["category"] == "dependency"


def test_drift_becomes_high_risk(tmp_path):
    drift = _drift([da.DriftResult("документация↔код", da.DRIFT, "3 висячих ссылки",
                                   findings=["a", "b", "c"])])
    rep = rr.risk_register(tmp_path, reports=_reports(drift=drift))
    assert len(rep["risks"]) == 1
    assert rep["risks"][0]["severity"] == "high"
    assert rep["risks"][0]["source"] == "drift:документация↔код"


def test_unknown_is_blind_spot_not_risk(tmp_path):
    tech = _health("tech", [hc.Signal("ci", hc.UNKNOWN, "нет выгрузки CI")])
    rep = rr.risk_register(tmp_path, reports=_reports(tech=tech))
    assert rep["risks"] == []                       # «не проверено» ≠ риск
    assert "health:tech:ci" in rep["blind_spots"]   # но слепая зона названа


def test_drift_unknown_pair_is_blind_spot(tmp_path):
    drift = _drift([da.DriftResult("Passport↔факт", da.UNKNOWN, "паспорта нет")])
    rep = rr.risk_register(tmp_path, reports=_reports(drift=drift))
    assert rep["risks"] == []
    assert "drift:Passport↔факт" in rep["blind_spots"]


def test_counts_aggregate(tmp_path):
    tech = _health("tech", [
        hc.Signal("ci", hc.RED, "красный"),
        hc.Signal("dependencies", hc.YELLOW, "устарели"),
    ])
    rep = rr.risk_register(tmp_path, reports=_reports(tech=tech))
    assert rep["count_by_severity"] == {"high": 1, "medium": 1}
    assert rep["count_by_category"] == {"technical": 1, "dependency": 1}


def test_every_risk_has_named_source_and_mitigation(tmp_path):
    tech = _health("tech", [hc.Signal("security", hc.RED, "1 критическая")])
    product = _health("product", [hc.Signal("product_metrics", hc.YELLOW, "score 60")])
    rep = rr.risk_register(tmp_path, reports=_reports(tech=tech, product=product))
    assert rep["risks"]
    for risk in rep["risks"]:
        assert risk["source"] and risk["mitigation"].strip() and risk["description"]


def test_integration_from_root_fixture(tmp_path):
    # реальный проход build_reports: пустой репо -> health/drift unknown -> рисков нет, слепые зоны есть
    rep = rr.risk_register(tmp_path)
    assert rep["risks"] == []
    assert rep["blind_spots"]        # всё непроверено -> слепые зоны, не благополучие
