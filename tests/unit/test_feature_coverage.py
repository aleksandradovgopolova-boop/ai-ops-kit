# -*- coding: utf-8 -*-
"""Поведенческие тесты судьи охвата фич и его гейта (W3 feature-registry-coverage).

Логика живёт в ПОСТАВЛЯЕМЫХ модулях `ai_ops_kit.checks.feature_coverage` (судья) и
`ai_ops_kit.validation.validate_feature_coverage` (процессный гейт); здесь мы ИМПОРТИРУЕМ их и
ВЫЗЫВАЕМ на образцах — тесты поведенческие, а не структурные (AGENTS.md, ратчет таксономии).

Доказываем контракт силы по УВЕРЕННОСТИ и bootstrap-ратчет:
  * verified-orphan  → fail (блокирует);
  * inferred-orphan  → warn (НЕ блокирует);
  * ghost (не planned)→ warn (planned из ghost исключён);
  * всё покрыто       → pass;
  * bootstrap-ратчет  → verified-сирота в пределах baseline не блокирует; сверх baseline — блокирует.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.checks import feature_coverage as fc
from ai_ops_kit.validation import validate_feature_coverage as vfc

pytestmark = pytest.mark.unit


def _surface(ref, confidence, kind="route", extractor="none"):
    return {"kind": kind, "ref": ref, "confidence": confidence, "extractor": extractor}


def _feature(fid, surfaces, status="active"):
    return {
        "id": fid,
        "name": fid,
        "description": {"what": "w", "who": "u", "verify": "v"},
        "surfaces": surfaces,
        "status": status,
        "owner": "team",
    }


# ─── covered → pass ──────────────────────────────────────────────────────────────────────────────

def test_all_surfaces_covered_is_pass():
    registry = {"features": [_feature("login", [_surface("src/a.py:10|login", "verified")])]}
    surfaces = [_surface("src/a.py:10|login", "verified")]
    report = fc.build_coverage_report(registry, surfaces)
    assert report["ghosts"] == [] and report["orphans"] == []
    assert len(report["covered"]) == 1
    assert report["coverage_pct_verified"] == 100.0
    assert fc.coverage_verdict(report)["status"] == "pass"


def test_covered_survives_line_drift_when_symbol_matches():
    """Номер строки дрейфует, символ — нет: сопоставление держится на "file|symbol"."""
    registry = {"features": [_feature("login", [_surface("src/a.py:10|login", "verified")])]}
    surfaces = [_surface("src/a.py:42|login", "verified")]      # та же фича, строка сдвинулась
    report = fc.build_coverage_report(registry, surfaces)
    assert report["orphans"] == [] and report["ghosts"] == []


# ─── verified-orphan → fail (блокирует) ─────────────────────────────────────────────────────────

def test_verified_orphan_blocks():
    registry = {"features": []}
    surfaces = [_surface("src/new.py:5|handler", "verified")]
    report = fc.build_coverage_report(registry, surfaces)
    assert len(report["orphans"]) == 1 and report["orphans"][0]["confidence"] == "verified"
    verdict = fc.coverage_verdict(report)               # baseline=0
    assert verdict["status"] == "fail"
    assert verdict["evidence"] == [{"file": "src/new.py", "lines": 5}]
    # процессный вход отдаёт это как БЛОКИРУЮЩУЮ проблему и код возврата 1
    assert vfc.blocking_problems(registry, surfaces) != []


# ─── inferred-orphan → warn (не блокирует) ──────────────────────────────────────────────────────

def test_inferred_orphan_only_warns():
    registry = {"features": []}
    surfaces = [_surface("src/guess.py:7|maybe", "inferred")]
    report = fc.build_coverage_report(registry, surfaces)
    assert fc.coverage_verdict(report)["status"] == "warn"
    assert vfc.blocking_problems(registry, surfaces) == []       # НЕ блокирует
    assert vfc.advisory_warnings(registry, surfaces) != []       # но предупреждает


# ─── ghost → warn, planned исключён ─────────────────────────────────────────────────────────────

def test_active_feature_without_trace_is_ghost_warn():
    registry = {"features": [_feature("gone", [_surface("src/x.py:1|gone", "verified")])]}
    surfaces: list = []                                          # кода фичи в извлечённом нет
    report = fc.build_coverage_report(registry, surfaces)
    assert report["ghosts"] == ["gone"]
    assert fc.coverage_verdict(report)["status"] == "warn"
    assert vfc.blocking_problems(registry, surfaces) == []


def test_planned_feature_is_not_a_ghost():
    registry = {"features": [_feature("future", [], status="planned")]}
    report = fc.build_coverage_report(registry, [])
    assert report["ghosts"] == []
    assert fc.coverage_verdict(report)["status"] == "pass"


# ─── bootstrap-ратчет ────────────────────────────────────────────────────────────────────────────

def test_bootstrap_baseline_absorbs_existing_verified_orphans():
    """На первом прогоне все verified-сироты приняты за baseline и НЕ блокируют."""
    registry = {"features": []}
    surfaces = [_surface("src/a.py:1|a", "verified"), _surface("src/b.py:2|b", "verified")]
    report = fc.build_coverage_report(registry, surfaces)
    baseline = fc.bootstrap_baseline(report)
    assert baseline == 2
    assert fc.coverage_verdict(report, baseline)["status"] == "warn"      # приняты, не fail
    assert vfc.blocking_problems(registry, surfaces, baseline) == []


def test_new_verified_orphan_beyond_baseline_blocks():
    """Сверх baseline появившаяся verified-сирота — уже блок (ратчет ловит рост)."""
    registry = {"features": []}
    surfaces = [_surface("src/a.py:1|a", "verified"), _surface("src/b.py:2|b", "verified")]
    report = fc.build_coverage_report(registry, surfaces)
    assert fc.coverage_verdict(report, baseline_verified_orphans=1)["status"] == "fail"
    assert vfc.blocking_problems(registry, surfaces, 1) != []


# ─── процессный вход: no-op без данных, код возврата по силе ─────────────────────────────────────

def test_validator_is_noop_without_input():
    """В самом ките реестра+поверхностей дочки нет — проверять нечего, возврат 0."""
    assert vfc.main([]) == 0


def test_validator_returns_nonzero_on_verified_orphan(tmp_path):
    inp = tmp_path / "cov.yaml"
    inp.write_text(
        "features: []\n"
        "surfaces:\n"
        "  - {kind: route, ref: 'src/new.py:5|h', confidence: verified, extractor: none}\n",
        encoding="utf-8",
    )
    assert vfc.main([str(inp)]) == 1


def test_validator_zero_on_inferred_orphan(tmp_path):
    inp = tmp_path / "cov.yaml"
    inp.write_text(
        "features: []\n"
        "surfaces:\n"
        "  - {kind: route, ref: 'src/g.py:5|h', confidence: inferred, extractor: none}\n",
        encoding="utf-8",
    )
    assert vfc.main([str(inp)]) == 0
