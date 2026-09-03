"""Крепкие тесты существующего поведения list-events. Зелёные на старте, остаются зелёными."""

import subprocess
import sys


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "events_cli", *args],
        capture_output=True,
        text=True,
    )


def test_list_all_prints_every_event():
    r = run("list-events")
    assert r.returncode == 0
    assert "Kickoff" in r.stdout
    assert "Retro" in r.stdout
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 5


def test_list_all_order_preserved():
    r = run("list-events")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    ids = [ln.split("\t")[0] for ln in lines]
    assert ids == ["1", "2", "3", "4", "5"]
