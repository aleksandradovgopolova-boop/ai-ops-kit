"""Алиас: engine.parallel_executor -> плоский модуль parallel_executor (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import parallel_executor as _target

sys.modules[__name__] = _target
