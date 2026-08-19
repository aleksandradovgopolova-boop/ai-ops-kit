#!/usr/bin/env python3
"""Provider implementations for orchestrator — mock, anthropic, openai, claude-cli.

Extracted from orchestrator.py. Imports HTTP client from orchestrator_http and
usage recording from orchestrator_usage.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
from ai_ops_kit.shared import _bootstrap  # noqa: E402

# Import from sibling submodules
from ai_ops_kit.providers.orchestrator_http import _http_post_json
from ai_ops_kit.providers import orchestrator_usage          # noqa: E402 — _CALL_STATS читаем ЖИВЫМ (drain пересоздаёт список)
from ai_ops_kit.providers.orchestrator_usage import _record_call


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


# v3.28.x (review 2026-08-06, P2-7): имена провайдеров из registry/providers.yaml, которые технически
# являются OpenAI-совместимыми (protocols: [rest, openai-compatible]). Раньше `--provider qwen` падал
# «неизвестный провайдер», хотя реестр его объявляет — registry и код расходились.
# ИСТОЧНИК ИСТИНЫ — registry/providers.yaml (key_env) и registry/models.yaml (default_model);
# соответствие проверяется тестом tests/unit/test_provider_resolution.py (registry-consistency).
# base_url — те же проверенные эндпоинты, что в tools/provider_endpoints.py; переопределяется env.
# Секрет НИКОГДА не в коде: здесь только ИМЯ переменной окружения.
OPENAI_COMPATIBLE_VENDORS = {
    "deepseek": {"key_env": "DEEPSEEK_API_KEY", "base_url_env": "DEEPSEEK_BASE_URL",
                 "base_url": "https://api.deepseek.com/chat/completions",
                 "default_model": "deepseek-v4-flash"},
    "qwen": {"key_env": "QWEN_API_KEY", "base_url_env": "QWEN_BASE_URL",
             "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
             "default_model": "qwen3-coder-plus"},
    "kimi": {"key_env": "KIMI_API_KEY", "base_url_env": "KIMI_BASE_URL",
             "base_url": "https://api.moonshot.ai/v1/chat/completions",
             "default_model": "kimi-k2.7-code-highspeed"},
}

# Объявлены в registry/providers.yaml, но НЕ реализованы адаптером движка. Честная ошибка с причиной
# лучше и «неизвестного провайдера» (реестр их знает), и тихого фолбэка на mock.
DECLARED_NOT_IMPLEMENTED = {
    "google": "нет REST-адаптера Gemini (registry: kind hosted-api, protocols [rest])",
    "gigachat": "нужен OAuth-адаптер NGW (registry: adoption_status planned-future)",
    "local": "укажите endpoint явно: --provider openai-compatible + OPENAI_COMPATIBLE_BASE_URL "
             "(registry: LOCAL_LLM_BASE_URL)",
    "custom": "укажите endpoint явно: --provider openai-compatible + OPENAI_COMPATIBLE_BASE_URL",
}


def make_provider(name: str, model: str = None):
    """Вернуть callable(role_prompt)->text для провайдера.
    'mock' (по умолчанию, офлайн, детерминированный) | 'anthropic' | 'openai' |
    'openai-compatible' | 'claude-cli' | вендоры из OPENAI_COMPATIBLE_VENDORS (qwen/deepseek/kimi).
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
    if name in OPENAI_COMPATIBLE_VENDORS:
        # qwen/deepseek/kimi — openai-совместимые вендоры реестра: base_url по умолчанию + ключ
        # СТРОГО из env вендора. Ключа нет -> честная ошибка внутри _openai_call (не тихий mock).
        v = OPENAI_COMPATIBLE_VENDORS[name]
        base = os.environ.get(v["base_url_env"]) or v["base_url"]
        return lambda prompt: _openai_call(prompt, model or v["default_model"],
                                           base_url=base, key_env=v["key_env"])
    if name in DECLARED_NOT_IMPLEMENTED:
        raise SystemExit(f"провайдер '{name}' объявлен в registry/providers.yaml, но не реализован "
                         f"адаптером движка: {DECLARED_NOT_IMPLEMENTED[name]}")
    raise SystemExit(f"неизвестный провайдер '{name}' (есть: mock, anthropic, openai, "
                     f"openai-compatible, claude-cli, "
                     f"{', '.join(sorted(OPENAI_COMPATIBLE_VENDORS))})")


# ---------------- резолв провайдера (v3.28.x, review 2026-08-06, P0-1) ----------------
#
# Проблема: `--provider` имел хардкод-дефолт `mock`, поэтому в чистом репозитории `run --execute`
# давал «провайдер: mock · правок 0» даже когда `claude` есть в PATH, а `.ai-ops.yaml` объявляет
# providers.default: anthropic с ключом в env. Резолв ниже выбирает провайдера ЯВНО и ГРОМКО.
#
# Приоритет (первый сработавший побеждает):
#   1. явный --provider X (в т.ч. явный `mock`) — решение человека всегда сильнее автовыбора;
#   2. .ai-ops.yaml -> providers.default, ЕСЛИ ключ этого провайдера РЕАЛЬНО есть в env
#      (credentials_ref: "env:ANTHROPIC_API_KEY" -> проверяем os.environ, значение не читаем в лог);
#   3. `claude` в PATH -> claude-cli (локальная сессия, ключ не нужен);
#   4. иначе mock + ГРОМКОЕ предупреждение ДО прогона (а не молчаливый ноль правок постфактум).
#
# Инвариант офлайн-детерминизма (failure mode №1 Change Brief): автовыбор применяется ТОЛЬКО в
# пользовательском пути `run --execute`. Всё остальное (selftest, pytest, CI) получает mock —
# см. autoresolve_enabled(): под pytest/в CI автовыбор выключен по умолчанию, а
# AI_OPS_PROVIDER_AUTORESOLVE=0 выключает его где угодно явно (selftest-пути ставят именно его).

PROVIDER_AUTORESOLVE_ENV = "AI_OPS_PROVIDER_AUTORESOLVE"
_FALSY = {"0", "false", "no", "off", "none", ""}
_TRUTHY = {"1", "true", "yes", "on"}

# Имя env-переменной с ключом по провайдеру — ИЗ registry/providers.yaml (auth.env[0]).
# Используется только когда child-конфиг не задал credentials_ref явно.
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gigachat": "GIGACHAT_AUTH_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "QWEN_API_KEY",
    "kimi": "KIMI_API_KEY",
    "local": "LOCAL_LLM_BASE_URL",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
    "custom": "CUSTOM_PROVIDER_TOKEN",
}

NO_LIVE_PROVIDER_WARNING = ("живой провайдер не настроен → правок не будет; "
                            "задайте ANTHROPIC_API_KEY или установите claude CLI")

CLAUDE_BIN_ENV = "AI_OPS_CLAUDE_BIN"


def claude_lookup(env=None, which=None):
    """Где искали `claude` и что нашли -> {"path": str|None, "where": "named"|"path"}.

    ЗАЧЕМ ОТДЕЛЬНАЯ ФУНКЦИЯ, а не `shutil.which` по месту: проверка присутствия и запуск обязаны
    смотреть в ОДНО И ТО ЖЕ. Прежде выбор провайдера звал `which("claude")`, а запуск подставлял
    короткое имя `claude` — то есть два разных решения, и между ними успевало помещаться расхождение
    (поле 13.08 и 15.08.2026, дочка ИИ-Среда: `FileNotFoundError: 'claude'` при живом claude в
    терминале). Здесь путь вычисляется один раз и им же исполняется.

    ЗАЧЕМ ЕЩЁ И `where` (замер 18.08.2026): одного пути мало — решение о провайдере обязано
    называть, ОТКУДА взялся исполнитель. Автовыбор печатал «claude CLI найден в PATH» и в том
    случае, когда путь пришёл словом владельца, то есть говорил про PATH неправду; а на живом
    прогоне с битым `AI_OPS_CLAUDE_BIN` при claude в PATH — печатал ту же строку, выбирал
    claude-cli без предупреждения и умирал на первом вызове модели, уже зарегистрировав работу
    и подготовив рабочее дерево.

    `which` по умолчанию берёт PATH ИЗ ПЕРЕДАННОГО env, а не из окружения процесса: иначе замер с
    подменённым PATH молча смотрел бы в настоящий PATH и показывал ложную картину.
    """
    env = os.environ if env is None else env
    if which is None:
        def which(name, _path=env.get("PATH")):
            return shutil.which(name, path=_path)
    named = str(env.get(CLAUDE_BIN_ENV) or "").strip()
    if named:
        ok = os.path.isfile(named) and os.access(named, os.X_OK)
        return {"path": named if ok else None, "where": "named"}
    return {"path": which("claude"), "where": "path"}


def claude_binary(env=None, which=None):
    """Абсолютный путь к `claude` или None. Явное слово владельца (AI_OPS_CLAUDE_BIN) сильнее PATH."""
    return claude_lookup(env=env, which=which)["path"]


def claude_found_reason(lookup):
    """Человеческая причина «чем пойдём» — по ФАКТУ находки, а не по догадке о её источнике."""
    if lookup["where"] == "named":
        return (f"claude CLI взят из {CLAUDE_BIN_ENV}={lookup['path']} "
                "(путь назван явно; PATH не спрашивался)")
    return "claude CLI найден в PATH (локальная сессия, API-ключ не нужен)"


def claude_missing_message(env=None, extra=""):
    """Человеческая причина вместо `FileNotFoundError: 'claude'` — с ЗАМЕРОМ, а не с догадкой.

    Поле 13.08 и 15.08.2026 (ИИ-Среда): прогон падал этой строкой, и по ней нельзя было отличить
    «бинаря нет» от «бинарь есть, но не в PATH этого процесса» — а различие определяет, что делать.
    Поэтому сообщение называет: что искали, ГДЕ искали (реальный PATH процесса кита) и куда смотреть.
    """
    env = os.environ if env is None else env
    named = str(env.get(CLAUDE_BIN_ENV) or "").strip()
    entries = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
    where = (f"{CLAUDE_BIN_ENV}={named} — файла нет или он не исполняемый"
             if named else
             f"PATH процесса кита, записей {len(entries)}: {os.pathsep.join(entries)}")
    return ("не найден исполняемый файл `claude`, поэтому исполняющий прогон не начат"
            + (f" ({extra})" if extra else "") + ".\n"
            f"  где искали: {where}\n"
            "  почему это бывает при живом claude в терминале: PATH интерактивной оболочки "
            "(.zshrc/.zprofile) в процесс кита не попадает — например при запуске из другого "
            "окружения, из venv или из планировщика.\n"
            f"  что сделать (одно из трёх): назвать путь явно — {CLAUDE_BIN_ENV}=/путь/к/claude; "
            "добавить каталог claude в PATH того окружения, из которого запускаете кит; "
            "или попросить офлайн прямо — `--provider mock` (модель не вызывается, правок не будет).")


def autoresolve_enabled(env=None) -> bool:
    """Разрешён ли автовыбор провайдера. Явный AI_OPS_PROVIDER_AUTORESOLVE побеждает всегда;
    без него автовыбор выключен под pytest и в CI (офлайн-детерминизм, деньги не тратятся)."""
    env = os.environ if env is None else env
    raw = env.get(PROVIDER_AUTORESOLVE_ENV)
    if raw is not None:
        return str(raw).strip().lower() not in _FALSY
    if env.get("PYTEST_CURRENT_TEST"):
        return False
    if str(env.get("CI", "")).strip().lower() in _TRUTHY:
        return False
    return True


def _child_providers(root):
    """providers-секция child-конфига `.ai-ops.yaml`: {default, key_env: {id: ENV_NAME}}.
    Из credentials_ref берём ТОЛЬКО имя env-переменной (env:NAME); secret:-ссылку проверить
    из движка нельзя -> такой провайдер автовыбором не берём (fail-closed, не «вроде бы есть»)."""
    out = {"default": None, "key_env": {}, "unverifiable": {}}
    if not root:
        return out
    try:
        import yaml as _yaml
        p = Path(root) / ".ai-ops.yaml"
        if not p.is_file():
            return out
        data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:   # noqa: BLE001 — битый/нечитаемый конфиг не должен ронять прогон
        return out
    prov = (data or {}).get("providers") if isinstance(data, dict) else None
    if not isinstance(prov, dict):
        return out
    d = prov.get("default")
    out["default"] = d if isinstance(d, str) and d else None
    for item in prov.get("configured") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        ref = str(item.get("credentials_ref") or "")
        if ref.startswith("env:") and ref[4:]:
            out["key_env"][item["id"]] = ref[4:]
        elif ref:
            out["unverifiable"][item["id"]] = ref.split(":", 1)[0]
    return out


def resolve_provider(explicit=None, root=None, env=None, which=None):
    """Выбрать провайдера для пользовательского прогона. Возвращает словарь-решение:
    {provider, source, reason, warning, autoresolve, checked} — имя провайдера НЕ теряется по
    дороге: вызывающий обязан передать его в make_provider и записать в отчёт прогона.

    explicit — значение --provider (None = пользователь не задавал; 'mock' = задал явно).
    root     — корень child-репозитория (там ищем .ai-ops.yaml).
    env/which — инъекция окружения и shutil.which (тестируемость без сети и без CLI)."""
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    checked = []

    if explicit:
        # ЯВНЫЙ ВЫБОР ЧЕЛОВЕКА НЕ ОСПАРИВАЕТСЯ, НО И НЕ ОСТАЁТСЯ НЕПРОВЕРЕННЫМ (поле 13.08 и
        # 15.08.2026, ИИ-Среда). Прежде здесь не проверялось ничего: `--provider claude-cli` без
        # бинаря доводил прогон до вызова модели и ронял его сырым `FileNotFoundError`, уже после
        # разбора, плана и подготовки дерева. Провайдер остаётся тем, что назвал человек — меняется
        # только то, что об отсутствии сказано ДО прогона, а не трейсбеком посреди него.
        warning = None
        if explicit == "claude-cli" and not claude_binary(env=env, which=which):
            warning = ("выбран claude-cli, но исполняемый файл `claude` не найден — прогон дойдёт "
                       "до вызова модели и остановится. " + claude_missing_message(env=env))
            checked.append("claude CLI не найден (провайдер задан явно)")
        return {"provider": explicit, "source": "explicit", "autoresolve": False,
                "reason": f"задан явно: --provider {explicit}", "warning": warning,
                "checked": checked}

    if not autoresolve_enabled(env):
        return {"provider": "mock", "source": "autoresolve-disabled", "autoresolve": False,
                "reason": (f"автовыбор выключен ({PROVIDER_AUTORESOLVE_ENV}=0 / pytest / CI) — "
                           "офлайн-детерминизм: mock"),
                "warning": None, "checked": checked}

    cfg = _child_providers(root)
    default = cfg.get("default")
    if default and default != "mock":
        key_env = cfg["key_env"].get(default) or PROVIDER_KEY_ENV.get(default)
        if default in cfg["unverifiable"] and default not in cfg["key_env"]:
            checked.append(f".ai-ops.yaml providers.default={default}: credentials_ref — "
                           f"{cfg['unverifiable'][default]}:-ссылка, из движка не проверяется")
        elif not key_env:
            checked.append(f".ai-ops.yaml providers.default={default}: неизвестно, какой env-ключ "
                           "проверять (нет credentials_ref и записи в registry)")
        elif env.get(key_env):
            return {"provider": default, "source": "child-config", "autoresolve": True,
                    "reason": f".ai-ops.yaml providers.default={default}, ключ {key_env} есть в env",
                    "warning": None, "checked": checked, "key_env": key_env}
        else:
            checked.append(f".ai-ops.yaml providers.default={default}: {key_env} отсутствует в env")

    # АВТОВЫБОР СПРАШИВАЕТ ТО ЖЕ, ЧЕМ БУДЕТ ЗАПУСКАТЬ (замер 18.08.2026). Здесь стоял голый
    # `which("claude")` — тот самый второй взгляд, который `claude_lookup` заводился устранить, и
    # расхождение осталось живым ровно на пути автовыбора (явный `--provider claude-cli` проверялся
    # с 17.08, PR #141). Замерено два направления, и оба врали человеку:
    #   · назван рабочий путь, claude вне PATH (запуск из venv/планировщика) -> `which` пусто ->
    #     «живого провайдера не нашлось» и mock, то есть «правок не будет» при живом исполнителе;
    #   · claude в PATH, назван битый путь -> `which` есть -> claude-cli без предупреждения, работа
    #     зарегистрирована, дерево подготовлено, и прогон умирает на первом вызове модели.
    _look = claude_lookup(env=env, which=which)
    if _look["path"]:
        return {"provider": "claude-cli",
                "source": "claude-cli-named" if _look["where"] == "named" else "claude-cli-in-path",
                "reason": claude_found_reason(_look),
                "autoresolve": True, "warning": None, "checked": checked}
    checked.append(f"{CLAUDE_BIN_ENV}={env.get(CLAUDE_BIN_ENV)} — файла нет или он не исполняемый"
                   if _look["where"] == "named" else "claude CLI не найден в PATH")

    # СОВЕТ ПО ПРИЧИНЕ, А НЕ ОДИН НА ВСЕ СЛУЧАИ: «установите claude CLI» человеку, у которого CLI
    # стоит и назван, а сломан путь, отправляет чинить не то. Названный путь сильнее PATH осознанно
    # (иначе кит молча пошёл бы другим исполнителем, чем ему сказали), поэтому здесь именно отказ с
    # причиной — до прогона, а не посреди него.
    warning = (f"назван {CLAUDE_BIN_ENV}={env.get(CLAUDE_BIN_ENV)}, но файла нет или он не "
               "исполняемый → правок не будет; поправьте путь или уберите переменную, чтобы "
               "искать claude в PATH") if _look["where"] == "named" else NO_LIVE_PROVIDER_WARNING
    return {"provider": "mock", "source": "fallback", "autoresolve": True,
            "reason": "живого провайдера не нашлось", "warning": warning,
            "checked": checked}


def print_provider_resolution(res, printer=print):
    """Громкая печать решения ДО прогона (честность деклараций: скатились в mock — говорим сразу)."""
    if not isinstance(res, dict):
        return
    if res.get("warning"):
        # ИМЯ ПРОВАЙДЕРА БЕРЁТСЯ ИЗ РЕШЕНИЯ, а не вписано «mock» намертво: предупреждение бывает и
        # у живого выбора (явный claude-cli без бинаря), и тогда жёсткая строка сообщала владельцу
        # неправду о том, чем пойдёт прогон. Для прежнего случая (fallback) провайдер и есть mock,
        # поэтому вывод там не изменился.
        printer(f"⚠ провайдер: {res.get('provider')} — {res['warning']}")
        for c in res.get("checked") or []:
            printer(f"  · {c}")
    elif res.get("source") not in (None, "explicit"):
        printer(f"провайдер: {res.get('provider')} — {res.get('reason')}")


def _claude_cli_call(prompt, model=None, runner=None, timeout=600, max_attempts=5):
    """v3.9.0 First-class Claude Code Adapter — локальный `claude -p` как ТЕКСТ-провайдер (сильный writer),
    БЕЗ API-ключа (использует локальную аутентифицированную сессию claude CLI).

    БЕЗОПАСНОСТЬ (executing-adapter контракт): `--allowedTools Read Grep Glob` — ТОЛЬКО read-only инструменты.
    Claude ЧИТАЕТ репо (информированное предложение), но НЕ может писать/исполнять (нет Write/Edit/Bash/git) ->
    НЕ трогает FS/git/сеть, НЕ пушит, НЕ создаёт PR, НЕ меняет checkout, НЕ владеет исполнением/lifecycle.
    Модель ПРЕДЛАГАЕТ действия ТЕКСТОМ (JSON tool-loop); применяет их КИТ через свой sandbox/broker
    (scope-enforced, exact-SHA, gates, delivery) — это policy enforcement, не security isolation:
    брокер управляет операцией и областью записи, но сеть и ресурсы им не ограничены. AI Ops = control plane, Claude Code = сильный ЗАМЕНЯЕМЫЙ
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
    (парсинг `content[].text`/`error`), а не режется до 200 символов (F-011a — обрезка прятала «529 Overloaded»).

    Промпт передаётся ПОСЛЕДНИМ, после разделителя `--` (находка живого прогона на child-репозитории,
    2026-08-14). Промпты ролей — markdown с YAML-фронтматтером, то есть начинаются с `---`; в позиции
    до разделителя CLI разбирал их как ключ и падал с `unknown option '---…'` на КАЖДОЙ из 5 попыток.
    Ломалось не всё подряд: tool-loop строит промпт с текста, а run_workflow подаёт документ роли как
    есть — поэтому `--review`/`--author`/`--reevaluate-only` были недоступны с провайдером claude-cli,
    а обычный прогон работал. Разделитель снимает класс целиком: после `--` любой текст — позиционный
    аргумент, чем бы он ни начинался."""
    # ИСПОЛНЯЕМ ТЕМ ЖЕ, ЧТО ПРОВЕРЯЛИ (поле 13.08 и 15.08.2026, ИИ-Среда). Здесь стояло короткое имя
    # `claude`, а присутствие проверял `resolve_provider` через `which` — два разных решения, между
    # которыми помещалось расхождение PATH: прогон падал сырым `FileNotFoundError: 'claude'`, и по
    # нему нельзя было отличить «бинаря нет» от «бинарь не в PATH этого процесса». Теперь путь
    # вычисляется один раз и им же исполняется, а отсутствие — названная причина, не трейсбек.
    # Инъекция runner (офлайн-selftest) в бинаре не нуждается и имя не меняет: там запуска нет.
    binary = "claude"
    if runner is None:
        binary = claude_binary()
        if not binary:
            raise RuntimeError(claude_missing_message())
    cmd = [binary, "-p", "--output-format", "json",
           "--allowedTools", "Read", "Grep", "Glob"]
    if model:
        cmd += ["--model", model]
    cmd += ["--", prompt]
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
        # Узкий тип (срез providers, 2026-08-12): ожидаемый отказ — «это не JSON», и тогда отдаём
        # текст как есть. Любой другой тип здесь — дефект разбора, и он обязан всплыть.
        except (ValueError, TypeError):
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
        # 19.08.2026 (заявка #160): список стал ЕДИНСТВЕННЫМ основанием повторять, поэтому в нём
        # обязано быть и само слово. Сообщение, прямо называющее себя транзиентным, повторять
        # можно; поймано существующим селфтестом провайдеров, чей образец так и звучал.
        return any(s in t for s in ("overloaded", "529", "429", "rate limit", "rate_limit",
                                    "500", "502", "503", "504", "internal server error",
                                    "temporarily", "transient", "server_error",
                                    "timeout", "timed out", "connection"))

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
        # ЗАПУСК НЕ СОСТОЯЛСЯ — это НЕ транзиент и ретраить нечего: файл не появится от повтора.
        # Ловим здесь, а не только до цикла, потому что между проверкой и запуском проходит время
        # (обновление claude, смена PATH, съёмный диск), и владелец в этом случае получал трейсбек.
        except FileNotFoundError:
            raise RuntimeError(claude_missing_message(
                extra=f"путь был проверен и исчез до запуска: {cmd[0]}")) from None
        except OSError as exc:                # права, битый симлинк, не тот формат бинаря
            raise RuntimeError(
                f"`claude` найден ({cmd[0]}), но не запускается: {exc}. Проверьте права на файл "
                f"и что это исполняемый бинарь, а не обёртка оболочки (alias/function)."
            ) from None
        if r.returncode == 0:
            try:
                d = _json.loads(r.stdout)
            except (ValueError, TypeError):   # не JSON -> usage unavailable (НЕ теряем факт вызова)
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
        last = _human_error(r.stderr or r.stdout or "")
        # ПОВТОР ТОЛЬКО ТАМ, ГДЕ ОТКАЗ ТРАНЗИЕНТНЫЙ (заявка #160, 19.08.2026).
        #
        # Здесь стоял безусловный ретрай: при ЛЮБОМ ненулевом коде делалось пять попыток с
        # экспоненциальным backoff. Замер поля: `claude-cli` внутри активной сессии Claude Code не
        # работает СТРУКТУРНО — отказ детерминированный, и пятый повтор не делает систему
        # надёжнее, он делает её медленнее ровно в пять раз плюс сумма пауз (до ~60 секунд).
        #
        # ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ПЕРЕЙТИ: backoff на транзиентном 529 введён замером поля (F-011,
        # квалификация 3.27.7), и снимать его нельзя — иначе вернётся дефект, стоивший раунда
        # квалификации. Поэтому правка ОТЛИЧАЕТ ДВА КЛАССА, а не отменяет повтор: список
        # транзиентных признаков (`_transient`) остаётся единственным основанием повторять, и 529,
        # 429, 5xx, таймауты и сетевые сбои в нём есть.
        #
        # Тот же признак уже применялся к синтетическому конверту `is_error` выше — ветка rc!=0
        # просто осталась без него. Расхождение двух веток одного решения и есть дефект.
        if not _transient(last):
            raise RuntimeError(
                "claude -p отказал структурно (код %s), повтор не назначен — он не сделал бы "
                "систему надёжнее, только медленнее: %s" % (r.returncode, last))
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


def main(argv):
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
