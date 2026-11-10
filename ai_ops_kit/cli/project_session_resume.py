"""Внутренняя read-only проверка resume с конечным ожиданием, без provider/модели."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ai_ops_kit.lifecycle import project_session as sessions

TIMEOUT = 30
SNAPSHOT_LIMIT = 4 * 1024 * 1024


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
    if any(current.get(key) != task["binding"].get(key) for key in
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
