"""Алиас: engine.tool_loop -> плоский модуль tool_loop (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import tool_loop as _target

sys.modules[__name__] = _target
