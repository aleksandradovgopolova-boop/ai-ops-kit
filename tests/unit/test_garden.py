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
    for group in r["duplicate_functions"]:
        assert group["members"] and group["sources"]
        assert len(group["sources"]) == len(group["members"])


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


def _plant_inventory(tmp_path, monkeypatch):
    from ai_ops_kit.devtools import capability_inventory as inventory

    module = "ai_ops_kit.engine.garden_orphan"
    source = tmp_path / "ai_ops_kit/engine/garden_orphan.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"import {module}\n", encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(f"import {module}\n", encoding="utf-8")
    copy = tmp_path / ".ai/worktrees/copy/probe.py"
    copy.parent.mkdir(parents=True)
    copy.write_text(f"import {module}\n", encoding="utf-8")
    monkeypatch.setattr(inventory, "PKG", tmp_path)
    monkeypatch.setattr(inventory, "INTENTIONAL_DORMANT_REASON", {module: "PARK: ждать проверки"})
    from ai_ops_kit.devtools import arch_gate_reconciliation as recon
    from ai_ops_kit.devtools import code_duplication as dup
    monkeypatch.setattr(recon, "dishonest_rows", lambda: [])
    monkeypatch.setattr(dup, "stale_baseline_keys", lambda: [])
    monkeypatch.setattr(dup, "duplicate_groups", lambda: [])
    # Здесь изолируется dormant-сигнал; реальные структурные входы проверяет test_garden_inventory.
    monkeypatch.setattr(garden, "inventory_signals", lambda root: {})
    return module, source


def test_collect_names_real_dormant_source_and_preserves_quarantine(tmp_path, monkeypatch):
    module, source = _plant_inventory(tmp_path, monkeypatch)
    assert source.is_file() and f"import {module}" in source.read_text()
    report = garden.collect()
    assert report["dormant_modules"] == [{
        "module": module, "path": "ai_ops_kit/engine/garden_orphan.py",
        "reason": "PARK: ждать проверки",
    }]
    rendered = garden.render(report)
    assert "ai_ops_kit/engine/garden_orphan.py" in rendered
    assert "PARK: ждать проверки" in rendered
    assert "сад чист" not in rendered


def test_real_working_import_removes_candidate_without_changing_sources(tmp_path, monkeypatch):
    module, _ = _plant_inventory(tmp_path, monkeypatch)
    assert garden.collect()["dormant_modules"]
    importer = tmp_path / "worker.py"
    importer.write_text(f"import {module}\n", encoding="utf-8")
    assert importer.read_text() == f"import {module}\n"
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    report = garden.collect()
    assert report["dormant_modules"] == []
    assert "сад чист" in garden.render(report)
    after = {str(p.relative_to(tmp_path)): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_inventory_failure_does_not_print_clean_report(monkeypatch, capsys):
    from ai_ops_kit.devtools import capability_inventory as inventory

    def fail():
        raise OSError("inventory unavailable")

    monkeypatch.setattr(inventory, "dormant_modules", fail)
    with pytest.raises(OSError, match="inventory unavailable"):
        garden.main(["--json"])
    assert capsys.readouterr().out == ""


def test_successful_json_names_dormant_source(tmp_path, monkeypatch, capsys):
    module, _ = _plant_inventory(tmp_path, monkeypatch)
    assert garden.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dormant_modules"][0]["module"] == module
