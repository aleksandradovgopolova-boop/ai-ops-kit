"""Алиас: engine.parallel_planner -> плоский модуль parallel_planner (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import parallel_planner as _target

sys.modules[__name__] = _target
