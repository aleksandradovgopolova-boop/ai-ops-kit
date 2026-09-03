# -*- coding: utf-8 -*-
"""Команды `ai-ops roadmap` и `ai-ops delivery` ДОХОДЯТ до работы, а не печатают заглушку.

Лента 4, Фаза 3: подключение модулей roadmap_manager / roadmap_milestones / delivery_planning /
delivery_planning_blockers к CLI. Структурную достижимость стережёт
tests/contracts/test_direct_intents_match_handler.py; здесь — ФАКТ: main() с этими интентами на
живом мини-репозитории производит осмысленный вывод и код возврата, а не общий preview с rc=0
(тот самый класс «команда есть, отвечает успехом, ничего не делает», ради которого guard заведён).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.cli import ai_ops_cli # noqa: E402

pytestmark = pytest.mark.unit


def _repo(tmp_path):
    (tmp_path / "planning").mkdir()
    plan = {
        "kind": "delivery-plan",
        "goals": [{"id": "g-now", "outcome": {"a": False}}],
        "work": [{"id": "w", "goal": "g-now", "status": "in_progress"}],
    }
    (tmp_path / "planning" / "plan.yaml").write_text(
        yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _run(argv, cwd):
    old = os.getcwd()
    try:
        os.chdir(cwd)
        return ai_ops_cli.main(argv)
    finally:
        os.chdir(old)


def test_roadmap_intent_builds_horizons(tmp_path, capsys):
    """roadmap строит Now/Next/Later из плана — вывод содержит горизонт и направление."""
    repo = _repo(tmp_path)
    rc = _run(["roadmap", str(repo)], repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "СЕЙЧАС" in out
    assert "g-now" in out                        # направление действительно выведено из плана


def test_delivery_without_backlog_is_third_state(tmp_path, capsys):
    """delivery без источника backlog честно говорит «не подключён», а не строит пустой план."""
    repo = _repo(tmp_path)
    rc = _run(["delivery", str(repo)], repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "не подключён" in out


def test_delivery_with_backlog_plans_and_finds_blockers(tmp_path, capsys):
    """delivery с backlog даёт прогноз-ОЦЕНКУ и ранжированные блокеры — реальная работа, не заглушка."""
    repo = _repo(tmp_path)
    (repo / ".ai-ops").mkdir()
    backlog = {
        "capacity": 2, "today": "2026-08-20",
        "milestones": [{"id": "m1", "due": "2026-08-30"}],
        "tasks": [
            {"id": "t1", "milestone": "m1", "effort": 4},
            {"id": "t2", "milestone": "m1", "effort": 2, "dependencies": ["t1"]},
        ],
    }
    (repo / ".ai-ops" / "backlog.yaml").write_text(
        yaml.safe_dump(backlog, allow_unicode=True), encoding="utf-8")
    rc = _run(["delivery", str(repo), "--milestone", "m1"], repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "ОЦЕНКА" in out                        # прогноз назван оценкой, не фактом
    assert "блокер 't1'" in out                   # t1 держит t2 — найден блокером
