"""CLI-проброс `--reevaluate-only` и удержание уровня из сохранённых сигналов.

Вынесено из test_ai_ops_cli.py (мега-тест-файл сверх 850 строк — режется по темам): тема
«переоценка после записи вердикта оркестратора» стоит отдельным файлом. #570-follow-up (07.09).
"""
from __future__ import annotations

from pathlib import Path  # noqa: F401 — симметрия с test_ai_ops_cli; путь может понадобиться темам

import pytest

from ai_ops_kit.cli import ai_ops_cli


@pytest.mark.unit
class TestReevaluateOnlyFlag:
    """#570-follow-up (07.09): `--reevaluate-only` поднят в CLI-обёртку (`./ai-ops run`), а не только
    у движка — иначе штатная переоценка после записи вердикта падала «unrecognized arguments». И
    уровень на переоценке берётся из СОХРАНЁННЫХ на specify сигналов: ENGINEERING не превращается
    молча в QUICK, когда --signals на этом вызове не задан (полевой замер cockpit)."""

    def test_run_subparser_accepts_reevaluate_only(self):
        """Флаг принимается парсером run — не «unrecognized arguments»."""
        ap = ai_ops_cli._build_cli_arg_parser()
        a = ap.parse_args(["run", ".", "task", "--feature", "wid-x", "--execute",
                           "--reevaluate-only", "--provider", "claude-cli"])
        assert a.reevaluate_only is True
        assert a.execute is True and a.feature == "wid-x"

    def test_reevaluate_holds_engineering_from_saved_signals(self, tmp_path):
        """Без task_type в --signals на переоценке уровень берётся из spec.yaml: ENGINEERING, не QUICK."""
        wid = "eng-work"
        sp = tmp_path / "features" / wid / "spec.yaml"
        sp.parent.mkdir(parents=True)
        sp.write_text(
            "kind: spec\nsignals:\n  task_type: ENGINEERING\n  size: small\n  risk: low\n",
            encoding="utf-8")
        ap = ai_ops_cli._build_cli_arg_parser()
        a = ap.parse_args(["run", str(tmp_path), "task", "--feature", wid, "--execute",
                           "--reevaluate-only"])
        signals = ai_ops_cli._build_signals("run", "task", str(tmp_path), a)
        assert signals.get("task_type") == "ENGINEERING", signals
