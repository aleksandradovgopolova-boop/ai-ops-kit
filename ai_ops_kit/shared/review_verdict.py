#!/usr/bin/env python3
"""Персистентный объект review-вердикта: «кто/что проверил функцию» как ЗАПИСЬ, а не эхо прогона.

ЗАЧЕМ. До сих пор «Проверено» существовало ТОЛЬКО в прогоне: `gate_executor.evidence_verdict` делит
пройденные гейты по источнику доверия (детерминированная машина / независимый ревьюер / человек), а
`shared.gate_dimensions` превращает их в уровни знания для readout (#985). Но как только прогон
заканчивался, вердикт исчезал — персистентного объекта не было, и нить «история жизни продукта» рвалась
на звене «фича → кто/что проверил» (замер PRODUCT-LIFE-HISTORY-CONTINUITY-2026-09-17, разрыв №4).
Привязать «проверку» к работе, которая функцию ПОСТРОИЛА, нельзя — это нарушило бы инвариант
писатель ≠ судья. Нужен отдельный объект, который пишет ПУТЬ РЕВЬЮ (независимый судья), а не писатель.

ЧТО ЭТО. Тонкий слой над УЖЕ существующим содержанием вердикта (веха 4.2, #588): запись НЕ вводит
новую модель проверки, а сохраняет `evidence_verdict` (какие гейты пройдены и КЕМ) рядом с фичей —
`features/<feature>/review/verdict.yaml`, — плюс когда и на какой ревизии. Knowledge Graph читает эту
запись и строит узел `review` + ребро `review -reviewed-> feature`; `graph trace` называет, кто проверил.

ЧЕСТНОСТЬ. Нет записи — нет узла и нет ребра: `graph trace` честно молчит «проверка не записана», а НЕ
объявляет пробел (проверки могло не быть — это не то же, что «должна была быть, но нет»). Ничего не
проверено (ни машиной, ни ревьюером, ни человеком) — `persist` НЕ пишет запись: пустой вердикт хуже
его отсутствия. Запись, ссылающаяся на несуществующую фичу, оставляет висящее ребро — и
`validate_knowledge_graph` отвергает граф целиком (сломанная запись обязана быть громкой).

Слой: `shared` (foundation) — как и `gate_dimensions`, которую переиспользует. Её вправе звать и
`engine` (путь ревью, пишет запись), и `intelligence` (Knowledge Graph, читает запись): оба импортят
ВНИЗ, инвариант слоёв не нарушен. Пишем/читаем обычный YAML — новой зависимости нет.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Mapping
import hashlib
import json
import os
import re
import stat
import sys
from typing import Any, NotRequired, TypedDict

import yaml

from ai_ops_kit.shared import gate_dimensions
from ai_ops_kit.shared.lifecycle_store import JsonDict


class CheckedBy(TypedDict):
    """Три существующих источника; элементы входных списков остаются открытой границей."""
    deterministic: list[Any]
    ai_judgment: list[Any]
    human: list[Any]


class ReviewVerdictRecord(TypedDict):
    """Статическая проекция build_record(), не валидация прочитанного YAML."""
    schema_version: int
    kind: str
    feature: str
    reviewed_revision: str | None
    reviewed_at: str
    verified: bool
    checked_by: CheckedBy
    reason: Any  # из открытого evidence_verdict, без проверки/нормализации
    outcome_verdict: NotRequired[str]


RECORD_KIND = "review-verdict"

# Источник доверия -> человеко-ярлык «кем проверено». Порядок = от машины к человеку (как в readout).
_SOURCE_LABELS = (
    ("deterministic", "машина"),
    ("ai_judgment", "независимый ревьюер"),
    ("human", "человек"),
)


def record_rel(feature: str) -> str:
    """Путь записи вердикта ОТНОСИТЕЛЬНО корня репозитория (рядом с паспортом функции)."""
    return f"features/{feature}/review/verdict.yaml"


def record_path(child_root: str | Path, feature: str) -> Path:
    return Path(child_root) / "features" / str(feature) / "review" / "verdict.yaml"


def _checked_by(evidence_verdict: Mapping[str, Any] | None) -> CheckedBy:
    """Три списка пройденных гейтов по источнику доверия — из `evidence_verdict` (веха 4.2, #588)."""
    ev = evidence_verdict or {}
    return {"deterministic": list(ev.get("deterministic") or []),
            "ai_judgment": list(ev.get("ai_judgment") or []),
            "human": list(ev.get("human") or [])}


def _anything_checked(checked_by: CheckedBy) -> bool:
    return any(checked_by.get(k) for k, _ in _SOURCE_LABELS)


def build_record(feature: str, evidence_verdict: Mapping[str, Any] | None, *, revision: str | None = None,
                 at: str | None = None, outcome_verdict: str | None = None) -> ReviewVerdictRecord:
    """Собрать запись review-вердикта из `evidence_verdict` — БЕЗ новой модели проверки.

    Содержание вердикта берётся как есть (какие гейты пройдены и КЕМ); запись лишь добавляет, к какой
    ФУНКЦИИ он относится, КОГДА и на какой РЕВИЗИИ вынесен. `at` по умолчанию — текущее UTC-время без
    микросекунд (без метки времени это не запись, а заметка — то же правило, что у BranchReview).
    """
    checked_by = _checked_by(evidence_verdict)
    ev = evidence_verdict or {}
    at = at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    record: ReviewVerdictRecord = {
        "schema_version": 1,
        "kind": RECORD_KIND,
        "feature": str(feature),
        "reviewed_revision": revision,
        "reviewed_at": at,
        "verified": bool(ev.get("verified")),
        "checked_by": checked_by,
        "reason": ev.get("reason"),
    }
    if outcome_verdict is not None:
        record["outcome_verdict"] = outcome_verdict
    return record


def persist(child_root: str | Path, feature: str, evidence_verdict: Mapping[str, Any] | None, *,
            revision: str | None = None, at: str | None = None,
            outcome_verdict: str | None = None) -> str | None:
    """Записать review-вердикт рядом с функцией. -> путь записи (относительный) или None.

    ЧЕСТНОСТЬ: если НИЧЕГО не проверено (ни машиной, ни ревьюером, ни человеком) — запись НЕ пишется и
    возвращается None: пустой вердикт населять историю не должен. Иначе пишется YAML в
    `features/<feature>/review/verdict.yaml` (перезаписывая прошлый — актуальна последняя проверка).
    Сбой записи не роняет вызывающего: возвращаем None, вердикт от наличия файла не зависит.
    """
    record = build_record(feature, evidence_verdict, revision=revision, at=at,
                          outcome_verdict=outcome_verdict)
    if not _anything_checked(record["checked_by"]):
        return None
    path = record_path(child_root, feature)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    except OSError:
        return None
    root = Path(child_root)
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def load(child_root: str | Path, feature: str) -> dict[Any, Any] | None:
    """Прочитать запись review-вердикта функции. -> dict или None (нет файла / нечитаемо)."""
    path = record_path(child_root, feature)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == RECORD_KIND else None


def checked_sources(record: Mapping[str, Any] | None) -> list[str]:
    """Человеко-ярлыки источников, которые РЕАЛЬНО что-то проверили: машина / ревьюер / человек."""
    cb = (record or {}).get("checked_by") or {}
    return [label for key, label in _SOURCE_LABELS if cb.get(key)]


def who_checked_lines(record: Mapping[str, Any] | None) -> list[str]:
    """«Кем и что проверено» продуктовыми словами -> список строк (переиспользует gate_dimensions).

    `checked_by` записи имеет ту же форму, что `evidence_verdict` ждёт `run_verified_lines`, поэтому
    смысл гейтов и атрибуция источника («мнение ≠ машинная проверка») берутся оттуда, а не дублируются.
    """
    return gate_dimensions.run_verified_lines((record or {}).get("checked_by") or {})


def node_title(record: Mapping[str, Any] | None) -> str:
    """Короткий заголовок узла review для графа: «проверили: машина, независимый ревьюер»."""
    sources = checked_sources(record)
    if not sources:
        return "проверка (без пройденных измерений)"
    return "проверили: " + ", ".join(sources)


# Квитанции выполненных модельных ходов доверенного хоста. Только чтение.
MODEL_RECEIPT_STORE = (Path("/private/var") if sys.platform == "darwin" else Path("/var")) / "lib/ai-ops/model-reviews"
MODEL_RECEIPT_LIMIT = 64 * 1024


def model_receipt_name(scope: dict[str, str]) -> str:
    raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest() + ".json"


def _require_host_owned(info: os.stat_result, path: Path) -> None:
    if info.st_uid != 0 or info.st_mode & 0o022 or os.access(path, os.W_OK):
        raise ValueError("квитанция хоста доступна для изменения или её владелец не системный")


def _read_host_file(name: str) -> bytes:
    if os.name != "posix" or os.geteuid() == 0:
        raise ValueError("для чтения независимой квитанции нужен непривилегированный POSIX-процесс")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    prefix = Path("/")
    try:
        _require_host_owned(os.fstat(directory), prefix)
        for component in MODEL_RECEIPT_STORE.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = following
            prefix /= component
            _require_host_owned(os.fstat(directory), prefix)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(fd)
            _require_host_owned(info, prefix / name)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MODEL_RECEIPT_LIMIT:
                raise ValueError("нужен обычный ограниченный файл квитанции хоста")
            raw = stream.read(MODEL_RECEIPT_LIMIT + 1)
            if len(raw) != info.st_size or os.fstat(fd).st_ctime_ns != info.st_ctime_ns:
                raise ValueError("квитанция хоста изменилась при чтении")
            return raw
    finally:
        os.close(directory)


def load_model_receipt(scope: dict[str, str], *, expected_sha256: str | None = None) -> tuple[JsonDict, str]:
    """Канонические id описывают выполненные turns; выбор модели до отправки недостаточен."""
    raw = _read_host_file(model_receipt_name(scope))
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


def recheck_model_receipt(record: JsonDict) -> None:
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
    host, _ = load_model_receipt(receipt["scope"], expected_sha256=receipt["sha256"])
    verdict = model_paths[0]
    request = verdict.with_name("ai_red_team.request.json")
    if (files[str(verdict)] != host["verdict_sha256"] or files.get(str(request)) != receipt["scope"].get("request_sha256")
            or any(files.get(path) != checksum for path, checksum in host["execution_artifacts"].items())):
        raise ValueError("квитанция хоста относится к другим проверенным файлам")


def recheck_model_completion(task: JsonDict, read_project_file: Callable[[str], bytes]) -> None:
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
    recheck_model_receipt(report)
