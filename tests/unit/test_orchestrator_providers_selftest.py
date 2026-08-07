"""Селфтест orchestrator_providers, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from orchestrator_providers import (  # noqa: F401 — имена, которые использует тело
    PROVIDER_AUTORESOLVE_ENV,
    autoresolve_enabled,
    make_claude_cli_provider,
    make_provider,
    mock_provider,
    orchestrator_usage,
    resolve_provider,
)


@pytest.mark.slow
def test_orchestrator_providers_selftest():
    ok = True
    import os as _os

    # провайдер-адаптер: mock офлайн; живой требует ключ (честная ошибка без него)
    if make_provider("mock") is mock_provider:
        print("PASS provider: mock — офлайн-провайдер по умолчанию")
    else:
        ok = False; print("FAIL provider: mock не резолвится в mock_provider")
    _saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        make_provider("anthropic")("тест")
        ok = False; print("FAIL provider: anthropic без ключа должен падать честной ошибкой")
    except SystemExit:
        print("PASS provider: anthropic без ключа -> честная ошибка (не тихий mock)")
    finally:
        if _saved is not None:
            _os.environ["ANTHROPIC_API_KEY"] = _saved
    try:
        make_provider("bogus")
        ok = False; print("FAIL provider: неизвестный провайдер должен падать")
    except SystemExit:
        print("PASS provider: неизвестный провайдер -> ошибка")
    # openai-compatible (v2.39): DeepSeek/local через base_url; ключ из env, без — честная ошибка
    _b = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
    try:
        make_provider("openai-compatible", "deepseek-chat")
        ok = False; print("FAIL openai-compatible без BASE_URL должен падать")
    except SystemExit:
        print("PASS openai-compatible без BASE_URL -> ошибка")
    _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://api.deepseek.com/chat/completions"
    _kb = _os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
    try:
        try:
            make_provider("openai-compatible")   # без model
            ok = False; print("FAIL openai-compatible без model должен падать")
        except SystemExit:
            print("PASS openai-compatible без --model -> ошибка")
        try:
            make_provider("openai-compatible", "deepseek-chat")("тест")   # base есть, ключа нет
            ok = False; print("FAIL openai-compatible без ключа должен падать")
        except SystemExit:
            print("PASS openai-compatible c BASE_URL, но без ключа -> честная ошибка")
    finally:
        if _b is None:
            _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        else:
            _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = _b
    # v3.9.0 First-class Claude Code Adapter: claude-cli провайдер, runner заменяет subprocess.run
    import json as _test_json
    class _FakeResult:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr
    _seen = {}
    _call_stats_before = len(orchestrator_usage._CALL_STATS)
    def _fake_runner(cmd):
        _seen["cmd"] = cmd
        return _FakeResult(stdout=_test_json.dumps({
            "result": "PROPOSED-ACTIONS-JSON",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-opus",
            "total_cost_usd": 0.01
        }))
    _prov = make_claude_cli_provider(model="claude-opus", runner=_fake_runner)
    _out = _prov("сгенерируй tool-loop действия")
    if _out == "PROPOSED-ACTIONS-JSON":
        print("PASS claude-cli: возвращает текст-предложение модели (кит исполняет)")
    else:
        ok = False; print("FAIL claude-cli: не вернул текст провайдера")
    # v3.21.1 регрессия: _record_call вызван (usage измеряется), time.monotonic() не упал
    _call_stats_after = len(orchestrator_usage._CALL_STATS)
    if _call_stats_after > _call_stats_before:
        _last_call = orchestrator_usage._CALL_STATS[-1]
        _has_tokens = _last_call.get("input_tokens") == 100 and _last_call.get("output_tokens") == 50
        _has_cost = _last_call.get("cost_usd_est") is not None
        _has_latency = _last_call.get("latency") is not None and _last_call["latency"] >= 0
        if _has_tokens and _has_latency:
            print("PASS claude-cli: production-path пройден (time.monotonic + _record_call + usage)")
        else:
            ok = False; print(f"FAIL claude-cli: production-path неполный — tokens={_has_tokens}, latency={_has_latency}, call={_last_call}")
    else:
        ok = False; print("FAIL claude-cli: _record_call не вызван (production-path не пройден)")
    _c = _seen.get("cmd") or []
    _allowed = []
    if "--allowedTools" in _c:
        _i = _c.index("--allowedTools") + 1
        while _i < len(_c) and not _c[_i].startswith("--"):
            _allowed.append(_c[_i]); _i += 1
    _read_only = bool(_allowed) and set(_allowed) <= {"Read", "Grep", "Glob"} and "Read" in _allowed
    _no_mutate = not any(t in _c for t in ("Write", "Edit", "Bash"))
    if "-p" in _c and _read_only and _no_mutate:
        print("PASS claude-cli: read-only (Read/Grep/Glob) -> Claude читает, но НЕ мутирует/не исполняет")
    else:
        ok = False; print("FAIL claude-cli: инструменты не ограничены read-only (риск прямого действия Claude в обход кита)")
    if callable(make_provider("claude-cli")):
        print("PASS claude-cli: зарегистрирован как first-class провайдер")
    else:
        ok = False; print("FAIL claude-cli: не резолвится через make_provider")
    # v3.21.1 регрессия: retry-loop + sleep проходят без NameError
    _retry_calls = []
    def _flaky_runner(cmd):
        _retry_calls.append(1)
        if len(_retry_calls) < 3:
            return _FakeResult(returncode=1, stderr="transient error")
        return _FakeResult(stdout=_test_json.dumps({"result": "ok", "usage": {}}))
    _retry_prov = make_claude_cli_provider(runner=_flaky_runner)
    _retry_out = _retry_prov("тест retry")
    if _retry_out == "ok" and len(_retry_calls) == 3:
        print("PASS claude-cli: retry-loop + sleep работают (3 попытки, time.monotonic не упал)")
    else:
        ok = False; print(f"FAIL claude-cli: retry не сработал — calls={len(_retry_calls)}, out={_retry_out}")
    if _kb is not None:
        _os.environ["OPENAI_COMPATIBLE_API_KEY"] = _kb

    # v3.28.x (P2-7): вендоры реестра (qwen/deepseek/kimi) резолвятся в openai-compatible путь,
    # ключ строго из env вендора; объявленный-но-нереализованный — честная ошибка с причиной.
    _qs = _os.environ.pop("QWEN_API_KEY", None)
    try:
        make_provider("qwen")("тест")
        ok = False; print("FAIL vendors: qwen без QWEN_API_KEY должен падать честной ошибкой")
    except SystemExit as _e:
        if "QWEN_API_KEY" in str(_e):
            print("PASS vendors: qwen -> openai-compatible путь, ключ строго из QWEN_API_KEY")
        else:
            ok = False; print(f"FAIL vendors: qwen упал не по ключу — {_e}")
    finally:
        if _qs is not None:
            _os.environ["QWEN_API_KEY"] = _qs
    try:
        make_provider("gigachat")
        ok = False; print("FAIL vendors: нереализованный провайдер реестра должен падать")
    except SystemExit as _e:
        print("PASS vendors: gigachat -> честная ошибка «объявлен в registry, не реализован»"
              if "registry" in str(_e) else "FAIL vendors: причина не названа")

    # v3.28.x (P0-1) резолв провайдера: явный выбор > child-config+ключ > claude в PATH > mock+варн.
    _r_expl = resolve_provider(explicit="mock", root=None, env={}, which=lambda n: "/usr/bin/claude")
    if _r_expl["provider"] == "mock" and _r_expl["source"] == "explicit":
        print("PASS resolve: явный --provider mock побеждает автовыбор")
    else:
        ok = False; print(f"FAIL resolve: явный выбор не победил — {_r_expl}")
    _env_on = {PROVIDER_AUTORESOLVE_ENV: "1"}
    _r_cli = resolve_provider(env=_env_on, which=lambda n: "/usr/bin/claude" if n == "claude" else None)
    if _r_cli["provider"] == "claude-cli":
        print("PASS resolve: claude в PATH -> claude-cli")
    else:
        ok = False; print(f"FAIL resolve: claude в PATH не дал claude-cli — {_r_cli}")
    _r_mock = resolve_provider(env=_env_on, which=lambda n: None)
    if _r_mock["provider"] == "mock" and _r_mock.get("warning"):
        print("PASS resolve: нет ключей и CLI -> mock + громкое предупреждение до прогона")
    else:
        ok = False; print(f"FAIL resolve: молчаливый mock — {_r_mock}")
    _r_off = resolve_provider(env={PROVIDER_AUTORESOLVE_ENV: "0"}, which=lambda n: "/usr/bin/claude")
    if _r_off["provider"] == "mock" and _r_off["source"] == "autoresolve-disabled":
        print("PASS resolve: AI_OPS_PROVIDER_AUTORESOLVE=0 -> mock (CI/selftest офлайн)")
    else:
        ok = False; print(f"FAIL resolve: выключатель автовыбора не сработал — {_r_off}")
    if autoresolve_enabled({"PYTEST_CURRENT_TEST": "x"}) is False and autoresolve_enabled({"CI": "true"}) is False:
        print("PASS resolve: под pytest/в CI автовыбор выключен по умолчанию")
    else:
        ok = False; print("FAIL resolve: автовыбор не выключен под pytest/CI")

    assert ok, "перенесённый селфтест orchestrator_providers: см. строки FAIL в выводе"
