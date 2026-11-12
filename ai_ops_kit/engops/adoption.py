"""Добровольный локальный учёт adoption. Сеть отсутствует; внешние записи недоверенные.

UUID в истории проекта объединяет клоны/ветки. Решение владельца и даты активности
живут в git-common и не наследуются клоном. См. docs/architecture/adoption-opt-in.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from ai_ops_kit.engops.adoption_evidence import (
    EVIDENCE_MAX_FILES, _checksum, _evidence_bytes, _evidence_path, _evidence_version,
    _installation_evidence, _update_evidence,
)
from ai_ops_kit.shared.gitio import git as _run_git
from ai_ops_kit.shared.lifecycle_store import durable_write_json, _journal_lock

CAPABILITIES = {"network": False, "sends": False}
IDENTITY = ".ai/project/adoption-id.json"
RELATIONSHIPS = ("owned", "external", "unknown")
MAX_BYTES = 65536



def git(root, *args):
    # Даже promisor/partial clone не имеет права догружать недостающий объект.
    env = {k: v for k, v in os.environ.items() if k not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_GRAFT_FILE"}}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_NO_REPLACE_OBJECTS="1",
               GIT_GRAFT_FILE=os.devnull)
    return _run_git(root, "--literal-pathspecs", *args, timeout=10, env=env)

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



def _revocation_path(root, pid, cid):
    return _store(root) / "revocations" / f"{pid}-{cid}.json"


def _revoked_here(store, pid, cid):
    try:
        record = _read(store / "revocations" / f"{pid}-{cid}.json")
    except FileNotFoundError:
        return False
    if record != {"project_id": pid, "consent_id": cid}:
        raise ValueError("повреждён локальный отзыв")
    return True


def _remember_revocation(root, state):
    pid, cid = state["project_id"], state["consent_id"]
    _write(_revocation_path(root, pid, cid), {"project_id": pid, "consent_id": cid})

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
    if doc["consent"] == "granted" and _revoked_here(path.parent, doc["project_id"], doc["consent_id"]):
        return dict(doc, consent="revoked", days=[])
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
            _remember_revocation(root, old)
            doc = dict(old, consent="revoked", days=[])
        else:
            pid = identity(root)
            if old and old["consent"] == "revoked":
                _remember_revocation(root, old)  # legacy state может не иметь долговечного отзыва
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
    if granted:
        try:
            if _evidence_version(_evidence_bytes(root, ".ai/managed/VERSION", 256).decode().strip()):
                installed = "observed"
        except (OSError, ValueError):
            installed = "unknown"
    active = granted and any(start <= day <= end for day in state["days"])
    return {"schema_version": 1, "kind": "AdoptionReceipt", "project_id": state["project_id"],
            "consent_id": state["consent_id"], "consent": state["consent"], "observed_on": _today(),
            "installation": installed, "activity": "observed" if active else "unknown", "window": window}


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


def report(root, start, end, projects=(), *, verification=None):
    window = _window(start, end)
    local, remote, errors = {}, {}, []
    candidates = {}
    parent_seen = False
    seen_local = set()
    for project, relation in projects:
        if relation not in RELATIONSHIPS:
            raise ValueError("неверная принадлежность проекта")
        if _is_parent(project):
            parent_seen = True
            continue
        try:
            doc = snapshot(project, start, end)
            pid = doc["project_id"]
            seen_local.add(pid)
            candidates.setdefault(pid, []).append((project, relation, doc))
        except (OSError, ValueError, TypeError, KeyError):
            errors.append("local_observation_unavailable")
    imported = []
    revoked = {(pid, d["consent_id"]) for pid, copies in candidates.items() for _, _, d in copies
               if d["consent"] == "revoked"}
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
    keys = {(pid, d["consent_id"]) for pid, copies in candidates.items() for _, _, d in copies}
    keys.update((doc["project_id"], doc["consent_id"]) for doc, _ in imported)
    stores = {_store(root)}
    for project, _ in projects:
        try:
            stores.add(_store(project))
        except (OSError, ValueError):
            continue  # недоступный checkout уже отражён в coverage/errors
    for store in sorted(stores):
        for pid, cid in sorted(keys - revoked):
            try:
                if _revoked_here(store, pid, cid):
                    revoked.add((pid, cid))
            except (OSError, ValueError, TypeError, KeyError):
                revoked.add((pid, cid))
                errors.append("local_revocations_unavailable")
    for pid, copies in candidates.items():
        for _, relation, doc in copies:
            if doc["consent"] != "granted" or (pid, doc["consent_id"]) in revoked:
                continue
            row = local.setdefault(pid, {"installation": False, "activity": False, "relations": set()})
            row["relations"].add(relation)
            for field in ("installation", "activity"):
                row[field] |= doc[field] == "observed"
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
            "verified_adoption": _verified_report(candidates, verification or {}, revoked, window, len(projects), len(remote), parent_seen),
            "external_self_reported_unverified": counts(remote), "errors": errors,
            "evidence": "local trusted filesystem + run_completed; imported checksums are not authentication",
            "activity_absence": "unknown; only pipeline completions with model calls after consent, last 366 dates"}


def load_verification(path, digest):
    """Читаем закреплённую независимую квитанцию, НЕ импорт project receipt."""
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("нужен доверенный SHA256 квитанции проверки")
    path = Path(path)
    raw = _evidence_bytes(path.parent, path.name, MAX_BYTES)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("квитанция не совпадает с доверенным SHA256")
    doc = json.loads(raw)
    if (not isinstance(doc, dict) or set(doc) != {"schema_version", "projects"}
            or type(doc["schema_version"]) is not int or doc["schema_version"] != 1
            or not isinstance(doc["projects"], dict)):
        raise ValueError("неверная форма квитанции проверки")
    for pid, row in doc["projects"].items():
        _uuid(pid)
        if (not isinstance(row, dict) or not {"kind", "relationship", "identity_commit", "observed_on", "consent_ids"} <= row.keys()
                or row.keys() - {"kind", "relationship", "identity_commit", "observed_on", "consent_ids", "installation", "activity", "update"}
                or row["kind"] not in ("product", "fixture", "parent")
                or row["relationship"] not in RELATIONSHIPS or _day(row["observed_on"]) > _today()):
            raise ValueError("неверная запись независимой проверки")
        _oid(row["identity_commit"])
        ids = row["consent_ids"]
        if not isinstance(ids, list) or not 0 < len(ids) <= 64:
            raise ValueError("укажите согласия, связанные с проверкой")
        for cid in ids:
            _uuid(cid)
        for name, keys in (("installation", {"commit", "version", "release_commit", "inventory_sha256"}),
                           ("activity", {"commit", "path"}), ("update", {"commit", "from_version", "from_tree_sha256"})):
            if name not in row:
                continue
            proof = row[name]
            if not isinstance(proof, dict) or set(proof) != keys:
                raise ValueError("неверный состав доказательства")
            _oid(proof["commit"])
            if name == "installation":
                _oid(proof["release_commit"])
                if not _evidence_version(proof["version"]) or not re.fullmatch(r"[0-9a-f]{64}", proof["inventory_sha256"]):
                    raise ValueError("нужны версия и digest проверенного релиза")
            elif name == "update" and (not _evidence_version(proof["from_version"])
                                       or not re.fullmatch(r"[0-9a-f]{64}", proof["from_tree_sha256"])):
                raise ValueError("нужна исходная версия перехода")
    return doc["projects"]


def _oid(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
        raise ValueError("нужен полный SHA коммита")
    return value


def _git_value(root, *args):
    rc, out, _ = git(root, *args)
    if rc:
        raise ValueError("local_git_evidence_unavailable")
    return out


def _committed_file(root, sha, path):
    entry = _git_value(root, "ls-tree", sha, "--", path)
    if not entry.startswith(("100644 blob ", "100755 blob ")):
        raise ValueError("not_a_committed_file")
    # Оба используемых формата малы; проверить размер объекта до чтения.
    if int(_git_value(root, "cat-file", "-s", f"{sha}:{path}")) > MAX_BYTES:
        raise ValueError("oversized_git_evidence")
    return _git_value(root, "show", f"{sha}:{path}")


def _checkpoint(root, sha, pid, anchor, observed_on):
    if _git_value(root, "rev-parse", "--verify", f"{sha}^{{commit}}") != sha:
        raise ValueError("commit_not_exact")
    _git_value(root, "merge-base", "--is-ancestor", sha, "HEAD")
    _git_value(root, "merge-base", "--is-ancestor", anchor, sha)
    if json.loads(_committed_file(root, sha, IDENTITY)) != {"schema_version": 1, "project_id": pid}:
        raise ValueError("identity_history_conflict")
    stamp = datetime.fromisoformat(_git_value(root, "show", "-s", "--format=%cI", sha))
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ValueError("invalid_source_time")
    day = stamp.astimezone(timezone.utc).date().isoformat()
    if day > observed_on:
        raise ValueError("source_newer_than_verification")
    return day


def _historical_inventory(root, sha):
    files = {}
    for entry in _git_value(root, "ls-tree", "-r", "-z", sha, "--", ".ai/managed/").split("\0"):
        if not entry:
            continue
        info, path = entry.split("\t", 1)
        rel = PurePosixPath(path).relative_to(".ai/managed")
        if ("__pycache__" in rel.parts or rel.suffix in (".pyc", ".pyo")
                or rel.name in (".checksums.json", ".provenance.json", ".update-lock", ".gitkeep")):
            continue
        mode, kind, oid = info.split()
        if mode not in ("100644", "100755") or kind != "blob" or len(files) >= EVIDENCE_MAX_FILES:
            raise ValueError("invalid_historical_inventory")
        files[rel.as_posix()] = _oid(oid)
    return files


def _verify_identity(root, pid, doc):
    if Path(_git_value(root, "rev-parse", "--show-toplevel")).resolve() != Path(root).resolve():
        raise ValueError("not_a_git_project_root")
    anchor = doc["identity_commit"]
    _checkpoint(root, anchor, pid, anchor, doc["observed_on"])


def _verified_observation(root, pid, doc, window):
    observed_on, anchor = doc["observed_on"], doc["identity_commit"]
    install = doc.get("installation")
    row = {"registered": {"state": "verified", "source": "local_owner_consent", "observed_on": _today(), "source_at": None},
           "installed": {"state": "unknown", "reason": "release_installation_not_verified"},
           "verified_active": {"state": "unknown", "reason": "product_delivery_not_verified_in_window"},
           "updated": {"state": "unknown", "reason": "transition_not_verified_in_window"}}
    if not install:
        return row
    at = _checkpoint(root, install["commit"], pid, anchor, observed_on)
    version = install["version"]
    historical = _historical_inventory(root, install["commit"])
    if (_committed_file(root, install["commit"], ".ai/managed/VERSION") != version
            or _installation_evidence(root, install, historical)["state"] != "locally_consistent"):
        return row
    row["installed"] = {"state": "verified", "source": "reviewed_release_inventory", "source_at": at,
                        "observed_on": observed_on, "version": version}
    for name, key in (("activity", "verified_active"), ("update", "updated")):
        proof = doc.get(name)
        if not proof:
            continue
        try:
            sha = proof["commit"]
            day = _checkpoint(root, sha, pid, anchor, observed_on)
            if not window["start"] <= day <= window["end"]:
                continue
            if (sha != install["commit"] and _historical_inventory(root, sha) != historical):
                continue
            if name == "activity":
                path = proof["path"]
                rel = PurePosixPath(path)
                if (not rel.parts or rel.is_absolute() or rel.as_posix() != path or ".." in rel.parts
                        or any(part.startswith(".") for part in rel.parts) or "\\" in path or ":" in path
                        or rel.parts[0] in {"tests", "fixtures", "qualification", "newsfragments", "ai-ops", "AGENTS.md"}):
                    continue
                _git_value(root, "merge-base", "--is-ancestor", install["commit"], sha)
                if path not in _git_value(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z",
                                          f"{sha}^1", sha, "--", path).split("\0"):
                    continue
                source = "reviewed_product_delivery_commit"
            else:
                parent = f"{sha}^1"
                if (proof["from_version"] == version
                        or json.loads(_committed_file(root, parent, IDENTITY)) != {"schema_version": 1, "project_id": pid}
                        or _committed_file(root, parent, ".ai/managed/VERSION") != proof["from_version"]
                        or _checksum(_historical_inventory(root, parent)) != proof["from_tree_sha256"]):
                    continue
                source = "reviewed_version_transition_commit"
            row[key] = {"state": "verified", "source": source, "source_at": day, "observed_on": observed_on}
            if name == "update":
                row[key].update(from_version=proof["from_version"], to_version=version)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            continue
    return row


def _is_parent(root):
    return all((Path(root) / marker).is_file() for marker in
               ("VERSION", "installer/ai_ops.py", "manifest/ai-ops-manifest.yaml"))


def _verified_report(candidates, verification, revoked, window, inspected, imports, parent_seen):
    names = ("registered", "installed", "verified_active", "updated")
    counts = {rel: dict.fromkeys(names, 0) for rel in RELATIONSHIPS}
    rows, excluded, quarantine = [], {"parent": int(parent_seen), "fixture": 0}, []
    for pid, copies in sorted(candidates.items()):
        approved = verification.get(pid, {})
        if approved.get("kind") == "parent":
            excluded["parent"] = 1
            continue
        if approved.get("kind") == "fixture":
            excluded["fixture"] += 1
            continue
        copies = [(p, r, d) for p, r, d in copies if d["consent"] == "granted"
                  and (pid, d["consent_id"]) not in revoked]
        if not copies:
            continue
        relations = {r for _, r, _ in copies if r != "unknown"}
        relation = approved.get("relationship", "unknown")
        if len(relations | ({relation} - {"unknown"})) > 1:
            quarantine.append({"project_id": pid, "reason": "relationship_conflict"})
            continue
        if not approved:
            quarantine.append({"project_id": pid, "reason": "independent_project_verification_missing"})
            continue
        try:
            for project, _, _ in copies:
                _verify_identity(project, pid, approved)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            quarantine.append({"project_id": pid, "reason": "identity_or_evidence_conflict"})
            continue
        copies = [(p, r, d) for p, r, d in copies if d["consent_id"] in approved["consent_ids"]]
        if not copies:
            quarantine.append({"project_id": pid, "reason": "consent_not_bound_to_review"})
            continue
        variants = []
        for project, _, snapshot_doc in copies:
            try:
                row = _verified_observation(project, pid, approved, window)
                state = _state(project)
                if state and (state["project_id"], state["consent_id"], state["consent"]) == (
                        pid, snapshot_doc["consent_id"], "granted"):
                    variants.append(row)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                continue
        if len(variants) != len(copies) or any(row != variants[0] for row in variants):
            quarantine.append({"project_id": pid, "reason": "identity_or_evidence_conflict"})
            continue
        row = variants[0]
        for name in names:
            counts[relation][name] += int(row[name]["state"] == "verified")
        rows.append({"project_id": pid, "relationship": relation, "basis": "independent_operator_review", **row})
    return {"window": window, "deduplication": "committed_project_uuid_and_reviewed_identity_history",
            "lower_bounds": counts, "projects": rows, "quarantine": quarantine, "excluded": excluded,
            "coverage": {"local_checkouts_inspected": inspected, "local_project_ids_observed": len(candidates),
                         "reviewed_product_projects": len(rows), "voluntary_imports_unverified": imports,
                         "public_index": "not_observed", "offline_or_unregistered": "unknown"},
            "global_exact_total": None, "global_exact_total_state": "unknown"}
