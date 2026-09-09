"""Человеческая «передняя дверь» CLI (#675 Human API).

Человек, не знающий внутренней механики кита, должен понять, что попросить, с ПЕРВОГО экрана:
`ai-ops` без аргументов и `ai-ops help` показывают короткий набор команд владельца, а не argparse-
стену из 36 интентов и 30 флагов. Дверь — витрина, а не ограничение: любой интент вызывается как
раньше. Тест держит инвариант «дверь мала и настоящая», чтобы она не разрослась обратно в стену.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.cli.ai_ops_cli import INTENTS, main
from ai_ops_kit.cli.human_help import HUMAN_INTENTS, _HUMAN_LABELS

pytestmark = pytest.mark.unit


class TestTheDoorIsSmallAndReal:
    def test_every_human_command_is_a_real_intent(self):
        """Дверь не может обещать команду, которой нет."""
        unknown = [c for c in HUMAN_INTENTS if c not in INTENTS]
        assert not unknown, f"в двери команды, которых нет в INTENTS: {unknown}"

    def test_every_human_command_has_a_plain_label(self):
        """У каждой команды двери — человеческая подпись без внутренних терминов."""
        missing = [c for c in HUMAN_INTENTS if c not in _HUMAN_LABELS or not _HUMAN_LABELS[c].strip()]
        assert not missing, f"у команд двери нет человеческой подписи: {missing}"

    def test_the_door_stays_human_sized(self):
        """Дверь МАЛА намеренно: если она разрастается к полному списку — смысл потерян."""
        assert len(HUMAN_INTENTS) <= 12, (
            f"дверь разрослась до {len(HUMAN_INTENTS)} команд — человек снова тонет; "
            f"внутреннюю механику показывает `help --all`, а не первый экран")


class TestTheDoorIsWhatAHumanSeesFirst:
    def test_empty_call_shows_the_human_door_not_the_argparse_wall(self, capsys):
        """`ai-ops` без аргументов -> короткий человеческий список, а не usage-стена."""
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Основные команды" in out
        # дверь показывает человеческие команды и НЕ вываливает продвинутые первым экраном
        assert "ai-ops do" in out and "ai-ops inbox" in out
        assert "specify" not in out and "governance" not in out
        assert "usage:" not in out.lower()

    def test_help_all_reveals_the_advanced_commands(self, capsys):
        """`help --all` показывает и продвинутую механику — она работает, просто не на первом экране."""
        rc = main(["help", "--all"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Продвинутое" in out
        # хотя бы пара заведомо экспертных интентов присутствует в полном списке
        assert "specify" in out and "governance" in out
