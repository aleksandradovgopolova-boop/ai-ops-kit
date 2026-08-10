"""Связность контуров: `unknown` != `not_changed` (v3.35 Product Operating Model).

Главный инвариант среза и главный способ его подделать — свернуть «не умею видеть» в «не менялось».
Три теста на capability:
  * positive     — diff по сигнальному пути даёт `changed`; сигналы есть и не тронуты -> `not_changed`;
  * fail-closed  — контура без сигнальных путей -> `unknown`, и порча модели -> исключение;
  * side-effect  — заявленный `changed` без обновления источника истины даёт находку.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import contours as C

MODEL = C.load_model()


def _repo(tmp_path):
    """Репозиторий, где сигнальные пути ЧАСТИ контуров существуют, а части — нет."""
    (tmp_path / "context" / "system").mkdir(parents=True)
    (tmp_path / "context" / "system" / "DataMap.md").write_text("# данные\n", encoding="utf-8")
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_signal_path_in_diff_is_changed(tmp_path):
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["context/system/DataMap.md"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED
    assert der["data_contracts"]["matched"] == ["context/system/DataMap.md"]


def test_signals_present_but_untouched_is_not_changed(tmp_path):
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["README.md"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.NOT_CHANGED


def test_deep_glob_matches_nested_path(tmp_path):
    """`**/models/**` обязан ловить `src/api/models/user.py` — иначе модель данных «не менялась»."""
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["src/api/models/user.py"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED


def test_repo_override_teaches_kit_its_paths(tmp_path):
    """Доопределение в `.ai-ops.yaml` превращает `unknown` в проверяемое состояние."""
    r = _repo(tmp_path)
    before = C.derive_affects(r, ["src/telemetry/events.py"], MODEL, overrides={})
    assert before["analytics_learning"]["state"] == C.UNKNOWN
    after = C.derive_affects(r, ["src/telemetry/events.py"], MODEL,
                             overrides={"analytics_learning": ["src/telemetry/**"]})
    assert after["analytics_learning"]["state"] == C.CHANGED


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_no_signal_paths_is_unknown_not_not_changed(tmp_path):
    """ГЛАВНЫЙ инвариант: «не умею видеть» никогда не выглядит как «не менялось»."""
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["src/api/app.py"], MODEL, overrides={})
    an = der["analytics_learning"]
    assert an["state"] == C.UNKNOWN
    assert an["state"] != C.NOT_CHANGED
    assert "не найден" in an["reason"] or "нет сигнальных" in an["reason"]


def test_corrupt_model_raises(tmp_path):
    bad = tmp_path / "pom.yaml"
    bad.write_text("contours: []\n", encoding="utf-8")
    with pytest.raises(C.ModelCorrupt):
        C.load_model(bad)


def test_missing_model_raises(tmp_path):
    with pytest.raises(C.ModelCorrupt):
        C.load_model(tmp_path / "нет-такого.yaml")


def test_broken_repo_config_does_not_crash_overrides(tmp_path):
    """Битый `.ai-ops.yaml` — забота doctor'а: детект не обязан падать, но и врать не должен."""
    (tmp_path / ".ai-ops.yaml").write_text("communication: [\n bad", encoding="utf-8")
    assert C.repo_overrides(tmp_path) == {}


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_declared_changed_without_sot_update_is_finding(tmp_path):
    """Ровно тот случай, ради которого модель существует: обновлён компонент, модель данных нет."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, ["src/ui/Dashboard.tsx"], MODEL, overrides={})
    ids = [f["id"] for f in rep["findings"]]
    assert "declared_not_updated" in ids
    assert rep["verdict"] == "inconsistent"


def test_undeclared_change_is_finding(tmp_path):
    r = _repo(tmp_path)
    rep = C.reconcile(r, {}, ["context/system/DataMap.md"], MODEL, overrides={})
    ids = [f["id"] for f in rep["findings"]]
    assert "undeclared_change" in ids


def test_sot_update_closes_declared_change(tmp_path):
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, ["context/system/DataMap.md"], MODEL,
                      overrides={})
    assert not [f for f in rep["findings"]
                if f["id"] == "declared_not_updated" and f["contour"] == "data_contracts"]


def test_no_diff_is_not_comparable_rather_than_ok(tmp_path):
    """Пустой diff не является доказательством согласованности — об этом сказано прямо."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, [], MODEL, overrides={})
    assert rep["comparable"] is False


def test_unknown_findings_are_info_not_major(tmp_path):
    """`unknown` — признание, а не провал: оно не обязано ронять вердикт."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {}, ["src/api/app.py"], MODEL, overrides={})
    unknown = [f for f in rep["findings"] if f["id"] == "unknown_contour"]
    assert unknown
    assert all(f["severity"] == "info" for f in unknown)


def test_sot_state_reports_required_gaps(tmp_path):
    r = _repo(tmp_path)
    st = C.sot_state(r, MODEL)
    assert st["data_contracts"]["ok"] is True          # DataMap.md на месте
    assert st["product_strategy"]["ok"] is False       # ProductOverview/Status/ROADMAP нет
    assert "ROADMAP.md" in st["product_strategy"]["required_missing"]
