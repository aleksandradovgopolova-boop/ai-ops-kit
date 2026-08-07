"""Алиас: engine.parallel_live -> плоский модуль parallel_live (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import parallel_live as _target

sys.modules[__name__] = _target
