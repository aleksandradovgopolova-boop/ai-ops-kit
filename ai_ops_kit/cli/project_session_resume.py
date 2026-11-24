"""Внутренняя read-only проверка resume с конечным ожиданием, без provider/модели."""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
import subprocess
import sys
import tempfile

from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_prepared_update

TIMEOUT = 30
SNAPSHOT_LIMIT = 4 * 1024 * 1024


def unstarted_retry(root, payload, task, *, replay):
    """Связать только доказанный повтор с исходной незапущенной постановкой."""
    runtime, session = task["runtime"], task["session_id"]
    if (runtime != "codex" or task["status"] != "pending" or not task.get("turn_id") or not payload.get("turn_id")
            or task["prompt"] != payload["prompt"]
            or any(k in task for k in ("execution", "intake", "preparation", "provider_preparation", "state_migration", "verification"))):
        return False
    if not replay:  # replay уже сверил точные байты immutable input receipt
        rejected = rejected_turn(root, payload)
        expected = task.get("input_latest") or task["request_id"]
        if not rejected or sessions.digest(json.dumps([runtime, session, rejected]))[:32] != expected:
            return False
    sessions.pending(root, runtime, session)
    fid = "session-" + task["request_id"]
    for prefix in ("features", ".ai/runplan"):
        path = sessions.within(root, f"{prefix}/{fid}")
        if path.exists() or path.is_symlink():
            raise ValueError("обнаружены артефакты прежней попытки; повтор не подтверждён")
    sessions.artifact_inputs(root, fid)
    return True


def rejected_turn(root, payload):
    """Предыдущий turn_id только для отказа до ответа/инструментов в этой сессии."""
    session, turn, raw = (payload.get(k) for k in ("session_id", "turn_id", "transcript_path"))
    if not all(isinstance(s, str) and s for s in (session, turn, raw)):
        return None
    directory = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    path = Path(raw)
    try:
        rel = path.relative_to(directory)
        if (not path.is_absolute() or directory.is_relative_to(root) or len(rel.parts) != 4
                or not re.fullmatch(r"\d{4}/\d{2}/\d{2}/rollout-[\dT-]+-" + re.escape(session) + r"\.jsonl", rel.as_posix())
                or path.resolve(strict=True) != path):
            return None
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            limit = 2 * 1024 * 1024
            header = json.loads(stream.readline(limit))
            if header["type"] != "session_meta" or header["payload"]["id"] != session or header["payload"]["cwd"] != str(root):
                return None
            if info.st_size - stream.tell() > limit:
                stream.seek(-limit, os.SEEK_END)
                stream.readline(limit)  # only complete records from the tail
            data = stream.read(limit + 1)
        if len(data) > limit or not data.endswith(b"\n"):
            return None
        return _rejected_before_turn(data, turn)
    except (OSError, RuntimeError, ValueError, KeyError, AttributeError, TypeError, RecursionError):
        return None


def _rejected_before_turn(data, turn):
    previous = rejected = None
    current = False
    for line in data.splitlines():
        record = json.loads(line)
        kind, body = record["type"], record["payload"]
        event = body.get("type")
        if kind == "event_msg" and event == "task_started":
            if current:
                return None
            current = body["turn_id"] == turn
            if not current:
                previous, rejected = body["turn_id"], None
        elif kind == "event_msg" and event == "task_complete" and previous and body["turn_id"] == previous:
            error = json.loads((body.get("error") or {}).get("message") or "{}")
            if (body["last_agent_message"] is None and error.get("status") == 400
                    and (error.get("error") or {}).get("code") == "model_not_found"):
                rejected = previous
            previous = None
        elif kind in ("world_state", "turn_context") or (kind == "event_msg" and event == "user_message"):
            continue
        elif kind == "response_item" and event == "message" and body.get("role") in ("user", "developer"):
            continue
        else:
            previous = rejected = None
    return rejected


def _diagnostic(directory):
    path = directory / "process.stderr.log"
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 4096))
            return stream.read().decode("utf-8", errors="replace").strip()
    except OSError as exc:
        return "диагностика worker недоступна: " + type(exc).__name__


def validate(root, task, *, timeout=None):
    """Не менять state/claim: вернуть управление только по квитанции точного snapshot."""
    timeout = sessions._process_timeout(TIMEOUT if timeout is None else timeout)
    raw = json.dumps({"root": str(root), "task": task}, ensure_ascii=False).encode()
    if len(raw) > SNAPSHOT_LIMIT:
        raise ValueError("resume snapshot превышает 4 MiB; проверка не запущена")
    with tempfile.TemporaryDirectory(prefix="ai-ops-resume-") as temporary:
        directory = Path(temporary)
        payload = directory / "snapshot.json"
        payload.write_bytes(raw)
        kit = str(Path(sessions.__file__).resolve().parents[2])
        # Python >=3.12: -P убирает cwd из sys.path; только точный корень Kit
        # в PYTHONPATH. Продуктовые ai_ops_kit/yaml/sitecustomize не исполняются.
        env = dict(os.environ, PYTHONPATH=kit)
        command = [sys.executable, "-P", "-m", "ai_ops_kit.cli.project_session_resume", str(payload)]
        try:
            result = sessions.run_process(command, root, directory, timeout=timeout, env=env,
                progress=lambda text: print(text, file=sys.stderr, flush=True))
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"проверка resume превысила {timeout:g} с; " + _diagnostic(directory)) from exc
        except KeyboardInterrupt:
            print("AI Ops: resume отменён; " + _diagnostic(directory), file=sys.stderr, flush=True)
            raise
        except OSError as exc:
            raise ValueError("resume worker прерван; " + _diagnostic(directory)) from exc
        if result.returncode:
            raise ValueError("resume worker не подтвердил проверку: " + _diagnostic(directory))
        try:
            with (directory / "response.json").open("rb") as stream:
                response_raw = stream.read(SNAPSHOT_LIMIT + 1)
        except OSError as exc:
            raise ValueError("нет подтверждённого ответа resume worker") from exc
        if len(response_raw) > SNAPSHOT_LIMIT:
            raise ValueError("ответ resume worker превышает 4 MiB")
        expected = {"request_id": task["request_id"], "snapshot_sha256": sessions.digest(raw),
                    "response_sha256": sessions.digest(response_raw)}
        if json.loads(result.stdout) != expected:
            raise ValueError("квитанция resume не соответствует snapshot задачи")
        response = json.loads(response_raw)
        if (not isinstance(response, dict) or set(response) - set(task) - {"host_actions"}
                or not set(task) <= set(response)
                or json.dumps({k: response[k] for k in task}, sort_keys=True) != json.dumps(task, sort_keys=True)):
            raise ValueError("ответ resume изменил исходную задачу")
        return response


def check(root, task, *, before_read=None):
    """Прежний inline validator: callbacks hooks не должны порождать 30s worker."""
    current = sessions.binding(root, "session-" + task["request_id"], before_read=before_read)
    expected = session_prepared_update.runtime_binding(root, task)
    if any(current.get(key) != expected.get(key) for key in
           ("root", "branch", "version", "managed_sha256", "config_sha256")):
        raise ValueError("контекст проектной сессии изменился; проверь сохранённую работу")
    for relative, checksum in task["execution"]["files"].items():
        if before_read:
            before_read(root / relative)
        if sessions.digest(sessions.within(root, relative).read_bytes()) != checksum:
            raise ValueError("подготовленный артефакт изменён: " + relative)


def worker(snapshot):
    """Выполнить прежние проверки целиком, не приобретая locks родителя."""
    raw = Path(snapshot).read_bytes()
    if len(raw) > SNAPSHOT_LIMIT:
        raise ValueError("resume snapshot превышает 4 MiB")
    payload = json.loads(raw)
    root, task = Path(payload["root"]).resolve(), payload["task"]

    def reading(path):
        relative = Path(path).relative_to(root).as_posix()
        print("AI Ops resume read: " + json.dumps(relative, ensure_ascii=False), file=sys.stderr, flush=True)

    check(root, task, before_read=reading)
    from ai_ops_kit.cli import project_session_completion
    response = project_session_completion.response(root, task, before_read=reading)
    response_raw = json.dumps(response, ensure_ascii=False).encode()
    if len(response_raw) > SNAPSHOT_LIMIT:
        raise ValueError("ответ resume worker превышает 4 MiB")
    Path(snapshot).with_name("response.json").write_bytes(response_raw)
    print(json.dumps({"request_id": task["request_id"], "snapshot_sha256": sessions.digest(raw),
                      "response_sha256": sessions.digest(response_raw)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(worker(sys.argv[1]))
