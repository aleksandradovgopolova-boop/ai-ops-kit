"""После specify следующий шаг — plan, а трек отключается заявкой, а не фактом о ненаписанном коде.

ПОВОД — ПОЛЕ 20.08.2026 (прогон ⌘K в ai-ops-cockpit).
- obs e09fe515: подсказка «Дальше» после specify вела сразу на `run --execute`, минуя `plan`.
  Заявленный путь кита — specify -> plan -> run; человек, идущий по подсказкам, планирования не
  видел вообще.
- obs 64a4840a: треки отключались причинами в ПРОШЕДШЕМ времени о коде, которого ещё не было
  («UI не менялся»). План строится ДО первой правки — это ложь о ненаписанном; честно говорить о
  том, что заявлено в сигналах.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG))

from ai_ops_kit.engine import run_plan  # noqa: E402


@pytest.mark.unit
def test_skip_reason_is_about_the_signal_not_past_tense_code():
    """Отключённый трек объясняется заявкой, а не фактом о коде, которого ещё нет."""
    plan = run_plan.build_plan({"task_text": "мелкая правка без UI", "task_type": "engineering"})
    skipped = {s["track"]: s["reason"] for s in plan["skipped_tracks"]}
    assert skipped, "ни один трек не отключён — проверять нечего, тест смотрит не туда"
    for track, reason in skipped.items():
        low = reason.lower()
        assert "не менял" not in low and "нет нового" not in low, (
            f"трек {track} отключён прошедшим временем о ненаписанном коде: «{reason}»")
        assert "не заявлен" in low or "не активирован" in low, (
            f"трек {track}: причина не про заявку/сигнал: «{reason}»")


@pytest.mark.unit
def test_the_specify_next_step_is_plan_not_run():
    """Подсказка после specify ведёт на `plan`, а не сразу на `run --execute` (specify->plan->run)."""
    src = (PKG / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")
    # блок вызова from_specification
    i = src.index("from_specification")
    block = src[i:i + 600]
    assert "ai-ops plan" in block, "следующий шаг после specify не ведёт на plan"
    assert 'ai-ops run "' not in block.split("next_command", 1)[0][:400] or "ai-ops plan" in block
    # прямой якорь: команда, которую передают как next_command
    assert 'plan \\"' in src[i:i + 700] or "ai-ops plan" in src[i:i + 700], src[i:i+700][-200:]
