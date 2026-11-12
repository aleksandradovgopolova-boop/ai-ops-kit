"""Ограниченное чтение и проверка managed-байтов для добровольного учёта."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

EVIDENCE_META_BYTES = 1024 * 1024
EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
EVIDENCE_TOTAL_BYTES = 64 * 1024 * 1024
EVIDENCE_MAX_FILES = 4096


def _checksum(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

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


def _managed_integrity(root, manifest, historical=None):
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
    if actual != set(files) or (historical is not None and actual != historical.keys()):
        raise ValueError("incomplete_or_drifted_inventory")
    for rel, expected in files.items():
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("invalid_checksum")
        path = _evidence_path(root, f".ai/managed/{rel}", EVIDENCE_FILE_BYTES)
        if total + path.stat().st_size > EVIDENCE_TOTAL_BYTES:
            raise ValueError("managed_bytes_limit")
        digest = hashlib.sha256()
        git_digest = None
        if historical is not None:
            oid = historical[rel]
            git_digest = hashlib.new("sha1" if len(oid) == 40 else "sha256", usedforsecurity=False)
            git_digest.update(f"blob {path.stat().st_size}\0".encode())
        read_bytes = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                read_bytes += len(chunk)
                total += len(chunk)
                if read_bytes > EVIDENCE_FILE_BYTES or total > EVIDENCE_TOTAL_BYTES:
                    raise ValueError("managed_file_grew_over_limit")
                digest.update(chunk)
                if git_digest is not None:
                    git_digest.update(chunk)
        if git_digest is not None and git_digest.hexdigest() != historical[rel]:
            raise ValueError("historical_inventory_does_not_match_release_bytes")
        if digest.hexdigest() != expected:
            raise ValueError("managed_content_drift")
    return len(files)


def _installation_evidence(root, approved=None, historical=None):
    try:
        version = _evidence_bytes(root, ".ai/managed/VERSION", 256).decode("utf-8").strip()
        prov = _evidence_json(root, ".ai/managed/.provenance.json")
        if (not _evidence_version(version) or type(prov.get("schema_version")) is not int
                or prov["schema_version"] != 1 or prov.get("package") != "ai-first-system"
                or prov.get("installed_version") != version or prov.get("managed_root") != ".ai/managed"
                or prov.get("checksums_file") != ".checksums.json"):
            raise ValueError("inconsistent_provenance")
        manifest = _evidence_json(root, ".ai/managed/.checksums.json")
        if approved is not None:
            source = prov.get("source_identity")
            if (not isinstance(source, dict) or source.get("sha") not in
                    (approved["release_commit"], approved["release_commit"][:12])
                    or source.get("tag") != f"v{version}" or source.get("is_release") is not True
                    or approved["version"] != version
                    or _checksum(manifest.get("files")) != approved["inventory_sha256"]):
                raise ValueError("release_inventory_not_corroborated")
        count = _managed_integrity(root, manifest, historical)
        return {"state": "locally_consistent", "version": version, "checked_files": count,
                "source_authentication": "unknown", "source_at": None,
                "reason": "checksums_do_not_authenticate_source"}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return {"state": "unknown", "reason": "installation_evidence_missing_invalid_or_drifted",
                "managed_drift": "detected" if str(exc) in
                {"incomplete_or_drifted_inventory", "managed_content_drift"} else "unknown"}


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
