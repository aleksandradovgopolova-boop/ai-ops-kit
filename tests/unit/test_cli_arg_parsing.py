"""Разбор флагов CLI в любом порядке относительно позиционных (#1398).

pip-вход (`ai_ops_kit.cli.entry`) добавляет рабочий каталог последним позиционным, а пользователь
ставит флаги как привычно. Обычный `parse_args` отвергал позиционный ПОСЛЕ опционального
(«unrecognized arguments»), ломая `plan "задача" --json`. `_parse_cli_args` использует
`parse_intermixed_args` — порядок флагов и позиционных больше не важен.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.cli import ai_ops_cli as c

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("argv", [
    ["plan", "задача", "/root", "--json"],   # флаг в хвосте
    ["plan", "--json", "задача", "/root"],   # флаг перед позиционными
    ["plan", "задача", "--json", "/root"],   # флаг между позиционными (ломало parse_args)
])
def test_flags_parse_in_any_order_around_positionals(argv):
    a = c._parse_cli_args(argv)
    assert a.intent == "plan"
    assert a.json is True
    assert "задача" in a.rest and "/root" in a.rest


def test_plain_call_without_flags_parses():
    a = c._parse_cli_args(["plan", "задача", "/root"])
    assert a.intent == "plan"
    assert a.rest == ["задача", "/root"]


def test_entry_appends_cwd_and_main_guarded_receives_it(monkeypatch):
    """Контракт pip-входа: cwd добавлен последним, флаги пользователя сохранены и дойдут до разбора."""
    import os
    import sys

    from ai_ops_kit.cli import ai_ops_cli, entry

    seen = {}

    def _fake_main_guarded(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(ai_ops_cli, "_main_guarded", _fake_main_guarded)
    monkeypatch.setattr(sys, "argv", ["ai-ops", "plan", "задача", "--json"])
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 0
    assert seen["argv"] == ["plan", "задача", "--json", os.getcwd()]
    # и этот argv разбирается без ошибок (позиционный cwd после флага)
    a = c._parse_cli_args(seen["argv"])
    assert a.json is True and a.rest[-1] == os.getcwd()
