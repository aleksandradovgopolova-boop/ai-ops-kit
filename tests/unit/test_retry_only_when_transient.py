"""Повтор назначается там, где он может помочь, — и не назначается там, где не может.

ЗАЯВКА #160 (внешнее ревью 19.08.2026). `claude-cli` внутри активной сессии Claude Code не работает
СТРУКТУРНО: отказ детерминированный. Кит делал пять попыток с экспоненциальным backoff и только
потом падал — то есть платил ~минуту ожидания за результат, известный после первой попытки.
Принцип принят дословно, потому что он проверяемый: **если отказ детерминированный, пятый повтор не
делает систему надёжнее — он делает её медленнее.**

ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ПЕРЕЙТИ, и она проверяется здесь наравне с самой правкой: backoff на
ТРАНЗИЕНТНОМ 529 введён замером поля (F-011, раунд квалификации 3.27.7). Снять его значило бы
вернуть дефект, который стоил целого раунда. Поэтому правка отличает два класса, а не отменяет
повтор, и тест требует ОБОИХ свойств: структурный отказ — одна попытка, транзиентный — все пять.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.providers import orchestrator_providers as op  # noqa: E402


class _Runner:
    """Считает попытки и отдаёт заданный ответ. Заменяет subprocess.run, а не весь вызов."""

    def __init__(self, returncode=1, stdout="", stderr=""):
        self.calls = 0
        self._rc, self._out, self._err = returncode, stdout, stderr

    def __call__(self, cmd):
        self.calls += 1
        return subprocess.CompletedProcess(cmd, self._rc, self._out, self._err)


@pytest.mark.unit
def test_a_structural_failure_is_not_retried():
    """Отказ, который повтор не лечит, стоит ОДНОЙ попытки, а не пяти."""
    runner = _Runner(returncode=1, stderr="Error: claude cannot run inside an active session")
    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert runner.calls == 1, f"структурный отказ повторён {runner.calls} раз(а)"
    assert "структурно" in str(e.value), str(e.value)
    assert "повтор не назначен" in str(e.value), str(e.value)


@pytest.mark.unit
def test_the_reason_survives_and_is_not_truncated():
    """Причина отказа доходит до человека: по ней и отличают структурный сбой от транзиентного."""
    runner = _Runner(returncode=2, stderr="unknown option '---title: роль'")
    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert "unknown option" in str(e.value), str(e.value)


@pytest.mark.unit
@pytest.mark.parametrize("text", ["529 Overloaded", "rate limit exceeded", "502 Bad Gateway",
                                  "connection reset by peer", "request timed out"])
def test_a_transient_failure_still_gets_every_attempt(monkeypatch, text):
    """F-011 НЕ ОТМЕНЁН: транзиентный отказ по-прежнему получает все попытки с backoff."""
    # `time` импортируется ВНУТРИ функции, поэтому патчим настоящий модуль, а не атрибут провайдера:
    # иначе тест ждал бы реальные паузы backoff (до ~60 секунд на пять попыток).
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    runner = _Runner(returncode=1, stderr=text)
    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert runner.calls == 5, f"транзиентный отказ получил {runner.calls} попыток вместо 5"
    assert "после 5 попыток" in str(e.value), str(e.value)


@pytest.mark.unit
def test_the_synthetic_error_envelope_keeps_its_own_rule(monkeypatch):
    """Конверт `is_error` на rc=0 (класс F-011) — тот же признак транзиентности, что и у rc!=0.

    Обе ветки одного решения обязаны судить одинаково: расхождение между ними и было дефектом.
    """
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    transient = _Runner(returncode=0, stdout='{"is_error": true, "error": "529 Overloaded"}')
    with pytest.raises(RuntimeError):
        op._claude_cli_call("prompt", runner=transient, max_attempts=3)
    assert transient.calls == 3, "транзиентный конверт перестал ретраиться"

    structural = _Runner(returncode=0, stdout='{"is_error": true, "error": "invalid api key"}')
    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=structural, max_attempts=3)
    assert structural.calls == 1, f"структурный конверт повторён {structural.calls} раз(а)"
    assert "invalid api key" in str(e.value)


@pytest.mark.unit
def test_a_good_answer_is_returned_on_the_first_call():
    """Контроль: исправный путь не задет — одна попытка, результат возвращён."""
    runner = _Runner(returncode=0, stdout='{"result": "готово", "usage": {"input_tokens": 10}}')
    assert op._claude_cli_call("prompt", runner=runner) == "готово"
    assert runner.calls == 1
