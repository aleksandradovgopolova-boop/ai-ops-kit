"""Алиас: engine.atomic_planner -> плоский модуль atomic_planner (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import atomic_planner as _target

sys.modules[__name__] = _target
