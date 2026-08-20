"""Лимит модели доходит до человека фразой, а не трейсбеком — и не путается с транзиентным 529.

ПОВОД — ПОЛЕ 20.08.2026 (obs 99aa67ef, прогон ⌘K в ai-ops-cockpit на 3.36.12). При исчерпании
лимита сессии claude-cli («You've hit your session limit», HTTP 429) кит делал ПЯТЬ повторов с
backoff и затем ронял RuntimeError полным питоновским трейсбеком. Человек не понимал ни что
случилось, ни что делать — а делать надо было подождать до сброса или сменить провайдера.

ДВА КЛАССА, КОТОРЫЕ НЕЛЬЗЯ ПУТАТЬ:
- лимит сессии/квоты — за 30 секунд backoff не вернётся; повторять бессмысленно, надо СКАЗАТЬ;
- транзиентный 529/5xx (F-011, стоил раунда квалификации) — повторять НУЖНО.
Текст лимита сам несёт «429», поэтому распознаётся ПЕРВЫМ, иначе попал бы в _transient.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.providers import orchestrator_providers as op  # noqa: E402


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _limit_envelope(msg):
    """Синтетический конверт claude с rc=0 и is_error (как реальный 429/лимит)."""
    return json.dumps({"is_error": True, "type": "result",
                       "content": [{"type": "text", "text": msg}]})


@pytest.mark.unit
def test_a_session_limit_raises_a_human_error_without_five_retries():
    calls = {"n": 0}

    def runner(cmd):
        calls["n"] += 1
        return _FakeProc(0, stdout=_limit_envelope(
            "You've hit your session limit (429). Try again at 3:00 PM"))

    with pytest.raises(op.ProviderLimitError) as e:
        op._claude_cli_call("prompt", runner=runner)
    assert calls["n"] == 1, f"лимит повторяли, хотя повтор бессмыслен: {calls['n']} попыток"
    msg = e.value.human_message()
    assert "Лимит модели" in msg and "claude-cli" in msg, msg
    assert "провайдера" in msg, "не сказано про смену провайдера"
    assert "3:00 PM" in msg, f"время сброса не донесено: {msg}"
    assert "Traceback" not in msg


@pytest.mark.unit
def test_a_session_limit_on_nonzero_rc_is_also_recognized():
    """Тот же лимит может прийти и ненулевым кодом (stderr) — ветка rc!=0 обязана ловить так же."""
    def runner(cmd):
        return _FakeProc(1, stderr="Error: You've hit your session limit. Please try again later.")

    with pytest.raises(op.ProviderLimitError):
        op._claude_cli_call("prompt", runner=runner)


@pytest.mark.unit
def test_a_transient_529_is_still_retried_not_turned_into_a_limit():
    """ГРАНИЦА F-011: транзиентный 529 обязан ПОВТОРЯТЬСЯ, а не выдаваться за лимит.

    Снять backoff на 529 нельзя — он введён замером поля (стоил раунда квалификации). Проба
    стережёт, что новая ветка лимита не съела старую ветку повтора.
    """
    seq = [_FakeProc(0, stdout=_limit_envelope("529 Overloaded")),
           _FakeProc(0, stdout=_limit_envelope("529 Overloaded")),
           _FakeProc(0, stdout=json.dumps({"result": "готово", "usage": {}}))]
    calls = {"n": 0}

    def runner(cmd):
        i = calls["n"]; calls["n"] += 1
        return seq[i]

    def _no_sleep(_n):
        return None
    # backoff не должен реально спать в тесте
    import ai_ops_kit.providers.orchestrator_providers as m
    orig_sleep = __import__("time").sleep
    __import__("time").sleep = lambda *_a, **_k: None
    try:
        out = op._claude_cli_call("prompt", runner=runner)
    finally:
        __import__("time").sleep = orig_sleep
    assert out == "готово", out
    assert calls["n"] == 3, f"529 не повторялся как транзиент: {calls['n']}"


@pytest.mark.unit
def test_a_structural_refusal_is_not_a_limit():
    """Контроль: структурный отказ (не лимит, не транзиент) — обычный RuntimeError, не лимитный."""
    def runner(cmd):
        return _FakeProc(1, stderr="claude: unknown flag --frobnicate")

    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=runner)
    assert not isinstance(e.value, op.ProviderLimitError), "структурный отказ выдан за лимит"


@pytest.mark.unit
def test_the_cli_boundary_renders_the_limit_as_message_not_traceback(capsys, monkeypatch):
    """Граница CLI: лимит -> фраза в stderr и код 3, а не трейсбек наверх."""
    from ai_ops_kit.cli import ai_ops_cli as cli

    def _boom(argv):
        raise op.ProviderLimitError("claude-cli", "You've hit your session limit", "3:00 PM")
    monkeypatch.setattr(cli, "main", _boom)

    rc = cli._main_guarded(["review", "."])
    assert rc == 3, f"код возврата не 3 (модель недоступна): {rc}"
    err = capsys.readouterr().err
    assert "Лимит модели" in err and "Traceback" not in err, err
