"""Садовник кита — единый read-only отчёт уборки (#1405).

Держим: отчёт КОМПОЗИТ существующие сигналы (не новый детектор), это ОТЧЁТ, а не гейт (main всегда
0), и честно говорит «сад чист», когда кандидатов нет.
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.devtools import garden

pytestmark = pytest.mark.unit


def test_collect_composes_existing_signals_on_real_kit():
    """collect() зовёт реальные детекторы и возвращает ожидаемую форму, не падая."""
    r = garden.collect()
    assert r["kind"] == "kit-garden-report"
    assert isinstance(r["stale_duplicate_baseline_keys"], list)
    assert isinstance(r["dishonest_gate_rows"], list)
    assert isinstance(r["duplicate_group_count"], int)


def test_report_not_gate_main_always_returns_zero(capsys):
    """Садовник СОВЕТУЕТ, не блокирует: main возвращает 0 (иначе рост вширь)."""
    assert garden.main([]) == 0
    capsys.readouterr()  # сбросить вывод текстового отчёта
    assert garden.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "kit-garden-report"


def test_render_names_candidates_and_clean_state():
    with_candidates = {
        "stale_duplicate_baseline_keys": ["a::f|b::f"],
        "dishonest_gate_rows": ["ARCH-006"],
        "duplicate_group_count": 3,
    }
    text = garden.render(with_candidates)
    assert "ARCH-006" in text and "устаревш" in text
    assert "сад чист" not in text

    clean = {"stale_duplicate_baseline_keys": [], "dishonest_gate_rows": [], "duplicate_group_count": 0}
    assert "сад чист" in garden.render(clean)
