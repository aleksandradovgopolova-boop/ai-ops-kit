"""WorkItem slug contract and checked paths shared by artifact writers."""
from __future__ import annotations

import os
import re
from pathlib import Path

WORKITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate_workitem_id(wid: object) -> str:
    """Reject path separators, traversal and non-slug identifiers before any I/O."""
    if not isinstance(wid, str) or not WORKITEM_ID_RE.fullmatch(wid):
        raise ValueError(
            f"недопустимый workitem_id {wid!r}: разрешён slug {WORKITEM_ID_RE.pattern} "
            "(нижний регистр, [a-z0-9._-], без '/', '\\', '..', 1..64 символа)")
    if wid.startswith(".") or ".." in wid:
        raise ValueError(f"недопустимый workitem_id {wid!r}: '.' в начале или '..' запрещены")
    return wid


def artifact_path(features_dir: str | Path, wid: object, filename: str) -> Path:
    """Reject existing escaping links; concurrent hostile link replacement is not isolated."""
    features = Path(features_dir)
    path = features / validate_workitem_id(wid) / filename
    try:
        within = path.resolve().is_relative_to(features.parent.resolve())
    except (OSError, RuntimeError) as exc:
        raise ValueError("путь артефакта нельзя проверить в пределах проекта") from exc
    if not within:
        raise ValueError("путь артефакта выходит за пределы проекта")
    return path


def validate_feature_links(features_dir: str | Path, wid: object) -> None:
    """Check existing artifact links before CLI processes can write sibling outputs."""
    directory = artifact_path(features_dir, wid, ".")
    if not directory.exists():
        return

    def refuse_scan(exc: OSError) -> None:
        raise ValueError("пути фичи нельзя проверить в пределах проекта") from exc

    for parent, dirs, files in os.walk(directory, onerror=refuse_scan, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(parent) / name
            if path.is_symlink():
                artifact_path(features_dir, wid, path.relative_to(directory).as_posix())
