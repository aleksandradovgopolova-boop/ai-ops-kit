"""Тесты Team Synchronization (PR-12): статус собирается сам, честно помечая непроверенное."""
from __future__ import annotations

import yaml

from ai_ops_kit.intelligence import health_delivery, health_tech, team_sync as ts


def _tech_export(root, data):
    (root / ".ai-ops").mkdir(exist_ok=True)
    (root / health_tech.EXPORT_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


def _delivery_signals(root, data):
    (root / ".ai-ops").mkdir(exist_ok=True)
    (root / health_delivery.SIGNALS_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_empty_repo_status_is_honest_unknowns(tmp_path):
    st = ts.team_status(tmp_path)
    assert st["health"]["product"]["band"] == "unknown"
    assert st["health"]["tech"]["band"] == "unknown"
    assert st["health"]["delivery"]["band"] == "unknown"
    assert st["risks"]["count_by_severity"] == {"high": 0, "medium": 0}
    assert st["blockers"]["status"] == "unknown"      # плана нет
    assert st["next_tasks"]["status"] == "unknown"
    assert st["milestone"]["status"] == "unknown"
    assert st["blind_spots"]                          # непроверенное названо, а не спрятано


def test_tech_export_flows_into_health(tmp_path):
    _tech_export(tmp_path, {
        "ci": {"status": "passing"},
        "tests": {"passed": 100, "total": 100},
        "lint": {"errors": 0},
        "security": {"critical": 0, "high": 0},
        "dependencies": {"outdated": 0},
    })
    st = ts.team_status(tmp_path)
    assert st["health"]["tech"]["band"] == "green"
    assert st["health"]["tech"]["complete"] is True


def test_red_tech_produces_risk_in_status(tmp_path):
    _tech_export(tmp_path, {"ci": {"status": "failing"}})
    st = ts.team_status(tmp_path)
    assert st["risks"]["count_by_severity"]["high"] >= 1
    assert st["risks"]["top"]                          # верхний риск показан
    assert st["risks"]["top"][0]["mitigation"].strip()


def test_milestone_from_export(tmp_path):
    _delivery_signals(tmp_path, {"milestone": {"done": 3, "total": 10}, "forecast": "2026-Q4"})
    ms = ts._milestone(tmp_path)
    assert ms["status"] == "ok"
    assert ms["done"] == 3 and ms["total"] == 10
    assert ms["forecast"] == "2026-Q4"


def test_milestone_unknown_without_export(tmp_path):
    assert ts._milestone(tmp_path)["status"] == "unknown"


def test_render_text_has_key_lines(tmp_path):
    _tech_export(tmp_path, {"ci": {"status": "failing"}})
    txt = ts._render(ts.team_status(tmp_path))
    assert "СТАТУС КОМАНДЫ" in txt
    assert "Здоровье:" in txt
    assert "Риски:" in txt
