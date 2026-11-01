"""Подготовка отдельного native workspace и запрет инструментов внутренней текстовой роли."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from ai_ops_kit.providers.codex_transport import NativeError


def policy_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def prepare(root):
    if os.name != "posix":
        raise NativeError("native text provider пока поддерживает только POSIX process isolation")
    key = hashlib.sha256((str(Path(root).resolve()) + str(Path(__file__).resolve())
                          + policy_digest() + sys.executable).encode()).hexdigest()[:24]
    directory = Path(tempfile.gettempdir()) / ("ai-ops-codex-text-" + key)
    if directory.is_symlink():
        raise NativeError("native workspace не может быть symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    st = directory.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise NativeError("native workspace не принадлежит участнику или доступен другим пользователям")
    # macOS /var и /private/var (а также /tmp aliases) должны давать одну native identity.
    directory = directory.resolve()
    package = Path(__file__).resolve().parents[2]
    wrapper = ("import sys\ntry:\n"
               f"    sys.path.insert(0, {str(package)!r})\n"
               "    from pathlib import Path\n"
               "    from ai_ops_kit.cli.project_session import native_provider_hook\n"
               "    native_provider_hook(Path(__file__).parent)\n"
               "except BaseException:\n"
               "    sys.stderr.write('AI Ops native hook failed closed\\n')\n"
               "    raise SystemExit(2)\n")
    command = shlex.join([sys.executable, "-B", str(directory / "hook.py")])
    definitions = {"hooks": {e: [{"hooks": [{"type": "command", "command": command,
                       "timeout": 10}]}] for e in ("SessionStart", "PreToolUse")}}
    files = {"hook.py": wrapper, ".codex/hooks.json": json.dumps(definitions, ensure_ascii=False) + "\n",
             ".codex/config.toml": "# AI Ops isolated text-provider project; trust is set only by the user.\n",
             "AGENTS.md": "Внутренняя текстовая роль AI Ops. Верни только ответ роли; инструменты запрещены.\n"}
    if (directory / ".codex").is_symlink():
        raise NativeError("native config directory не может быть symlink")
    for relative, content in files.items():
        path = directory / relative
        if path.is_symlink() or (path.exists() and path.read_text() != content):
            raise NativeError("native workspace изменён; требуется проверка владельцем, перезаписи нет")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
    if (directory / ".git").is_symlink():
        raise NativeError("native .git не может быть symlink")
    if not (directory / ".git").exists():
        try:
            subprocess.run(["git", "init", "-q", str(directory)], check=True, capture_output=True, timeout=10)
        except subprocess.SubprocessError:
            raise NativeError("Git не смог подготовить изолированный native workspace") from None
    return directory, command


def denied(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def handle(directory, payload):
    """Нет копии auth, автоматического trust и разрешения инструментов."""
    event = payload.get("hook_event_name")
    if event == "SessionStart":
        context = json.loads((directory / "context.json").read_text())
        if context.get("policy") != policy_digest():
            return {"continue": False, "stopReason": "AI Ops native policy changed"}
        ack = dict(context, session_id=payload.get("session_id"))
        (directory / "ack.json").write_text(json.dumps(ack), encoding="utf-8")
        return {}
    if event == "PreToolUse":
        try:
            (directory / "tool-attempt").write_text("denied", encoding="utf-8")
        except OSError:
            return denied("AI Ops text provider: tools denied; diagnostic marker unavailable")
        return denied("AI Ops text provider: tools are forbidden")
    return denied("Unexpected native hook event; tools denied")


def main(directory=None):
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ValueError("native hook payload exceeds 256 KiB")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("native hook payload must be object")
    return handle(directory or Path.cwd(), payload)
