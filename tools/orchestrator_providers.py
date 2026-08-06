#!/usr/bin/env python3
from __future__ import annotations
"""Provider implementations for orchestrator — mock, anthropic, openai, claude-cli.

Extracted from orchestrator.py. Imports HTTP client from orchestrator_http and
usage recording from orchestrator_usage.
"""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
import _bootstrap  # noqa: E402

# Import from sibling submodules
from orchestrator_http import _http_post_json
from orchestrator_usage import _record_call, _CALL_STATS


# --- провайдеры ---

def mock_provider(role_prompt: str) -> str:
    """Детерминированный офлайн-провайдер: возвращает структурированную заглушку."""
    first = role_prompt.splitlines()[0][:80] if role_prompt else ""
    return (f"[mock-provider] Роль принята: {first}\n"
            f"Результат стадии подготовлен согласно контракту роли.")


# --- живые провайдеры (v2.18): реальная модель по ключу из env ---
# Секреты НЕ в репо: ключ читается ТОЛЬКО из переменной окружения. Сеть — через
# системный прокси (urllib берёт HTTPS_PROXY автоматически). Без ключа — честная
# ошибка, не тихий фолбэк на mock (иначе «живой» прогон был бы фикцией).
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o"}
# v3.0-rc7 (finding живого прогона kimi): reasoning-модели (kimi-k3 и т.п.) тратят большой бюджет на
# внутренний reasoning ПЕРЕД контентом. При 2048 весь бюджет уходил в reasoning -> finish_reason=length,
# content пустой. 8192 даёт место reasoning + артефакт. Обычные модели стопятся раньше по stop (без вреда).
_MAX_TOKENS = 8192


def _anthropic_call(prompt, model):
    import os
    import time
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY не задан — живой прогон невозможен. "
                         "Задайте ключ в окружении или используйте --provider mock (офлайн).")
    _t0 = time.monotonic()
    data = _http_post_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": model, "max_tokens": _MAX_TOKENS,
         "messages": [{"role": "user", "content": prompt}]})
    _u = data.get("usage") or {}
    _record_call(model, _u.get("input_tokens"), _u.get("output_tokens"), time.monotonic() - _t0)
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip() or "(пустой ответ модели)"


def _openai_call(prompt, model, base_url="https://api.openai.com/v1/chat/completions",
                 key_env="OPENAI_API_KEY"):
    """OpenAI Chat Completions и любой OpenAI-совместимый endpoint (DeepSeek, local, …)
    через base_url + ключ из указанной env. Секрет — только из env, не в репо/логах."""
    import os
    key = os.environ.get(key_env)
    if not key:
        raise SystemExit(f"{key_env} не задан — живой прогон невозможен. "
                         "Задайте ключ в окружении или используйте --provider mock (офлайн).")
    import time
    # v3.0-rc5 (finding живого прогона kimi): перегруженный провайдер отдаёт HTTP 200 с ПУСТЫМ content
    # (не 429 — _http_post_json его не ловит). Для author/review это фатально (артефакт «не вернулся»).
    # Ретраим пустой ответ с бэкоффом; часть моделей кладёт текст в reasoning_content — используем и его.
    for attempt in range(3):
        _t0 = time.monotonic()
        # v3.0-rc7: reasoning-модели медленные (kimi-k3) — 120с не хватало -> 300с default.
        # v3.6.8: таймаут настраиваем через env OPENAI_COMPATIBLE_TIMEOUT (флагман kimi-k3 бывает >300с).
        _to = int(os.environ.get("OPENAI_COMPATIBLE_TIMEOUT", "300"))
        data = _http_post_json(
            base_url, {"authorization": f"Bearer {key}"},
            {"model": model, "max_tokens": _MAX_TOKENS,
             "messages": [{"role": "user", "content": prompt}]},
            timeout=_to)
        msg = (data.get("choices", [{}])[0] or {}).get("message", {}) or {}
        content = ((msg.get("content") or msg.get("reasoning_content") or "")).strip()
        if content:
            _u = data.get("usage") or {}   # v3.1 trace v0.2: OpenAI-совместимый usage
            _record_call(model, _u.get("prompt_tokens"), _u.get("completion_tokens"), time.monotonic() - _t0)
            return content
        if attempt < 2:
            time.sleep(2 ** attempt)
    return "(пустой ответ модели)"


def make_provider(name: str, model: str = None):
    """Вернуть callable(role_prompt)->text для провайдера.
    'mock' (по умолчанию, офлайн, детерминированный) | 'anthropic' | 'openai'.
    Живые провайдеры вызывают реальный API по ключу из env; без ключа — честная ошибка.
    ВАЖНО: живой путь опционален (opt-in через --provider) — CI/selftest офлайн на mock."""
    if name in (None, "mock"):
        return mock_provider
    if name == "anthropic":
        m = model or DEFAULT_MODELS["anthropic"]
        return lambda prompt: _anthropic_call(prompt, m)
    if name == "openai":
        m = model or DEFAULT_MODELS["openai"]
        return lambda prompt: _openai_call(prompt, m)
    if name == "openai-compatible":
        # DeepSeek / local / любой OpenAI-совместимый: base_url + ключ из env (provider-agnostic).
        import os
        base = os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
        if not base:
            raise SystemExit("OPENAI_COMPATIBLE_BASE_URL не задан — для openai-совместимого "
                             "провайдера (напр. DeepSeek: https://api.deepseek.com/chat/completions) "
                             "укажите base URL в env.")
        if not model:
            raise SystemExit("--model обязателен для openai-compatible (напр. deepseek-chat).")
        return lambda prompt: _openai_call(prompt, model, base_url=base,
                                           key_env="OPENAI_COMPATIBLE_API_KEY")
    if name in ("claude-cli", "claude-code-local"):
        # v3.9.0 First-class Claude Code Adapter: локальный `claude -p` как СИЛЬНЫЙ writer.
        return make_claude_cli_provider(model)
    raise SystemExit(f"неизвестный провайдер '{name}' "
                     f"(есть: mock, anthropic, openai, openai-compatible, claude-cli)")


def _claude_cli_call(prompt, model=None, runner=None, timeout=600, max_attempts=5):
    """v3.9.0 First-class Claude Code Adapter — локальный `claude -p` как ТЕКСТ-провайдер (сильный writer),
    БЕЗ API-ключа (использует локальную аутентифицированную сессию claude CLI).

    БЕЗОПАСНОСТЬ (executing-adapter контракт): `--allowedTools Read Grep Glob` — ТОЛЬКО read-only инструменты.
    Claude ЧИТАЕТ репо (информированное предложение), но НЕ может писать/исполнять (нет Write/Edit/Bash/git) ->
    НЕ трогает FS/git/сеть, НЕ пушит, НЕ создаёт PR, НЕ меняет checkout, НЕ владеет исполнением/lifecycle.
    Модель ПРЕДЛАГАЕТ действия ТЕКСТОМ (JSON tool-loop); применяет их КИТ через свой sandbox/broker
    (scope-enforced, exact-SHA, gates, delivery). AI Ops = control plane, Claude Code = сильный ЗАМЕНЯЕМЫЙ
    исполнитель. (Полный tool-less `--tools ""` авторит вслепую -> невалидная спека; read-only даёт контекст
    без права действия — доказано fs-rc3.)

    v3.10.0 Usage Truth: `--output-format json` -> claude usage (input/output_tokens) + total_cost_usd
    ИЗМЕРЯЮТСЯ и пишутся в _record_call (provider=claude-cli). Claude CLI usage больше НЕ исчезает.

    runner инъектируется (офлайн-selftest без вызова CLI); заменяет subprocess.run, а не весь вызов —
    production-path (time.monotonic, json parse, _record_call, retries) проходит полностью. Ключ не требуется.

    Устойчивость к транзиентам (находка F-011, Real-Product Qualification): транзиентные сбои API
    (5xx/429/**529 Overloaded**, сетевые, subprocess-timeout) ретраятся с экспоненциальным backoff+jitter,
    а не после 3 фиксированных пауз — один невосстановленный 529 больше не роняет весь многошаговый прогон.
    Синтетический конверт claude `is_error:true` на rc==0 (напр. 529: `input_tokens:0, stop_reason:stop_sequence`)
    распознаётся и НЕ выдаётся за валидный результат. Полный человекочитаемый текст ошибки сохраняется
    (парсинг `content[].text`/`error`), а не режется до 200 символов (F-011a — обрезка прятала «529 Overloaded»)."""
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--allowedTools", "Read", "Grep", "Glob"]
    if model:
        cmd += ["--model", model]
    import subprocess
    import json as _json
    import time
    import random
    # runner заменяет subprocess.run (не весь вызов) — production-path проходит в selftest
    _run = runner if runner is not None else (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=timeout))

    def _human_error(text):
        # F-011a: читаемая причина из JSON claude (content[].text / error) — НЕ резать диагностику до 200 символов
        try:
            d = _json.loads(text)
        except Exception:
            return (text or "").strip()[:2000]
        parts = []
        if d.get("error"):
            parts.append(str(d.get("error")))
        msg = d.get("message") if isinstance(d.get("message"), dict) else None
        for blk in ((msg.get("content") if msg else None) or d.get("content") or []):
            if isinstance(blk, dict) and blk.get("type") == "text" and blk.get("text"):
                parts.append(blk["text"])
        return (" | ".join(parts) or (text or "").strip())[:2000]

    def _transient(text):
        t = (text or "").lower()
        return any(s in t for s in ("overloaded", "529", "429", "rate limit", "rate_limit",
                                    "500", "502", "503", "504", "internal server error",
                                    "temporarily", "server_error", "timeout", "timed out", "connection"))

    def _backoff(n):
        time.sleep(min(30.0, 2.0 ** n) + random.uniform(0, 1))   # экспонента + jitter, потолок 30с

    last = ""
    for _attempt in range(max_attempts):
        _t0 = time.monotonic()
        try:
            r = _run(cmd)
        except subprocess.TimeoutExpired:   # обычно слишком большой промпт (весь транскрипт одним argv, см. F-011)
            last = "claude -p: таймаут subprocess (%ss) — вероятно слишком большой промпт" % timeout
            if _attempt + 1 >= max_attempts:
                break
            _backoff(_attempt); continue
        if r.returncode == 0:
            try:
                d = _json.loads(r.stdout)
            except Exception:   # json не распарсился -> usage unavailable (НЕ теряем факт вызова)
                _record_call(model or "claude-code-local", None, None, time.monotonic() - _t0, provider="claude-cli")
                return r.stdout
            if d.get("is_error"):   # синтетический конверт claude (rc=0!), напр. 529 Overloaded — НЕ валидный результат
                last = _human_error(r.stdout)
                if _transient(last) and _attempt + 1 < max_attempts:
                    _backoff(_attempt); continue
                raise RuntimeError("claude -p вернул is_error (rc=0): %s" % last)
            u = d.get("usage") or {}
            _record_call(d.get("model") or model or "claude-code-local",
                         u.get("input_tokens"), u.get("output_tokens"), time.monotonic() - _t0,
                         provider="claude-cli", cost=d.get("total_cost_usd"))
            return d.get("result") or ""
        last = _human_error(r.stderr or r.stdout or "")   # rc!=0 (сеть/5xx/оверлоад) -> ретрай с backoff
        if _attempt + 1 >= max_attempts:
            break
        _backoff(_attempt)
    raise RuntimeError("claude -p не удался после %d попыток: %s" % (max_attempts, last))


def make_claude_cli_provider(model=None, runner=None):
    """callable(prompt)->text через локальный `claude -p` (tool-less). См. _claude_cli_call: executing-adapter
    контракт — Claude предлагает, кит исполняет и блокирует по гейтам."""
    return lambda prompt: _claude_cli_call(prompt, model=model, runner=runner)


def make_openai_provider(model, base_url, key_env):
    """openai-compatible провайдер с ЯВНЫМ endpoint+key_env — per-role/vendor маршрутизация (v3.7.12,
    Router->ai_ops_run). Ключ читает _openai_call из env по имени key_env; значение не передаётся и не
    логируется. Так writer/reviewer резолвятся в РАЗНЫЕ модели/вендоры в одном прогоне."""
    return lambda prompt: _openai_call(prompt, model, base_url=base_url, key_env=key_env)


# ---------------- selftest ----------------

def selftest():
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
    _call_stats_before = len(_CALL_STATS)
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
    _call_stats_after = len(_CALL_STATS)
    if _call_stats_after > _call_stats_before:
        _last_call = _CALL_STATS[-1]
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

    print("orchestrator_providers selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
