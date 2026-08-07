"""Алиас: engine.run_plan -> плоский модуль run_plan (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import run_plan as _target

sys.modules[__name__] = _target
