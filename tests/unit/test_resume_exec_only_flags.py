"""`resume --open-pr/--takeover` без --execute больше не проглатывается молча, а ругается явно.

Обратная связь ИИ-Среды (#406): флаги `resume --open-pr/--takeover` на старых версиях молча
игнорировались. В текущем коде тот же тихий провал остался на пути PREFLIGHT: без --execute resume
лишь проверяет готовность и выходит, НИ РАЗУ не взглянув на эти флаги, — человек уверен, что PR
откроется или заявка перенимается, а не происходит ничего. Тихо проигнорированный флаг = ложь об
исходе. Починка (`engine/ai_ops_run.py`): на preflight с такими флагами — явный ОТКАЗ с причиной.

Триада: positive (обычный preflight без этих флагов идёт как прежде), fail-closed (флаг без
--execute -> отказ, код 2, внятное сообщение с именем флага и --execute), side-effect (отказ
короткозамыкает ДО обращения к resume_preflight — молчаливого «как будто применили» не остаётся).
"""
import json

import pytest

from ai_ops_kit.engine import ai_ops_run, run_handoff


class TestResumeExecOnlyFlags:
    def test_open_pr_without_execute_is_refused(self, capsys):
        """FAIL-CLOSED: `resume --open-pr` без --execute -> отказ (код 2), а не тихий выход."""
        rc = ai_ops_run.main(["resume", "/nonexistent", "wi-x", "--open-pr"])
        out = capsys.readouterr().out
        assert rc == 2
        assert "--open-pr" in out and "--execute" in out

    def test_takeover_without_execute_is_refused(self, capsys):
        """FAIL-CLOSED: то же для `--takeover` — заявку перенять на preflight нельзя, молчать нельзя."""
        rc = ai_ops_run.main(["resume", "/nonexistent", "wi-x", "--takeover"])
        out = capsys.readouterr().out
        assert rc == 2
        assert "--takeover" in out and "--execute" in out

    def test_refusal_is_machine_readable_in_json(self, capsys):
        """FAIL-CLOSED (--json): отказ виден и машинно — status=error, resumed=False."""
        rc = ai_ops_run.main(["resume", "/nonexistent", "wi-x", "--open-pr", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["status"] == "error"
        assert payload["resume"]["resumed"] is False

    def test_plain_preflight_without_exec_flags_still_runs(self, capsys, monkeypatch):
        """POSITIVE: без exec-only флагов guard не срабатывает — обычный preflight идёт как прежде."""
        monkeypatch.setattr(run_handoff, "resume_preflight",
                            lambda *a, **k: {"can_resume": False, "revalidation_needed": False,
                                             "reasons": ["нет снимка прогона"], "next_action": None})
        rc = ai_ops_run.main(["resume", "/nonexistent", "wi-x"])
        out = capsys.readouterr().out
        assert rc == 1                      # can_resume=False -> код 1 (preflight), НЕ отказ-2
        assert "ОТКАЗ" not in out

    def test_refusal_short_circuits_before_preflight(self, monkeypatch):
        """SIDE-EFFECT: отказ короткозамыкает ДО resume_preflight — никакой работы «как будто
        применили флаг» не выполняется."""
        calls = []
        monkeypatch.setattr(run_handoff, "resume_preflight",
                            lambda *a, **k: calls.append((a, k)) or {})
        rc = ai_ops_run.main(["resume", "/nonexistent", "wi-x", "--open-pr"])
        assert rc == 2
        assert calls == [], "resume_preflight не должен вызываться при отказе"
