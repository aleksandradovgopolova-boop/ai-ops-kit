"""Private, bounded IO and cooperative migration barrier; no workflow execution."""
from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

AREA = ".ai/runtime/sessions/.migrations"
LIMIT = 128 * 1024 * 1024


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


@contextlib.contextmanager
def parent(path, *, create=False):
    """Keep directory handles, rejecting symlinks in every path component."""
    path = Path(os.path.abspath(path))
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    if not stat.S_ISDIR(os.stat(component, dir_fd=fd, follow_symlinks=False).st_mode):
                        raise ValueError("migration parent is not a real directory") from None
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        yield fd, path.name
    finally:
        os.close(fd)


def read(path, *, atomic=False):
    with parent(path) as (directory, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            linked = info.st_nlink != 1
            if linked and atomic and info.st_nlink == 2:
                # SIGKILL between link(commit) and unlink(temp) leaves two private names.
                # Only our exact create prefix and the same inode qualify; no links are removed.
                twins = [entry for entry in os.scandir(directory) if entry.name.startswith(".creating-" + name + "-")
                         and not entry.is_symlink() and entry.inode() == info.st_ino]
                linked = len(twins) != 1
            if not stat.S_ISREG(info.st_mode) or linked or info.st_size > LIMIT:
                raise ValueError("migration requires bounded regular files without hard links")
            with os.fdopen(os.dup(fd), "rb") as handle:
                data = handle.read(LIMIT + 1)
            after = os.fstat(fd)
            if len(data) > LIMIT or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise ValueError("file changed during migration read")
            return {"data": base64.b64encode(data).decode(), "mode": stat.S_IMODE(info.st_mode)}
        finally:
            os.close(fd)


def raw(entry):
    return base64.b64decode(entry["data"], validate=True)


def document(path, *, atomic=False):
    return json.loads(raw(read(path, atomic=atomic)))


def replace(path, entry, expected, *, staging=None, atomic=False):
    """CAS with durable rename; failure after rename is deliberately an unknown outcome."""
    if read(path, atomic=atomic) != expected:
        raise ValueError("migration CAS conflict; preserved concurrent state")
    staging = Path(staging) if staging is not None else Path(path).parent
    with parent(path) as (directory, name), parent(staging / "placeholder", create=True) as (stage, _):
        temporary = ".migration-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=stage)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw(entry))
                os.fchmod(handle.fileno(), entry["mode"])
                handle.flush()
                os.fsync(handle.fileno())
            if read(path, atomic=atomic) != expected:
                raise ValueError("migration CAS conflict before rename")
            os.replace(temporary, name, src_dir_fd=stage, dst_dir_fd=directory)
            os.fsync(directory)
            os.fsync(stage)
        finally:
            try:
                os.unlink(temporary, dir_fd=stage)
            except FileNotFoundError:
                # rename consumed our staging name; the destination durability was checked above.
                os.fsync(stage)


def create(path, value):
    """Create-only private evidence. Never truncate a prior snapshot or plan."""
    data = encoded(value)
    if len(data) > LIMIT:
        raise ValueError("migration evidence exceeds 128 MiB")
    with parent(path, create=True) as (directory, name):
        temporary = ".creating-" + name + "-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # link is create-only: neither partial JSON nor overwriting existing evidence.
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                # The successful create path already unlinked this private temporary name.
                os.fsync(directory)
    return sha(data)


def update(path, value):
    replace(path, {"data": base64.b64encode(encoded(value)).decode(), "mode": 0o600}, read(path, atomic=True), atomic=True)


def inventory(root, prefixes, *, exclude=()):
    files = {}
    total = 0
    for prefix in prefixes:
        base = Path(root) / prefix
        if not base.exists() and not base.is_symlink():
            continue
        paths = [base]
        if base.is_dir() and not base.is_symlink():
            paths = []
            for directory, dirs, names in os.walk(base, followlinks=False):
                dirs[:] = [name for name in dirs if (Path(directory) / name).relative_to(root).as_posix() not in (AREA, *exclude)]
                for name in dirs:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError("symlink directory in migration inventory")
                paths.extend(Path(directory) / name for name in names)
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if relative in exclude:
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            # Locks carry no session data; creation during lock acquisition is expected.
            if relative.startswith(".ai/runtime/sessions/") and path.name in ("preparation.lock", "requests.lock"):
                continue
            entry = read(path)
            total += len(entry["data"])
            if total > LIMIT or len(files) >= 50000:
                raise ValueError("migration inventory exceeds bounded budget")
            files[relative] = entry
    return dict(sorted(files.items()))


def incomplete(root):
    from ai_ops_kit.lifecycle import project_session
    with project_session.reading():
        _incomplete(root)


def _incomplete(root):
    area = Path(root) / AREA
    if area.is_symlink():
        raise ValueError("symlink migration journal")
    for transaction in area.iterdir() if area.exists() else ():
        if transaction.name == "writer.lock":
            continue
        path = transaction / "journal.json"
        journal = document(path, atomic=True)
        if journal.get("phase") not in ("committed", "rolled_back"):
            raise ValueError("incomplete state migration; inspect and explicitly roll back before continuing")


@contextlib.contextmanager
def barrier(root, *, exclusive=False, recovery=False):
    import fcntl
    path = Path(root) / AREA / "writer.lock"
    with parent(path, create=True) as (directory, name):
        fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe migration writer lock")
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("state migration/writer busy; no request was restarted") from None
            if not recovery:
                incomplete(root)
            yield
        finally:
            os.close(fd)


def guarded(function):
    @functools.wraps(function)
    def call(root, *args, **kwargs):
        from ai_ops_kit.lifecycle import project_session
        root = project_session.project_root(root)
        with barrier(root):
            return function(root, *args, **kwargs)
    return call
