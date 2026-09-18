"""Человеческая «передняя дверь» CLI (#675 Human API; P1 №8/№9 — фасад из 7 действий).

Человек, не знающий внутренней механики кита, должен понять, что попросить, с ПЕРВОГО экрана:
`ai-ops` без аргументов и `ai-ops help` показывают короткий набор ДЕЙСТВИЙ владельца (7 глаголов
фасада), а не argparse-стену из 34 интентов и 30 флагов. Дверь — витрина, а не ограничение: любой
интент вызывается как раньше (`help --all`). Тест держит инвариант «дверь мала и настоящая».
"""
from __future__ import annotations

import pytest

from ai_ops_kit.cli.ai_ops_cli import HUMAN_ACTIONS, INTENTS, main

pytestmark = pytest.mark.unit


class TestTheDoorIsSmallAndReal:
    def test_the_door_stays_human_sized(self):
        """Дверь МАЛА намеренно: если она разрастается к полному списку — смысл потерян."""
        assert len(HUMAN_ACTIONS) <= 8, (
            f"фасад разросся до {len(HUMAN_ACTIONS)} действий — человек снова тонет; "
            f"внутреннюю механику показывает `help --all`, а не первый экран")

    def test_every_action_has_a_plain_label(self):
        """У каждого действия — человеческая подпись без внутренних терминов."""
        missing = [v for v, s in HUMAN_ACTIONS.items() if not (s.get("label") or "").strip()]
        assert not missing, f"у действий фасада нет человеческой подписи: {missing}"

    def test_labels_do_not_leak_internal_jargon(self):
        """Подписи не выводят внутренние термины (gate/write_scope/SHA/workflow/intent…)."""
        jargon = ("write_scope", "tested_revision", "sha", "workflow", "task_type",
                  "gate", "intent", "run_nightly")
        for verb, spec in HUMAN_ACTIONS.items():
            low = spec["label"].lower()
            leaked = [j for j in jargon if j in low]
            assert not leaked, f"подпись {verb!r} протекла жаргоном: {leaked}"


class TestTheDoorIsWhatAHumanSeesFirst:
    def test_empty_call_shows_the_seven_actions_not_the_argparse_wall(self, capsys):
        """`ai-ops` без аргументов -> 7 действий человеческим языком, а не usage-стена."""
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Основные действия" in out
        # все 7 действий видны первым экраном, в порядке набора
        idxs = [out.find(f"ai-ops {v}") for v in HUMAN_ACTIONS]
        assert all(i >= 0 for i in idxs), "не все 7 действий показаны на первом экране"
        assert idxs == sorted(idxs), "порядок действий на экране не совпал с фиксированным набором"
        # продвинутая механика НЕ вываливается первым экраном
        assert "specify" not in out and "governance" not in out and "readout" not in out
        assert "usage:" not in out.lower()

    def test_the_seven_are_the_final_owner_set_in_order(self, capsys):
        """Набор и порядок фиксированы владельцем: research·start·check·work·review·release·feedback."""
        assert list(HUMAN_ACTIONS) == [
            "research", "start", "check", "work", "review", "release", "feedback"]

    def test_help_all_reveals_the_advanced_commands(self, capsys):
        """`help --all` показывает и продвинутую механику — она работает, просто не на первом экране."""
        rc = main(["help", "--all"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Продвинутое" in out
        # хотя бы пара заведомо экспертных интентов присутствует в полном списке
        assert "specify" in out and "governance" in out
