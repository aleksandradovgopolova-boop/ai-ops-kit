"""Opt-in текстовый provider Codex app-server; live qualification отдельно от offline тестов."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
import uuid

from ai_ops_kit.providers import codex_native_hook as hook
from ai_ops_kit.providers.codex_transport import NativeError, RPC
from ai_ops_kit.providers.orchestrator_usage import _record_call
from ai_ops_kit.providers.provider_errors import ProviderEnvUnavailableError
from ai_ops_kit.shared import lifecycle_store

NAME = "codex-app-server"
DISABLED = ("apps", "multi_agent", "remote_plugin", "shell_tool", "memories", "js_repl", "remote_control")


def command(binary, servers=()):
    args = [binary, "app-server", "--stdio", "-c", 'forced_login_method="chatgpt"',
            "-c", 'web_search="disabled"']
    for flag in DISABLED:
        args += ["--disable", flag]
    for name in servers:
        # Не интерполируем непроверенное имя в dotted TOML path.
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
            raise NativeError("имя унаследованного MCP нельзя безопасно переопределить")
        args += ["-c", f"mcp_servers.{name}.enabled=false"]
    return args


def connect(binary, directory, timeout, servers=()):
    rpc = RPC(command(binary, servers), directory, timeout)
    try:
        rpc.call("initialize", {"clientInfo": {"name": "ai_ops_text_provider", "version": "1"},
                                "capabilities": {}})
        rpc.send({"method": "initialized"})
        account = rpc.call("account/read", {"refreshToken": False}).get("account") or {}
        if account.get("type") != "chatgpt":
            raise NativeError("нужен существующий штатный вход Codex через ChatGPT; API fallback запрещён")
        config = rpc.call("config/read", {"includeLayers": False, "cwd": str(directory)}).get("config") or {}
        if any((config.get("features") or {}).get(k) is not False for k in DISABLED):
            raise NativeError("Codex не подтвердил отключение инструментальных features")
        if (config.get("features") or {}).get("hooks") is not True or config.get("web_search") != "disabled":
            raise NativeError("Codex не подтвердил hooks/web_search policy")
        active = [k for k, v in (config.get("mcp_servers") or {}).items() if v.get("enabled", True)]
        return rpc, active
    except BaseException:
        rpc.close()
        raise


def start(binary, directory, expected_command, timeout, prompt, model=None):
    deadline = time.monotonic() + timeout
    rpc, active = connect(binary, directory, timeout)
    if active:
        rpc.close()
        rpc, active = connect(binary, directory, max(0.001, deadline - time.monotonic()), active)
    try:
        if active:
            raise NativeError("унаследованные MCP остались активны; turn не запущен")
        listed = rpc.call("hooks/list", {"cwds": [str(directory)]}).get("data", [])
        entries = [e for e in listed if Path(e.get("cwd", "")).resolve() == directory.resolve()]
        events = set()
        for entry in entries:
            if entry.get("errors"):
                raise NativeError("Codex сообщил ошибки загрузки native hooks")
            for h in entry.get("hooks", []):
                if (Path(h.get("sourcePath", "")).resolve() == directory / ".codex/hooks.json"
                        and h.get("enabled") is True and h.get("trustStatus") in ("trusted", "managed")
                        and h.get("handlerType") == "command" and h.get("command") == expected_command
                        and h.get("currentHash") and h.get("matcher") in (None, "*")):
                    events.add(h.get("eventName"))
        if not {"sessionStart", "preToolUse"} <= events:
            raise NativeError(f"native project/hooks trust не подтверждён: {directory}; "
                              "открой этот workspace в Codex и согласуй только его project/hook definitions штатным способом")
        context = {"nonce": uuid.uuid4().hex, "policy": hook.policy_digest(),
                   "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        for name in ("ack.json", "context.json", "tool-attempt"):
            if (directory / name).is_symlink():
                raise NativeError("native control file не может быть symlink")
            (directory / name).unlink(missing_ok=True)
        (directory / "context.json").write_text(json.dumps(context))
        args = {"cwd": str(directory), "ephemeral": True, "approvalPolicy": "on-request",
                "sandbox": "read-only", "modelProvider": "openai"}
        if model is not None:
            args["model"] = model
        result = rpc.call("thread/start", args)
        thread = (result.get("thread") or {}).get("id")
        if (not thread or result.get("approvalPolicy") != "on-request"
                or result.get("sandbox") != {"type": "readOnly", "networkAccess": False}):
            raise NativeError("native thread не подтвердил readOnly/on-request")
        if not (directory / "ack.json").is_file():
            raise NativeError("SessionStart после thread/start не подтверждён; turn не запущен. "
                              "Проверь поддержку native lifecycle hooks в этой версии CLI")
        ack = json.loads((directory / "ack.json").read_text())
        if ack != dict(context, session_id=thread):
            raise NativeError("SessionStart не подтвердил текущую native session/policy; turn не запущен")
        selected = result.get("model")
        if not isinstance(selected, str) or not selected or (model is not None and selected != model):
            raise NativeError("Codex не подтвердил выбранную модель; подмена запрещена")
        cursor, catalog = None, []
        for _ in range(10):
            page = rpc.call("model/list", {"cursor": cursor})
            catalog += page.get("data", [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if cursor or not any(selected in (m.get("model"), m.get("id")) for m in catalog):
            raise NativeError("выбранная модель отсутствует в native model/list; выбери доступную модель до запуска")
        for event in rpc.pending:
            params = event.get("params") or {}
            if (params.get("turnId") is not None or params.get("threadId", thread) != thread
                    or event.get("method", "").startswith("item/") or event.get("method") == "error"):
                raise NativeError("неожиданное исполнение/чужая сессия до native turn")
        rpc.pending.clear()
        return rpc, thread, selected
    except BaseException:
        rpc.close()
        raise


def readiness(root, *, binary="codex", timeout=15):
    """Metadata only: ни одного turn/start и никакого доверия от имени участника."""
    try:
        directory, cmd = hook.prepare(root)
        with lifecycle_store._journal_lock(directory / "execution", required=True):
            rpc, _, _ = start(binary, directory, cmd, timeout, "")
            rpc.close()
        return {"ready": True, "provider": NAME, "workspace": str(directory)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"ready": False, "provider": NAME, "reason": str(exc),
                "next_step": "Устрани указанную готовность native Codex; затем продолжи сохранённую задачу. "
                             "Execution claim и модельная попытка не расходованы."}


def answer(rpc, thread, prompt, model, directory, observed):
    observed["attempted"] = True
    begun = rpc.call("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompt}],
                     "model": model, "approvalPolicy": "on-request",
                     "sandboxPolicy": {"type": "readOnly", "networkAccess": False}})
    turn = (begun.get("turn") or {}).get("id")
    observed["turn"] = turn
    if not turn:
        raise NativeError("native turn id отсутствует")
    texts, usage = {}, None
    while True:
        event = rpc.event()
        method, params = event.get("method", ""), event.get("params") or {}
        if ("id" in event or params.get("threadId", thread) != thread
                or (params.get("turnId") is not None and params["turnId"] != turn)):
            raise NativeError("событие принадлежит чужому native thread/turn")
        if (directory / "tool-attempt").exists() or method == "error":
            raise NativeError("native отказ/попытка инструмента; ответ не принят")
        if method in ("item/started", "item/completed"):
            if params.get("threadId") != thread or params.get("turnId") != turn:
                raise NativeError("native item не привязан к текущему thread/turn")
            item = params.get("item") or {}
            if item.get("type") not in ("agentMessage", "reasoning"):
                raise NativeError("native стадия попыталась использовать инструмент")
            if method == "item/completed" and item.get("type") == "agentMessage":
                texts[item["id"]] = item.get("text")
        if method == "thread/tokenUsage/updated":
            if params.get("turnId") != turn or not isinstance(params.get("tokenUsage"), dict):
                raise NativeError("native usage не привязан к текущему turn")
            # Новый ephemeral thread: total включает ВСЕ внутренние вызовы одного turn, не только last.
            usage = params["tokenUsage"].get("total")
            if usage is not None and not isinstance(usage, dict):
                raise NativeError("неверная форма native usage")
            observed["usage"] = usage
        if method == "turn/completed":
            done = params.get("turn") or {}
            if done.get("id") != turn or done.get("status") != "completed" or done.get("error"):
                raise NativeError("native turn не завершён успешно")
            break
    if not texts or any(not isinstance(x, str) or not x.strip() for x in texts.values()):
        raise NativeError("native ответ пуст или имеет неверную форму")
    return "\n".join(texts.values()), usage, turn


def _call(prompt, model, *, root=None, binary="codex", timeout=120):
    if ((model is not None and (not isinstance(model, str) or not model.strip())) or not isinstance(prompt, str)
            or not prompt.strip() or len(prompt.encode()) > 1024 * 1024
            or isinstance(timeout, bool) or not isinstance(timeout, (float, int))
            or not math.isfinite(timeout) or timeout <= 0):
        raise NativeError("native provider требует непустой bounded prompt, корректную model и конечный timeout")
    directory, cmd = hook.prepare(root or Path.cwd())
    started = time.monotonic()
    with lifecycle_store._journal_lock(directory / "execution", required=True):
        rpc, thread, selected = start(binary, directory, cmd, timeout, prompt, model)
        observed = {"outcome": "failed"}
        try:
            with rpc:
                text, usage, turn = answer(rpc, thread, prompt, selected, directory, observed)
            for key in ("inputTokens", "outputTokens"):
                value = (usage or {}).get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                    raise NativeError("native usage не является фактическим числом токенов")
            observed["outcome"] = "completed"
            return text
        finally:
            if observed.get("attempted"):
                usage = observed.get("usage") or {}
                values = [usage.get(k) for k in ("inputTokens", "outputTokens")]
                values = [v if type(v) is int and v >= 0 else None for v in values]
                rec = _record_call(selected, *values, time.monotonic() - started,
                                   provider=NAME, cost_status="unavailable")
                rec.update(native_thread_id=thread, native_turn_id=observed.get("turn"),
                           native_outcome=observed["outcome"])


def call(prompt, model=None, **options):
    try:
        return _call(prompt, model, **options)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ProviderEnvUnavailableError(NAME, str(exc)) from None
