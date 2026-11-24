"""Ограниченный stdio JSON-RPC к официальному Codex app-server, без собственного agent loop."""
from __future__ import annotations

import json
import logging
import os
import selectors
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from typing import IO, Any

JsonDict = dict[str, Any]


class NativeError(ValueError):
    """Нет подтверждённого результата; автоматический retry/допуск запрещены."""


def _pipe(stream: IO[bytes] | None) -> IO[bytes]:
    # Popen с PIPE всегда отдаёт поток; None здесь означал бы несовместимый runtime.
    if stream is None:
        raise NativeError("Codex app-server запущен без stdio-канала")
    return stream


class RPC:
    def __init__(self, command: Sequence[str], cwd: str | os.PathLike[str], timeout: float = 120) -> None:
        self.deadline = time.monotonic() + timeout
        self.pending: list[JsonDict] = []
        self.buffer, self.number, self.received = b"", 0, 0
        self.stderr = tempfile.TemporaryFile()
        self.selector = selectors.DefaultSelector()
        self.writer = selectors.DefaultSelector()
        self.closed = False
        # Не переносим API keys, доступы инструментов и произвольные env-настройки модели.
        env = {k: v for k, v in os.environ.items() if k in (
            "HOME", "PATH", "TMPDIR", "LANG", "SYSTEMROOT", "CODEX_HOME",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE")}
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=self.stderr,
                                            start_new_session=True)
            self.selector.register(_pipe(self.process.stdout), selectors.EVENT_READ)
            os.set_blocking(_pipe(self.process.stdin).fileno(), False)
            self.writer.register(_pipe(self.process.stdin), selectors.EVENT_WRITE)
        except OSError:
            if hasattr(self, "process"):
                self.close()
            else:
                self.selector.close()
                self.writer.close()
                self.stderr.close()
            raise NativeError("Codex app-server не запустился; проверь установленный CLI") from None

    def send(self, message: JsonDict) -> None:
        try:
            remaining_data = memoryview((json.dumps(message, ensure_ascii=False) + "\n").encode())
            while remaining_data:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0 or not self.writer.select(remaining):
                    raise NativeError("таймаут записи в Codex app-server")
                try:
                    count = os.write(_pipe(self.process.stdin).fileno(), remaining_data)
                except BlockingIOError:
                    continue
                remaining_data = remaining_data[count:]
        except (BrokenPipeError, OSError):
            raise NativeError("Codex закрыл RPC до подтверждения результата") from None

    def receive(self) -> JsonDict:
        while b"\n" not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise NativeError("таймаут Codex app-server; автоматического повтора нет")
            chunk = os.read(_pipe(self.process.stdout).fileno(), 65536)
            if not chunk:
                raise NativeError("Codex app-server закрыл поток без подтверждения")
            self.received += len(chunk)
            self.buffer += chunk
            if self.received > 32 * 1024 * 1024 or len(self.buffer) > 2 * 1024 * 1024:
                raise NativeError("превышен бюджет RPC-потока Codex")
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError):
            raise NativeError("невалидный JSON в RPC Codex") from None
        if not isinstance(message, dict):
            raise NativeError("неверная форма RPC Codex")
        if "method" in message and "id" in message:
            # Запросы прав НЕ разрешаем, включая неизвестные будущие методы.
            method = message["method"]
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                self.send({"id": message["id"], "result": {"decision": "cancel"}})
            else:
                self.send({"id": message["id"], "error": {"code": -32601,
                          "message": "AI Ops text provider does not grant permissions or tools"}})
            raise NativeError("Codex запросил инструмент/разрешение; результат не принят")
        return message

    def call(self, method: str, params: JsonDict) -> JsonDict:
        self.number += 1
        current = self.number
        self.send({"id": current, "method": method, "params": params})
        while True:
            message = self.receive()
            if "id" not in message:
                self.pending.append(message)
                continue
            if message["id"] != current:
                raise NativeError("RPC ответ принадлежит другому запросу")
            result = message.get("result")
            if "error" in message or not isinstance(result, dict):
                raise NativeError(f"Codex отказал RPC {method}; проверь совместимость CLI/политику среды")
            return result

    def event(self) -> JsonDict:
        return self.pending.pop(0) if self.pending else self.receive()

    def group_alive(self) -> bool:
        # Darwin может вернуть EPERM для группы, в которой остались лишь zombies.
        # Это не разрешение игнорировать отказ для реально живой группы.
        try:
            result = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], text=True,
                                    capture_output=True, timeout=2, check=True)
        except (OSError, subprocess.SubprocessError):
            raise NativeError("не удалось проверить завершение собственной native process group") from None
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0] == str(self.process.pid) and not fields[1].startswith("Z"):
                return True
        return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            # Сигналим собственной группе ДО reaping leader: его PID ещё не может быть переиспользован.
            # Успешное завершение leader не означает, что закончились его потомки.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                logging.getLogger(__name__).debug("Native process group %s already exited", self.process.pid)
            except PermissionError:
                if self.group_alive():
                    raise NativeError("нет разрешения завершить собственную native process group") from None
            time.sleep(0.1)
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                logging.getLogger(__name__).debug("Native process group %s already exited", self.process.pid)
            except PermissionError:
                if self.group_alive():
                    raise NativeError("не удалось завершить живую собственную native process group") from None
            self.process.wait(timeout=3)
        finally:
            self.selector.close()
            self.writer.close()
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
            self.stderr.close()

    def __enter__(self) -> RPC:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
