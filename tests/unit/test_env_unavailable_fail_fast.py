"""Структурно нерабочий в среде `claude-cli` — fail-fast с понятным выходом, а не пять повторов.

ЗАЯВКА #160 (defect p1, поле 18.08.2026, ИИ-Среда). Когда `run --execute` запущен ИЗНУТРИ уже
открытой сессии Claude Code, вложенный `claude -p` возвращается мгновенно синтетическим
конвертом-ошибкой, НЕ дойдя до модели:

    {"is_error": true, "duration_api_ms": 0, "input_tokens": 0,
     "output_tokens": 0, "terminal_reason": "api_error", "stop_reason": "stop_sequence"}

Причина — сама среда (сессия внутри сессии), отказ детерминированный. Прежде кит делал пять
бессмысленных повторов и ронял трейсбек «claude -p не удался после 5 попыток»: человек не видел ни
причины, ни выхода.

Три свойства проверяются здесь, каждое — отдельная capability:
  1. POSITIVE      — структурный отказ распознаётся и даёт fail-fast (ОДНА попытка, не пять).
  2. FAIL-CLOSED   — настоящий транзиент (529 с ненулевым duration/токенами) по-прежнему повторяется:
                     мы не сломали backoff, введённый замером F-011.
  3. SIDE-EFFECT   — сообщение человеку реально несёт ОБА выхода (терминал вне сессии / --provider),
                     и повторов на структурном отказе — ноль.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.providers import orchestrator_providers as op  # noqa: E402

# Дословная сигнатура из заявки #160 (воспроизведена прямым `claude -p` из активной сессии).
_ENV_FAILURE_ENVELOPE = {
    "is_error": True,
    "duration_api_ms": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "terminal_reason": "api_error",
    "stop_reason": "stop_sequence",
}


class _Runner:
    """Считает попытки и отдаёт заданный ответ. Заменяет subprocess.run, а не весь вызов."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = 0
        self._rc, self._out, self._err = returncode, stdout, stderr

    def __call__(self, cmd):
        self.calls += 1
        return subprocess.CompletedProcess(cmd, self._rc, self._out, self._err)


@pytest.mark.unit
def test_positive_structural_env_failure_fails_fast_without_retries(monkeypatch):
    """Структурный отказ среды распознан → fail-fast ОДНОЙ попыткой, а не пятью."""
    # backoff обнулён, чтобы «5 повторов» (если бы регресс их вернул) не ждали реальных пауз.
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    runner = _Runner(returncode=0, stdout=json.dumps(_ENV_FAILURE_ENVELOPE))
    with pytest.raises(op.ProviderEnvUnavailableError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert runner.calls == 1, f"структурный отказ среды повторён {runner.calls} раз(а) вместо одного"
    # Именно этот тип, а не общий RuntimeError «не удался после N попыток».
    assert "claude -p не удался после" not in str(e.value), str(e.value)


@pytest.mark.unit
def test_positive_detected_on_nonzero_returncode_too(monkeypatch):
    """Тот же конверт с ненулевым кодом возврата тоже распознаётся структурным (stdout несёт JSON)."""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    runner = _Runner(returncode=1, stdout=json.dumps(_ENV_FAILURE_ENVELOPE))
    with pytest.raises(op.ProviderEnvUnavailableError):
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert runner.calls == 1, f"структурный отказ (rc!=0) повторён {runner.calls} раз(а)"


@pytest.mark.unit
def test_fail_closed_real_transient_still_retries_every_attempt(monkeypatch):
    """F-011 НЕ ОТМЕНЁН: настоящий транзиент (529, НЕнулевой duration/токены) получает все попытки.

    Ключ отличия — сигнатура: у транзиентного 529 есть время в API и токены, у структурного отказа
    среды — нули. Детекция не должна проглотить транзиент, иначе вернётся дефект, стоивший раунда
    квалификации (backoff на 529).
    """
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    transient = {
        "is_error": True,
        "error": "529 Overloaded",
        "duration_api_ms": 812,          # дошло до API — это НЕ структурный отказ среды
        "input_tokens": 1024,
        "terminal_reason": "api_error",  # даже при том же terminal_reason сигнатура иная (не нули)
    }
    runner = _Runner(returncode=0, stdout=json.dumps(transient))
    with pytest.raises(RuntimeError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)
    assert not isinstance(e.value, op.ProviderEnvUnavailableError), \
        "транзиент 529 ошибочно принят за структурный отказ среды"
    assert runner.calls == 5, f"транзиентный отказ получил {runner.calls} попыток вместо 5"
    # (сам транзиент 529 несёт свой текст — важно, что повторов было пять, а тип не наш fail-fast)
    assert "529" in str(e.value), str(e.value)


@pytest.mark.unit
def test_fail_closed_healthy_answer_untouched():
    """Контроль: исправный путь не задет — одна попытка, результат возвращён."""
    runner = _Runner(returncode=0, stdout='{"result": "готово", "usage": {"input_tokens": 10}}')
    assert op._claude_cli_call("prompt", runner=runner) == "готово"
    assert runner.calls == 1


@pytest.mark.unit
def test_side_effect_message_names_both_exits_and_zero_retries(monkeypatch):
    """Сообщение человеку реально несёт ОБА выхода, и повторов на структурном отказе — ноль."""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    runner = _Runner(returncode=0, stdout=json.dumps(_ENV_FAILURE_ENVELOPE))
    with pytest.raises(op.ProviderEnvUnavailableError) as e:
        op._claude_cli_call("prompt", runner=runner, max_attempts=5)

    msg = str(e.value)
    # Выход №1: запустить вне сессии Claude, из обычного терминала.
    assert "терминал" in msg.lower(), msg
    assert "сесси" in msg.lower(), msg
    # Выход №2: указать другого исполнителя с ключом.
    assert "--provider" in msg, msg
    # Последствие названо простым языком (product-уровень), без внутренних терминов.
    assert "выполнить не удалось" in msg, msg
    # Повтор бессмыслен и не сделан.
    assert runner.calls == 1, f"на структурном отказе сделано {runner.calls} попыток вместо одной"


@pytest.mark.unit
def test_detector_requires_the_full_signature():
    """`_env_unavailable_envelope` требует ВСЕ признаки — иначе транзиент попал бы под fail-fast."""
    assert op._env_unavailable_envelope(_ENV_FAILURE_ENVELOPE) is True
    # Ненулевой duration → это дошло до API, не структурный отказ среды.
    assert op._env_unavailable_envelope({**_ENV_FAILURE_ENVELOPE, "duration_api_ms": 5}) is False
    # Ненулевые токены → модель отвечала.
    assert op._env_unavailable_envelope({**_ENV_FAILURE_ENVELOPE, "input_tokens": 7}) is False
    # Другой terminal_reason → не наш класс.
    assert op._env_unavailable_envelope({**_ENV_FAILURE_ENVELOPE, "terminal_reason": "refusal"}) is False
    # Не ошибка вовсе.
    assert op._env_unavailable_envelope({"is_error": False}) is False
    assert op._env_unavailable_envelope(None) is False
