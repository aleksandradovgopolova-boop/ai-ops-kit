"""Алиас: engine.worktree -> плоский модуль worktree (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import worktree as _target

sys.modules[__name__] = _target
