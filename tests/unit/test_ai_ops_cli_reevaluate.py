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


@pytest.mark.unit
class TestResumeDeliverOnlyForwardsReevaluate:
    """Живой прогон #668 (09.09): `ai-ops resume --deliver-only` падал
    `ai_ops_run.py: error: unrecognized arguments: --reevaluate-only`. Причина — «объявлено, не
    исполняется»: intent-CLI прокидывает `--reevaluate-only` в подкоманду resume (переиспользуя
    режим #403 «доставить готовый READY без переавторинга»), но подкоманда resume у движка этот
    флаг НЕ объявляла и НЕ пробрасывала в run(). Весь deliver-only-путь resume был мёртв, хотя CLI
    его рекламировал. Тест держит оба конца: парсер принимает флаг И флаг доходит до движка."""

    def test_engine_resume_subparser_accepts_reevaluate_only(self):
        """Парсер run/resume движка принимает `resume ... --reevaluate-only` — не «unrecognized»."""
        from ai_ops_kit.engine.ai_ops_run_exec import _build_run_arg_parser
        ap = _build_run_arg_parser()
        a = ap.parse_args(["resume", ".", "wid-x", "--reevaluate-only", "--execute"])
        assert a.reevaluate_only is True
        assert a.cmd == "resume" and a.feature == "wid-x" and a.execute is True

    def test_cli_resume_deliver_only_forwards_flag_the_engine_accepts(self, monkeypatch):
        """Сквозь: `resume --deliver-only` строит argv, где `--reevaluate-only` есть И принимается
        парсером движка (иначе флаг «объявлен, но не исполняется» — как и было в поле)."""
        from ai_ops_kit.engine import ai_ops_run
        from ai_ops_kit.engine.ai_ops_run_exec import _build_run_arg_parser
        captured = {}

        def _capture(argv2):
            captured["argv"] = argv2
            return 0

        monkeypatch.setattr(ai_ops_run, "main", _capture)
        rc = ai_ops_cli.main(["resume", ".", "--feature", "wid-x", "--deliver-only", "--execute"])
        assert rc == 0
        argv = captured.get("argv")
        assert argv is not None, "resume не дошёл до движка — диспетчер перехватил вызов"
        assert "--reevaluate-only" in argv, argv
        # ключевое: тот же argv движок РЕАЛЬНО принимает и поднимает флаг (declared -> executed).
        parsed = _build_run_arg_parser().parse_args(argv)
        assert parsed.cmd == "resume" and parsed.reevaluate_only is True
