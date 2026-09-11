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


# ─── W4: персистентный baseline (ратчет ВНИЗ) — чистая логика reconcile_baseline ────────────────

def test_reconcile_seeds_on_first_run():
    """Первый прогон (baseline ещё нет): значение СИДИРУЕТСЯ, ничего не блокируем."""
    rec = fc.reconcile_baseline(3, None)
    assert rec["seeded"] and not rec["blocked"] and rec["baseline"] == 3 and rec["changed"]


def test_reconcile_growth_blocks_and_does_not_raise_baseline():
    """Verified-сирот стало больше принятого потолка — РОСТ блокирует, baseline вверх не идёт."""
    rec = fc.reconcile_baseline(4, 2)
    assert rec["blocked"] and rec["baseline"] == 2 and rec["regressed"] == 2 and not rec["changed"]


def test_reconcile_ratchets_down_when_orphans_fall():
    """Снижение опускает baseline (ратчет вниз); равенство ничего не меняет."""
    down = fc.reconcile_baseline(1, 3)
    assert not down["blocked"] and down["baseline"] == 1 and down["changed"]
    same = fc.reconcile_baseline(3, 3)
    assert not same["blocked"] and same["baseline"] == 3 and not same["changed"]


# ─── W4: режим ДОЧКИ через доставленный контур — вход собирается из КОДА, baseline персистентен ──

def _flask_child(tmp_path):
    """Дочка с одной verified-поверхностью (Flask-маршрут) и без реестра фич."""
    (tmp_path / "app.py").write_text(
        'from flask import Flask\napp = Flask(__name__)\n\n'
        '@app.route("/login")\ndef login():\n    return "ok"\n', encoding="utf-8")
    return tmp_path / ".ai" / "feature-coverage-baseline.yaml"


def test_child_mode_verified_orphan_blocks_beyond_baseline(tmp_path):
    """verified-поверхность в коде БЕЗ фичи и СВЕРХ принятого baseline → доставленный шаг валит (1)."""
    baseline = _flask_child(tmp_path)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("verified_orphans: 0\n", encoding="utf-8")     # деды = 0, а сирота есть
    rc = vfc.main(["--child-root", str(tmp_path), "--baseline", str(baseline), "--seed"])
    assert rc == 1, "новая verified-сирота сверх baseline обязана ронять гейт"
    # baseline при блокировке НЕ поднят молча — остался 0
    import yaml as _y
    assert _y.safe_load(baseline.read_text(encoding="utf-8"))["verified_orphans"] == 0


def test_child_mode_first_run_seeds_and_does_not_block(tmp_path):
    """Первый прогон без baseline: сироты приняты за дедов, файл засеян, возврат 0."""
    baseline = _flask_child(tmp_path)
    assert not baseline.exists()
    rc = vfc.main(["--child-root", str(tmp_path), "--baseline", str(baseline), "--seed"])
    assert rc == 0, "первая установка не должна тонуть в блокировках"
    import yaml as _y
    assert baseline.is_file() and _y.safe_load(baseline.read_text(encoding="utf-8"))["verified_orphans"] == 1


def test_child_mode_ratchets_baseline_down_on_disk(tmp_path):
    """Сирот стало меньше принятого — baseline на диске ОПУСКАЕТСЯ (persist + монотонность вниз)."""
    baseline = tmp_path / ".ai" / "feature-coverage-baseline.yaml"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("verified_orphans: 5\n", encoding="utf-8")     # приняли 5, а кода нет вовсе
    rc = vfc.main(["--child-root", str(tmp_path), "--baseline", str(baseline), "--seed"])
    assert rc == 0
    import yaml as _y
    assert _y.safe_load(baseline.read_text(encoding="utf-8"))["verified_orphans"] == 0, "не опустился"


def test_child_mode_documented_surface_is_not_an_orphan(tmp_path):
    """Поверхность, объявленная фичей в реестре дочки, — покрыта, не сирота: гейт зелёный."""
    _flask_child(tmp_path)
    reg = tmp_path / "registry"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "features.yaml").write_text(
        "features:\n"
        "  - id: login\n    name: Вход\n"
        "    description: {what: вход, who: пользователь, verify: тест}\n"
        "    surfaces:\n      - {kind: route, ref: 'app.py:5|login', confidence: verified, extractor: python-web-routes}\n"
        "    status: active\n    owner: team\n", encoding="utf-8")
    baseline = tmp_path / ".ai" / "feature-coverage-baseline.yaml"
    rc = vfc.main(["--child-root", str(tmp_path), "--baseline", str(baseline), "--seed"])
    assert rc == 0
    import yaml as _y
    assert _y.safe_load(baseline.read_text(encoding="utf-8"))["verified_orphans"] == 0
