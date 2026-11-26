"""Пассивное чтение квитанции хоста о выполнении работы автором и другой моделью.

Каталог принадлежит отдельному системному сборщику. Пользовательские настройки,
переменные среды и файлы рабочего дерева не выбирают доверенный источник.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


STORE = (Path("/private/var") if sys.platform == "darwin" else Path("/var")) / "lib/ai-ops/model-reviews"
LIMIT = 64 * 1024


def receipt_name(scope):
    raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest() + ".json"


def _trusted(info, path):
    if info.st_uid != 0 or info.st_mode & 0o022 or os.access(path, os.W_OK):
        raise ValueError("квитанция хоста доступна для изменения или её владелец не системный")


def _read_host_file(name):
    if os.name != "posix" or os.geteuid() == 0:
        raise ValueError("для чтения независимой квитанции нужен непривилегированный POSIX-процесс")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    prefix = Path("/")
    try:
        _trusted(os.fstat(directory), prefix)
        for component in STORE.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = following
            prefix /= component
            _trusted(os.fstat(directory), prefix)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(fd)
            _trusted(info, prefix / name)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
                raise ValueError("нужен обычный ограниченный файл квитанции хоста")
            raw = stream.read(LIMIT + 1)
            if len(raw) != info.st_size or os.fstat(fd).st_ctime_ns != info.st_ctime_ns:
                raise ValueError("квитанция хоста изменилась при чтении")
            return raw
    finally:
        os.close(directory)


def load(scope, *, expected_sha256=None):
    """Канонические id описывают выполненные turns; выбор модели до отправки недостаточен."""
    raw = _read_host_file(receipt_name(scope))
    checksum = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("изменилась квитанция хоста")
    try:
        data = json.loads(raw)
    except RecursionError:
        raise ValueError("слишком глубокая вложенность квитанции хоста") from None
    if (not isinstance(data, dict) or data.get("kind") != "observed-model-review"
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("gate") != "ai_red_team" or data.get("scope") != scope
            or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("verdict_sha256")))):
        raise ValueError("квитанция хоста не подтверждает проверяемую область и результат")
    writer, reviewer = data.get("writer"), data.get("reviewer")
    for actor in (writer, reviewer):
        if (not isinstance(actor, dict) or actor.get("execution") != "completed"
                or not isinstance(actor.get("session"), str) or not actor["session"].strip()
                or not isinstance(actor.get("turn"), str) or not actor["turn"].strip()
                or not isinstance(actor.get("canonical_model_id"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,127}", actor["canonical_model_id"])
                or actor["canonical_model_id"] in {"unknown", "default", "auto", "unavailable"}):
            raise ValueError("нет фактической канонической модели или завершённого хода участника")
    if (writer["session"] != scope["writer_session"] or writer["session"].casefold() == reviewer["session"].casefold()
            or writer["canonical_model_id"] == reviewer["canonical_model_id"]):
        raise ValueError("хост не подтвердил независимого судью другой модели")
    return data, checksum


def recheck(record):
    if "model_review_receipt" in record:
        receipt = record["model_review_receipt"]
        if not isinstance(receipt, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256"))):
            raise ValueError("неверная сохранённая привязка квитанции хоста")
        load(receipt["scope"], expected_sha256=receipt["sha256"])
