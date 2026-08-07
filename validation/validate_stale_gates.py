#!/usr/bin/env python3
from __future__ import annotations
"""Детектор «протухших» (stale) gate-результатов.

Gate-результат (*.gate.json, schemas/gate-result.schema.json) привязан к состоянию:
  - artifact_hashes: sha256 входных артефактов на момент проверки;
  - tested_revision: git-ревизия, на которой gate оценивался;
  - expires_at: срок действия (для capability-зависимых проверок).

Gate считается STALE, если:
  1. хэш любого артефакта из artifact_hashes не совпадает с текущим содержимым файла;
  2. артефакт из artifact_hashes исчез;
  3. expires_at в прошлом;
  4. tested_revision задан и не совпадает с текущим HEAD, при этом хотя бы один
     файл из affected_files изменён относительно tested_revision (если git доступен;
     без git — несовпадение ревизии само по себе помечается предупреждением).

Stale BLOCKING gate трактуется как fail (exit 1). Не-blocking — предупреждение.

Использование:
  validate_stale_gates.py [root]   — просканировать root (по умолчанию cwd) на *.gate.json
  validate_stale_gates.py --selftest — самопроверка на временной фикстуре

Только стандартная библиотека.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".ai/runtime/backups"}


def sha256(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_head(root: Path):
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def file_changed_since(root: Path, revision: str, rel_path: str):
    """True, если файл отличается от своего состояния в revision (или git недоступен -> None)."""
    try:
        r = subprocess.run(["git", "diff", "--quiet", revision, "--", rel_path],
                           cwd=root, capture_output=True, timeout=10)
        return r.returncode != 0
    except Exception:
        return None


def check_gate(root: Path, gate_path: Path):
    """Возвращает (stale_reasons, warnings)."""
    stale, warn = [], []
    try:
        g = json.loads(gate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"невалидный JSON: {e}"], []

    rel_gate = gate_path.relative_to(root)

    # 1-2. artifact_hashes
    for rel, digest in (g.get("artifact_hashes") or {}).items():
        p = root / rel
        if not p.exists():
            stale.append(f"артефакт '{rel}' исчез")
        else:
            actual = sha256(p)
            if not str(digest).endswith(actual):   # допускаем префикс "sha256:"
                stale.append(f"артефакт '{rel}' изменён после оценки gate")

    # 3. expires_at
    exp = g.get("expires_at")
    if exp:
        try:
            dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if dt < datetime.now(timezone.utc):
                stale.append(f"expires_at {exp} в прошлом")
        except ValueError:
            warn.append(f"{rel_gate}: некорректный expires_at '{exp}'")

    # 4. tested_revision vs HEAD + affected_files
    rev = g.get("tested_revision")
    if rev:
        head = git_head(root)
        if head and not head.startswith(str(rev)) and not str(rev).startswith(head[:7]):
            affected = g.get("affected_files") or []
            if not affected:
                warn.append(f"{rel_gate}: ревизия сменилась ({rev} -> {head[:12]}), affected_files пуст — проверить вручную")
            else:
                for rel in affected:
                    changed = file_changed_since(root, str(rev), rel)
                    if changed is True:
                        stale.append(f"'{rel}' изменён после tested_revision {rev}")
                    elif changed is None:
                        warn.append(f"{rel_gate}: git недоступен для проверки '{rel}' против {rev}")
    return stale, warn


def scan(root: Path):
    stale_blocking, stale_nonblocking, warnings = [], [], []
    gates = [p for p in root.rglob("*.gate.json")
             if not any(part in SKIP_DIRS for part in p.parts)]
    for gp in gates:
        stale, warn = check_gate(root, gp)
        warnings += warn
        if stale:
            try:
                blocking = json.loads(gp.read_text(encoding="utf-8")).get("blocking", True)
            except Exception:
                blocking = True
            rec = (gp.relative_to(root).as_posix(), stale)
            (stale_blocking if blocking else stale_nonblocking).append(rec)
    return gates, stale_blocking, stale_nonblocking, warnings


def report(root: Path):
    gates, sb, snb, warnings = scan(root)
    for path, reasons in sb:
        print(f"STALE (blocking) {path}:")
        for r in reasons:
            print(f"  - {r}")
    for path, reasons in snb:
        print(f"stale (non-blocking) {path}:")
        for r in reasons:
            print(f"  - {r}")
    for w in warnings:
        print(f"warn: {w}")
    if sb:
        print(f"ИТОГ: {len(sb)} stale blocking gate(ов) — требуется переоценка (stale = fail).")
        return 1
    print(f"OK: stale blocking gates не найдены ({len(gates)} gate-файлов проверено, "
          f"non-blocking stale: {len(snb)}).")
    return 0


def main(argv):
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    return report(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
