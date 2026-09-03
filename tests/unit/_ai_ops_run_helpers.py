"""Общие хелперы для разрезанных тестов ai_ops_run (не собирается pytest)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import ai_ops_run


def _git_init_commit(root):
    """Минимальный git-репозиторий с одним коммитом (как в монолите)."""
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)


# Сигналы planned-пути из монолита: PRODUCT + UI + аналитика -> треки VISUAL/ANALYTICS.
