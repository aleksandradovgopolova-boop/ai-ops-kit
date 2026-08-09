"""Селфтест provider_endpoints, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from provider_endpoints import (  # noqa: F401 — имена, которые использует тело
    endpoint_for,
    key_available,
    os,
)


@pytest.mark.slow
def test_provider_endpoints_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("kimi endpoint -> moonshot.ai + KIMI_API_KEY",
           endpoint_for("kimi")["base_url"].startswith("https://api.moonshot.ai") and endpoint_for("kimi")["key_env"] == "KIMI_API_KEY")
    expect("qwen endpoint -> dashscope-intl", "dashscope-intl" in endpoint_for("qwen")["base_url"])
    expect("deepseek endpoint -> api.deepseek.com", "api.deepseek.com" in endpoint_for("deepseek")["base_url"])
    expect("неизвестный провайдер -> None", endpoint_for("ghost") is None)

    # deepseek fallback на OPENAI_COMPATIBLE_API_KEY, если DEEPSEEK_API_KEY нет
    _saved_d = os.environ.pop("DEEPSEEK_API_KEY", None)
    _saved_o = os.environ.get("OPENAI_COMPATIBLE_API_KEY")
    os.environ["OPENAI_COMPATIBLE_API_KEY"] = "x"
    expect("deepseek без DEEPSEEK_API_KEY -> fallback OPENAI_COMPATIBLE_API_KEY",
           endpoint_for("deepseek")["key_env"] == "OPENAI_COMPATIBLE_API_KEY" and key_available("deepseek") is True)
    os.environ["DEEPSEEK_API_KEY"] = "y"
    expect("deepseek с DEEPSEEK_API_KEY -> primary", endpoint_for("deepseek")["key_env"] == "DEEPSEEK_API_KEY")
    os.environ.pop("DEEPSEEK_API_KEY", None)
    if _saved_d is not None:
        os.environ["DEEPSEEK_API_KEY"] = _saved_d
    if _saved_o is None:
        os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
    else:
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = _saved_o

    _saved_k = os.environ.pop("KIMI_API_KEY", None)
    expect("kimi без ключа -> key_available False", key_available("kimi") is False)
    if _saved_k is not None:
        os.environ["KIMI_API_KEY"] = _saved_k

    assert ok, "перенесённый селфтест provider_endpoints: см. строки FAIL в выводе"
