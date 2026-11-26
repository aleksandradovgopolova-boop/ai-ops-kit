"""Пассивное чтение квитанции хоста о выполнении работы автором и другой моделью.

Каталог принадлежит отдельному системному сборщику. Пользовательские настройки,
переменные среды и файлы рабочего дерева не выбирают доверенный источник.
"""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from ai_ops_kit.shared.lifecycle_store import JsonDict


STORE = (Path("/private/var") if sys.platform == "darwin" else Path("/var")) / "lib/ai-ops/model-reviews"
LIMIT = 64 * 1024


def receipt_name(scope: dict[str, str]) -> str:
    raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest() + ".json"


def _trusted(info: os.stat_result, path: Path) -> None:
    if info.st_uid != 0 or info.st_mode & 0o022 or os.access(path, os.W_OK):
        raise ValueError("квитанция хоста доступна для изменения или её владелец не системный")


def _read_host_file(name: str) -> bytes:
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


def load(scope: dict[str, str], *, expected_sha256: str | None = None) -> tuple[JsonDict, str]:
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
    if not isinstance(writer, dict) or not isinstance(reviewer, dict):
        raise ValueError("нет записей выполненных ходов автора и судьи")
    for actor in (writer, reviewer):
        if (actor.get("execution") != "completed"
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


def recheck(record: JsonDict) -> None:
    """На reconcile/verify связать receipt с теми же проверенными файлами."""
    files = record.get("files", {})
    model_paths = [Path(path) for path in files if Path(path).parts[-3:] ==
                   (".ai", "reviewer-requests", "ai_red_team.model.reviewer.json")]
    if not model_paths and "model_review_receipt" not in record:
        return
    receipt = record.get("model_review_receipt")
    if (len(model_paths) != 1 or not isinstance(receipt, dict) or not isinstance(receipt.get("scope"), dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256")))):
        raise ValueError("нет полной сохранённой привязки квитанции хоста")
    host, _ = load(receipt["scope"], expected_sha256=receipt["sha256"])
    verdict = model_paths[0]
    request = verdict.with_name("ai_red_team.request.json")
    if (files[str(verdict)] != host["verdict_sha256"] or files.get(str(request)) != receipt["scope"].get("request_sha256")
            or any(files.get(path) != checksum for path, checksum in host["execution_artifacts"].items())):
        raise ValueError("квитанция хоста относится к другим проверенным файлам")


def recheck_completion(task: JsonDict, read_project_file: Callable[[str], bytes]) -> None:
    """Верификация принятой задачи использует закреплённый отчёт штатного finalize."""
    execution = task["execution"]
    if execution.get("mode") != "current-session":
        return
    verification = task.get("verification") or {}
    report_path = verification.get("report")
    if not report_path or execution["files"].get(report_path) != verification.get("sha256"):
        raise ValueError("нет подтверждённого отчёта приёмки текущей сессии")
    raw = read_project_file(report_path)
    if hashlib.sha256(raw).hexdigest() != verification.get("sha256"):
        raise ValueError("отчёт приёмки текущей сессии изменён")
    report = json.loads(raw)
    if (report.get("kind") != "current-session-verification" or report.get("ready_for_pr") is not True
            or report.get("request_id") != task["request_id"] or report.get("attempt") != verification.get("attempt")
            or report.get("scope") != verification.get("scope") or report.get("binding") != execution.get("completion_binding")):
        raise ValueError("исходный отчёт не подтверждает принятие этой попытки")
    host = report.get("model_review_receipt")
    judged = any(entry.get("source") == "host-model-red-team-artifact"
                 for entry in ((report.get("pipeline") or {}).get("reviews") or []))
    if judged != bool(host) or host != execution.get("model_review_receipt"):
        raise ValueError("привязка к заключению модели расходится с отчётом проверки")
    if host and any(execution["files"].get(path) != value for path, value in report["files"].items()):
        raise ValueError("проверенные машиной файлы расходятся с отчётом проверки")
    recheck(report)
