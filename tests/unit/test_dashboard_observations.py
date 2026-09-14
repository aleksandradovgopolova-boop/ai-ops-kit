"""Поведенческий тест: пульт подхватывает снятые наблюдения продуктовых метрик.

Проверяем читателя `metric_observations` и то, что `build()` кладёт наблюдения в
`data.json` под `metrics.observations`. Модуль грузим по пути (не через sys.path):
dashboard/build_data.py — скрипт, не пакет.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
BUILD_DATA = KIT / "dashboard" / "build_data.py"

yaml = pytest.importorskip("yaml")


def _load():
    spec = importlib.util.spec_from_file_location("dashboard_build_data_under_test", BUILD_DATA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_min_repo(root: Path) -> None:
    """Минимум, чтобы build() не падал: VERSION + пустые источники."""
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "context" / "product").mkdir(parents=True, exist_ok=True)


def test_reader_returns_none_when_file_absent(tmp_path: Path):
    mod = _load()
    assert mod.metric_observations(tmp_path) is None


def test_reader_parses_observations(tmp_path: Path):
    mod = _load()
    (tmp_path / "context" / "product").mkdir(parents=True)
    (tmp_path / "context" / "product" / "metric-observations.yaml").write_text(
        "schema_version: 1\n"
        "kind: metric-observations\n"
        "honest_note: n=1, первое наблюдение\n"
        "observations:\n"
        "  - date: \"2026-09-14\"\n"
        "    source: ai-ops-cockpit\n"
        "    metrics:\n"
        "      intent_to_verified_pr_time: {value: 5m37s, samples: 1}\n"
        "      rework_rate: {status: observation_window_open, window_days: 7}\n",
        encoding="utf-8",
    )
    out = mod.metric_observations(tmp_path)
    assert out is not None
    assert out["honest_note"] == "n=1, первое наблюдение"
    first = out["observations"][0]
    assert first["metrics"]["intent_to_verified_pr_time"]["value"] == "5m37s"
    assert first["metrics"]["rework_rate"]["status"] == "observation_window_open"


def test_build_places_observations_in_data(tmp_path: Path):
    mod = _load()
    _write_min_repo(tmp_path)
    (tmp_path / "context" / "product" / "metric-observations.yaml").write_text(
        "observations:\n"
        "  - date: \"2026-09-14\"\n"
        "    metrics:\n"
        "      verified_pr_rate: {value: 1/1, samples: 1}\n",
        encoding="utf-8",
    )
    data = mod.build(tmp_path)
    obs = data["metrics"]["observations"]
    assert obs is not None
    assert obs["observations"][0]["metrics"]["verified_pr_rate"]["value"] == "1/1"


def test_build_observations_none_when_missing(tmp_path: Path):
    mod = _load()
    _write_min_repo(tmp_path)
    data = mod.build(tmp_path)
    assert data["metrics"]["observations"] is None


def test_reader_passes_through_aggregate(tmp_path: Path):
    """Читатель пробрасывает верхнеуровневый блок aggregate вместе с observations."""
    mod = _load()
    (tmp_path / "context" / "product").mkdir(parents=True)
    (tmp_path / "context" / "product" / "metric-observations.yaml").write_text(
        "honest_note: n=4, ранний тренд\n"
        "aggregate:\n"
        "  n: 4\n"
        "  median_intent_to_verified: 5m03s\n"
        "  range: 3m33s–11m23s\n"
        "  verified_pr_rate: 4/4\n"
        "  human_intervention_rate: 0/4\n"
        "observations:\n"
        "  - date: \"2026-09-14\"\n"
        "    metrics:\n"
        "      verified_pr_rate: {value: 1/1, samples: 1}\n",
        encoding="utf-8",
    )
    out = mod.metric_observations(tmp_path)
    assert out is not None
    assert out["aggregate"]["n"] == 4
    assert out["aggregate"]["median_intent_to_verified"] == "5m03s"


def test_real_repo_observations_reach_build():
    """Реальный файл кита действительно доезжает до data.json: агрегат + 4 прогона."""
    mod = _load()
    data = mod.build(KIT)
    obs = data["metrics"]["observations"]
    assert obs is not None, "context/product/metric-observations.yaml должен читаться build()"
    # Агрегат (n=4) попал в data.json.
    agg = obs["aggregate"]
    assert agg is not None, "aggregate должен доезжать до data.json"
    assert agg["n"] == 4
    assert agg["median_intent_to_verified"] == "5m03s"
    assert agg["range"] == "3m33s–11m23s"
    assert agg["verified_pr_rate"] == "4/4"
    assert agg["human_intervention_rate"] == "0/4"
    # Четыре наблюдения, первое — исходное с полигона cockpit.
    assert len(obs["observations"]) == 4
    m = obs["observations"][0]["metrics"]
    assert m["intent_to_verified_pr_time"]["value"] == "5m37s"
    assert m["post_merge_defect_rate"]["status"] == "observation_window_open"
    # Все четыре прогона слиты — guardrail-окна открыты (не pending_merge).
    last = obs["observations"][3]["metrics"]
    assert last["rework_rate"]["status"] == "observation_window_open"
    assert last["rework_rate"]["opened_at"] == "2026-09-14T13:54:00Z"
