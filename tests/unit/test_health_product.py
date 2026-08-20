"""Тесты Product Health (PR-13) на фикстурах.

Проверяем ровно границу ленты 5: цвет ВСЕГДА с причиной, и «не проверено» ≠ «в порядке»
(отсутствующий сигнал → unknown, а не green).
"""
from __future__ import annotations

import yaml

from ai_ops_kit.intelligence import health_common as hc
from ai_ops_kit.intelligence import health_product as hp


# ── helpers: собрать фикстуру Product Operating Layer ──

def _layer(root):
    d = root / ".ai-ops"
    d.mkdir(exist_ok=True)
    return d


def _write_metrics(root, metrics):
    _layer(root)
    (root / hp.METRICS_REL).write_text(
        yaml.safe_dump({"scope": "product", "metrics": metrics}), encoding="utf-8"
    )


def _write_passport(root, text="# Passport\n\nНазвание: X\n"):
    _layer(root)
    (root / hp.PASSPORT_REL).write_text(text, encoding="utf-8")


def _write_roadmap(root, text="# Roadmap\n\n## Now\n- x\n"):
    _layer(root)
    (root / hp.ROADMAP_REL).write_text(text, encoding="utf-8")


GREEN_METRICS = {"adoption": {"value": 0.5, "target": 0.5}}
WARN_METRICS = {"adoption": {"value": 0.3, "target": 0.5}}  # normalized 0.6 -> score 60
CRIT_METRICS = {
    "adoption": {"value": 0.1, "target": 0.5},
    "errors": {"value": 4.0, "target": 1.0, "direction": "lower-is-better"},
}


# ── третье состояние ≠ второе ──

def test_empty_repo_is_unknown_not_green(tmp_path):
    r = hp.product_health_report(tmp_path)
    assert r["band"] == hc.UNKNOWN
    assert r["complete"] is False
    assert set(r["unverified"]) == {"product_metrics", "product_passport", "product_roadmap"}
    # причина названа для КАЖДОГО непрочитанного сигнала — цвет без причины бесполезен
    assert len(r["reasons"]) == 3
    assert all(reason.strip() for reason in r["reasons"])


def test_partial_signals_report_green_but_flag_incomplete(tmp_path):
    # только roadmap прочитан (green); метрики и паспорт отсутствуют.
    _write_roadmap(tmp_path)
    r = hp.product_health_report(tmp_path)
    assert r["band"] == hc.GREEN                     # зелёный ПО ТОМУ, ЧТО проверено
    assert r["complete"] is False                    # но честно: проверено не всё
    assert set(r["unverified"]) == {"product_metrics", "product_passport"}


# ── все цвета из метрик ──

def test_healthy_metrics_and_artifacts_are_green(tmp_path):
    _write_metrics(tmp_path, GREEN_METRICS)
    _write_passport(tmp_path)
    _write_roadmap(tmp_path)
    r = hp.product_health_report(tmp_path)
    assert r["band"] == hc.GREEN
    assert r["complete"] is True
    assert r["unverified"] == []


def test_warning_metrics_make_yellow(tmp_path):
    _write_metrics(tmp_path, WARN_METRICS)
    _write_passport(tmp_path)
    _write_roadmap(tmp_path)
    r = hp.product_health_report(tmp_path)
    assert r["band"] == hc.YELLOW
    # причина итога названа и указывает на метрики
    assert any("метрик" in reason for reason in r["reasons"])


def test_critical_metrics_make_red_even_with_healthy_artifacts(tmp_path):
    _write_metrics(tmp_path, CRIT_METRICS)
    _write_passport(tmp_path)   # green
    _write_roadmap(tmp_path)    # green
    r = hp.product_health_report(tmp_path)
    assert r["band"] == hc.RED               # худший известный цвет побеждает
    assert any("метрик" in reason for reason in r["reasons"])


def test_empty_passport_is_yellow_signal(tmp_path):
    _write_passport(tmp_path, text="   \n")
    sig = hp._passport_signal(tmp_path)
    assert sig.band == hc.YELLOW
    assert "пуст" in sig.reason


def test_broken_metrics_file_is_unknown_not_green(tmp_path):
    _layer(tmp_path)
    (tmp_path / hp.METRICS_REL).write_text("metrics: {}\n", encoding="utf-8")  # пустые метрики
    sig = hp._metrics_signal(tmp_path)
    assert sig.band == hc.UNKNOWN
    assert sig.reason


# ── health_common: свёртка и инвариант причины ──

def test_rollup_no_known_signals_is_unknown():
    sigs = [hc.Signal("a", hc.UNKNOWN, "нет данных")]
    assert hc.rollup(sigs) == hc.UNKNOWN


def test_rollup_unknown_does_not_become_green():
    sigs = [hc.Signal("a", hc.GREEN, "ок"), hc.Signal("b", hc.UNKNOWN, "нет данных")]
    assert hc.rollup(sigs) == hc.GREEN  # unknown не красит, но и не считается зелёным


def test_rollup_worst_known_wins():
    sigs = [
        hc.Signal("a", hc.GREEN, "ок"),
        hc.Signal("b", hc.RED, "плохо"),
        hc.Signal("c", hc.YELLOW, "так себе"),
    ]
    assert hc.rollup(sigs) == hc.RED


def test_signal_without_reason_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        hc.Signal("a", hc.GREEN, "")


def test_signal_with_bad_band_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        hc.Signal("a", "blue", "причина")
