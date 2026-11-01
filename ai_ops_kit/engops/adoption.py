"""Добровольный локальный учёт adoption. Сеть отсутствует; внешние записи недоверенные.

UUID в истории проекта объединяет клоны/ветки. Решение владельца и даты активности
живут в git-common и не наследуются клоном. См. docs/architecture/adoption-opt-in.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from ai_ops_kit.shared.gitio import git
from ai_ops_kit.shared.lifecycle_store import durable_write_json, _journal_lock

CAPABILITIES = {"network": False, "sends": False}
IDENTITY = ".ai/project/adoption-id.json"
RELATIONSHIPS = ("owned", "external", "unknown")
MAX_BYTES = 65536
EVIDENCE_META_BYTES = 1024 * 1024
EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
EVIDENCE_TOTAL_BYTES = 64 * 1024 * 1024
EVIDENCE_MAX_FILES = 4096


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("некорректный UUID")
    return value


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("нужна дата YYYY-MM-DD")
    return value


def _window(start, end):
    if _day(start) > _day(end) or end > _today():
        raise ValueError("период должен завершаться не позже сегодня и начинаться до завершения")
    return {"start": start, "end": end}


def reporting_window(start=None, end=None):
    """Обе даты явные или последние 30 дат UTC, включая текущий неполный день."""
    if start is None and end is None:
        end = _today()
        start = (date.fromisoformat(end) - timedelta(days=29)).isoformat()
    elif start is None or end is None:
        raise ValueError("задайте обе даты периода или не задавайте ни одной")
    return _window(start, end)


def _evidence_path(root, relative, limit):
    """Только обычный ограниченный файл внутри явно выбранного root, без ссылок."""
    rel = PurePosixPath(relative)
    if (not relative or rel.is_absolute() or rel.as_posix() != relative
            or any(p in (".", "..") for p in rel.parts) or "\\" in relative or ":" in relative):
        raise ValueError("unsafe_evidence_path")
    path = Path(root).resolve()
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("unsafe_evidence_path")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError("unsafe_evidence_file")
    return path


def _evidence_bytes(root, relative, limit):
    path = _evidence_path(root, relative, limit)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("evidence_file_grew_over_limit")
    return raw


def _evidence_json(root, relative):
    data = json.loads(_evidence_bytes(root, relative, EVIDENCE_META_BYTES))
    if not isinstance(data, dict):
        raise ValueError("invalid_evidence_object")
    return data


def _evidence_version(value):
    return isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", value) is not None


def _managed_integrity(root, manifest):
    files = manifest.get("files")
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("algorithm") != "sha256" or manifest.get("managed_root") != "managed"
            or not isinstance(files, dict) or not 0 < len(files) <= EVIDENCE_MAX_FILES or "VERSION" not in files):
        raise ValueError("invalid_checksum_manifest")
    actual, total = set(), 0
    managed = Path(root).resolve() / ".ai/managed"
    for index, path in enumerate(managed.rglob("*")):
        if index > EVIDENCE_MAX_FILES * 4 or path.is_symlink():
            raise ValueError("unsafe_managed_inventory")
        rel = path.relative_to(managed)
        if "__pycache__" in rel.parts or path.suffix in (".pyc", ".pyo"):
            continue  # артефакты интерпретатора, как в штатном checksum-валидаторе
        if path.is_dir() or path.name in (".checksums.json", ".provenance.json", ".update-lock", ".gitkeep"):
            continue
        actual.add(rel.as_posix())
        if len(actual) > EVIDENCE_MAX_FILES:
            raise ValueError("managed_inventory_limit")
    if actual != set(files):
        raise ValueError("incomplete_or_drifted_inventory")
    for rel, expected in files.items():
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("invalid_checksum")
        path = _evidence_path(root, f".ai/managed/{rel}", EVIDENCE_FILE_BYTES)
        if total + path.stat().st_size > EVIDENCE_TOTAL_BYTES:
            raise ValueError("managed_bytes_limit")
        digest = hashlib.sha256()
        read_bytes = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                read_bytes += len(chunk)
                total += len(chunk)
                if read_bytes > EVIDENCE_FILE_BYTES or total > EVIDENCE_TOTAL_BYTES:
                    raise ValueError("managed_file_grew_over_limit")
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("managed_content_drift")
    return len(files)


def _installation_evidence(root):
    try:
        version = _evidence_bytes(root, ".ai/managed/VERSION", 256).decode("utf-8").strip()
        prov = _evidence_json(root, ".ai/managed/.provenance.json")
        if (not _evidence_version(version) or type(prov.get("schema_version")) is not int
                or prov["schema_version"] != 1 or prov.get("package") != "ai-first-system"
                or prov.get("installed_version") != version or prov.get("managed_root") != ".ai/managed"
                or prov.get("checksums_file") != ".checksums.json"):
            raise ValueError("inconsistent_provenance")
        count = _managed_integrity(root, _evidence_json(root, ".ai/managed/.checksums.json"))
        return {"state": "locally_consistent", "version": version, "checked_files": count,
                "source_authentication": "unknown", "source_at": None,
                "reason": "checksums_do_not_authenticate_source"}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {"state": "unknown", "reason": "installation_evidence_missing_invalid_or_drifted"}


def _update_evidence(root, installation):
    if installation["state"] != "locally_consistent":
        return {"state": "unknown", "updated_in_window": "unknown", "reason": "installation_not_corroborated"}
    try:
        rep = _evidence_json(root, ".ai/runtime/last-update-report.json")
        smoke = rep.get("smoke_tests")
        if (type(rep.get("schema_version")) is not int or rep["schema_version"] != 1
                or rep.get("command") != "update" or rep.get("status") != "ok"
                or not _evidence_version(rep.get("from_version"))
                or rep.get("from_version") == rep.get("to_version")
                or rep.get("to_version") != installation["version"]
                or ("applied_in_place" in rep and rep["applied_in_place"] is not True)
                or "deferred_to_branch" in rep
                or not isinstance(smoke, list) or not smoke
                or any(not isinstance(s, dict) or s.get("status") != "pass"
                       or not isinstance(s.get("check"), str) or not s["check"].strip() for s in smoke)):
            raise ValueError("update_not_corroborated")
        return {"state": "local_report_consistent", "from_version": rep["from_version"],
                "to_version": rep["to_version"], "source_at": None, "updated_in_window": "unknown",
                "reason": "undated_local_report_is_not_authenticated_transition"}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {"state": "unknown", "updated_in_window": "unknown", "reason": "update_evidence_missing_or_invalid"}


def local_evidence(root, start, end):
    """Read-only диагностика уже разрешённого проекта; ничего не экспортирует/не подтверждает заочно."""
    window = _window(start, end)
    state = _state(root)
    result = {"schema_version": 1, "kind": "AdoptionLocalEvidence", "window": window,
              "network": False, "writes": False, "consent": (state or {}).get("consent", "disabled")}
    if not state or state["consent"] != "granted":
        return dict(result, inspection="not_permitted", reason="active_project_consent_required")
    _evidence_path(root, IDENTITY, MAX_BYTES)
    if identity(root) != state["project_id"]:
        raise ValueError("ID проекта изменился")
    installed = _installation_evidence(root)
    return dict(result, inspection="local_only", installation=installed,
                update=_update_evidence(root, installed),
                activity={"observed_dates_in_window": len({d for d in state["days"] if start <= d <= end}),
                          "source": "unattributed_local_dates", "verified_product_active": "unknown",
                          "reason": "dates_or_manual_records_do_not_bind_product_evidence"},
                imported_receipts_used=False, world_total_state="unknown")


def _read(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_BYTES:
        raise ValueError("небезопасный файл учёта")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("учёт должен быть объектом")
    return data


def _write(path, data):
    if path.is_symlink():
        raise ValueError("символьная ссылка вместо файла учёта")
    result = durable_write_json(path, data)
    if not result.get("ok"):
        raise ValueError("не удалось надёжно сохранить учёт")


def _store(root):
    rc, out, _ = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc or not out:
        raise ValueError("нужен git-репозиторий")
    return Path(out) / "ai-ops" / "adoption"


def identity(root, *, create=False):
    """Создание ID не включает учёт. Для использования нужен ID в HEAD без локальной подмены."""
    path = Path(root) / IDENTITY
    if not path.exists():
        if not create:
            raise ValueError("сначала создайте и сохраните ID проекта в git")
        _write(path, {"schema_version": 1, "project_id": str(uuid.uuid4())})
    doc = _read(path)
    if set(doc) != {"schema_version", "project_id"} or doc["schema_version"] != 1:
        raise ValueError("неверный формат ID проекта")
    pid = _uuid(doc["project_id"])
    if not create:
        rc, raw, _ = git(root, "show", f"HEAD:{IDENTITY}")
        if rc or json.loads(raw) != doc:
            raise ValueError("ID проекта должен быть сохранён в HEAD без локальной подмены")
    return pid


def _state(root):
    path = _store(root) / "consent.json"
    if not path.exists():
        return None
    doc = _read(path)
    if set(doc) != {"project_id", "consent_id", "consent", "days"}:
        raise ValueError("повреждено согласие")
    _uuid(doc["project_id"])
    _uuid(doc["consent_id"])
    if doc["consent"] not in ("granted", "revoked") or not isinstance(doc["days"], list):
        raise ValueError("повреждено согласие")
    if any(_day(day) > _today() for day in doc["days"]):
        raise ValueError("активность из будущего")
    return doc


def consent(root, *, owner=False, revoke=False):
    if not owner:
        raise ValueError("нужно явное решение владельца этого проекта (--owner)")
    path = _store(root) / "consent.json"
    with _journal_lock(path, required=True):
        old = _state(root)
        # Отзыв возможен даже на ветке без ID или после его повреждения.
        if revoke:
            if old is None:
                return {"consent": "disabled"}
            doc = dict(old, consent="revoked", days=[])
        else:
            pid = identity(root)
            if old and old["consent"] == "granted" and old["project_id"] != pid:
                raise ValueError("сначала отзовите прежнюю идентичность проекта")
            doc = old if old and old["consent"] == "granted" else {
                "project_id": pid, "consent_id": str(uuid.uuid4()), "consent": "granted", "days": []}
        _write(path, doc)
    return {k: v for k, v in doc.items() if k != "days"}


def status(root):
    state = _state(root)
    return {"consent": (state or {}).get("consent", "disabled"), "network": False,
            "project_id": (state or {}).get("project_id"),
            "observation_scope": "pipeline run_completed after consent; other runtimes unknown"}


def _event_day(value):
    """Время источника, не дата доставки. Без времени свежесть не доказана."""
    if not isinstance(value, str):
        raise ValueError("нужно время события")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("нужен часовой пояс события")
    stamp = stamp.astimezone(timezone.utc)
    day = stamp.date().isoformat()
    if stamp > datetime.now(timezone.utc) or day != _today():
        raise ValueError("свежесть события не подтверждена")
    return day


def observe_completed(data):
    """Подписчик ядра. Не хранит task/model/provider/путь; максимум одна дата за день.

    Доверяет локальному процессу ядра, НЕ импортируемому JSON. Изолированная подделка
    локального процесса/FS не покрыта этой моделью доверия; внешние receipts никогда не verified.
    """
    root = data.get("child_root")
    rep = data.get("report")
    if not root or not isinstance(rep, dict):
        return
    try:
        state = _state(root)
        if not state or state["consent"] != "granted":
            return
        path = _store(root) / "consent.json"
        with _journal_lock(path, required=True):
            state = _state(root)
            if not state or state["consent"] != "granted":
                return
            if identity(root) != state["project_id"]:
                raise ValueError("ID проекта изменился")
            # Завершённый pipeline с фактическими вызовами; preview/blocked-before-call не активность.
            cost = rep.get("cost")
            if not isinstance(cost, dict):
                return
            calls = cost.get("calls")
            if rep.get("kind") != "execution-pipeline" or rep.get("provider") in (None, "mock"):
                return
            if type(calls) is not int or calls <= 0:
                return
            day = _event_day(data.get("timestamp"))
            if day not in state["days"]:
                state["days"] = sorted(set(state["days"]) | {day})[-366:]
                _write(path, state)
        rep["adoption_observation"] = "recorded_locally"
    except (OSError, ValueError, TypeError, RuntimeError, OverflowError):
        rep["adoption_observation"] = "unavailable"


def snapshot(root, start, end):
    window = _window(start, end)
    state = _state(root)
    if not state:
        raise ValueError("владелец проекта не включал учёт")
    granted = state["consent"] == "granted"
    if granted and identity(root) != state["project_id"]:
        raise ValueError("ID проекта изменился")
    installed = "unknown"
    version = Path(root) / ".ai/managed/VERSION"
    if granted and version.is_file() and not version.is_symlink():
        if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version.read_text().strip()):
            installed = "observed"
    active = granted and any(start <= day <= end for day in state["days"])
    return {"schema_version": 1, "kind": "AdoptionReceipt", "project_id": state["project_id"],
            "consent_id": state["consent_id"], "consent": state["consent"], "observed_on": _today(),
            "installation": installed, "activity": "observed" if active else "unknown", "window": window}


def _checksum(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def export(root, start, end, output):
    doc = snapshot(root, start, end)
    doc["checksum"] = _checksum(doc)
    # Не позволяем экспортом уничтожить identity/consent и другие существующие файлы.
    with Path(output).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return doc


def validate_receipt(doc):
    keys = {"schema_version", "kind", "project_id", "consent_id", "consent", "observed_on",
            "installation", "activity", "window", "checksum"}
    if set(doc) != keys or type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("неподдерживаемая запись или лишние поля")
    if doc["kind"] != "AdoptionReceipt":
        raise ValueError("не AdoptionReceipt")
    _uuid(doc["project_id"])
    _uuid(doc["consent_id"])
    if _day(doc["observed_on"]) > _today():
        raise ValueError("наблюдение из будущего")
    if not isinstance(doc["window"], dict) or set(doc["window"]) != {"start", "end"}:
        raise ValueError("неверный период")
    _window(**doc["window"])
    if doc["window"]["end"] > doc["observed_on"]:
        raise ValueError("период позже наблюдения")
    if doc["consent"] not in ("granted", "revoked"):
        raise ValueError("нет решения о согласии")
    if any(doc[k] not in ("observed", "unknown") for k in ("installation", "activity")):
        raise ValueError("неверный уровень наблюдения")
    if doc["consent"] == "revoked" and any(doc[k] != "unknown" for k in ("installation", "activity")):
        raise ValueError("отзыв не должен нести активность")
    body = {k: v for k, v in doc.items() if k != "checksum"}
    if doc["checksum"] != _checksum(body):
        raise ValueError("нарушена целостность; checksum не является подписью")
    return doc


def import_receipt(root, source, relationship="unknown"):
    if relationship not in RELATIONSHIPS:
        raise ValueError("неверная принадлежность проекта")
    doc = validate_receipt(_read(Path(source)))
    key = f"{doc['project_id']}-{doc['consent_id']}"
    directory = _store(root) / "imports"
    tombstone = directory / f"{key}.revoked.json"
    suffix = "revoked" if doc["consent"] == "revoked" else f"{doc['window']['start']}-{doc['window']['end']}"
    path = directory / f"{key}.{suffix}.json"
    # Один lock на consent_id сериализует все окна и отзыв.
    with _journal_lock(directory / key, required=True):
        if tombstone.exists():
            old = _read(tombstone)
            validate_receipt(old["receipt"])
            if old["receipt"]["consent"] != "revoked":
                raise ValueError("повреждён отзыв")
            return {"trust": "self_reported", "state": "revoked"}
        if path.exists():
            old = _read(path)
            validate_receipt(old["receipt"])
            # Tombstone терминален для этого consent_id; regrant создаёт новый consent_id.
            if old["receipt"]["consent"] == "revoked":
                return {"trust": "self_reported", "state": "revoked"}
            if old["receipt"]["observed_on"] > doc["observed_on"]:
                raise ValueError("устаревшая запись")
        _write(path, {"receipt": doc, "relationship": relationship})
    return {"trust": "self_reported", "state": doc["consent"]}


def report(root, start, end, projects=()):
    window = _window(start, end)
    local, remote, errors = {}, {}, []
    seen_local = set()
    for project, relation in projects:
        if relation not in RELATIONSHIPS:
            raise ValueError("неверная принадлежность проекта")
        try:
            doc = snapshot(project, start, end)
            pid = doc["project_id"]
            seen_local.add(pid)
            if doc["consent"] != "granted":
                continue
            row = local.setdefault(pid, {"installation": False, "activity": False, "relations": set()})
            row["relations"].add(relation)
            for field in ("installation", "activity"):
                row[field] |= doc[field] == "observed"
        except (OSError, ValueError, TypeError, KeyError):
            errors.append("local_observation_unavailable")
    imported, revoked = [], set()
    for path in sorted((_store(root) / "imports").glob("*.json")):
        try:
            record = _read(path)
            if set(record) != {"receipt", "relationship"} or record["relationship"] not in RELATIONSHIPS:
                raise ValueError("неверная запись импорта")
            doc = validate_receipt(record["receipt"])
            imported.append((doc, record["relationship"]))
            if doc["consent"] == "revoked":
                revoked.add((doc["project_id"], doc["consent_id"]))
        except (OSError, ValueError, TypeError, KeyError):
            errors.append("import_unavailable")
    for doc, relationship in imported:
        if doc["project_id"] in seen_local or (doc["project_id"], doc["consent_id"]) in revoked:
            continue
        row = remote.setdefault(doc["project_id"], {"installation": False, "activity": False, "relations": set()})
        row["relations"].add(relationship)
        row["installation"] |= doc["installation"] == "observed"
        row["activity"] |= doc["activity"] == "observed" and doc["window"] == window
    def counts(rows):
        out = {r: {"projects": 0, "installed": 0, "active": 0} for r in RELATIONSHIPS}
        for row in rows.values():
            relation = next(iter(row["relations"])) if len(row["relations"]) == 1 else "unknown"
            out[relation]["projects"] += 1
            out[relation]["installed"] += int(row["installation"])
            out[relation]["active"] += int(row["activity"])
        return out
    return {"schema_version": 1, "window": window, "world_total": None, "world_total_state": "unknown",
            "observed_on": _today(), "observation_completeness": "partial",
            "coverage": {"local_inspected": len(projects), "local_registered_unique": len(local),
                         "imported_unverified_unique": len(remote)},
            "local_observed": counts(local),
            "external_self_reported_unverified": counts(remote), "errors": errors,
            "evidence": "local trusted filesystem + run_completed; imported checksums are not authentication",
            "activity_absence": "unknown; only pipeline completions with model calls after consent, last 366 dates"}
