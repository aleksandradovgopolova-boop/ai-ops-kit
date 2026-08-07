"""Алиас: gates.gate_executor -> плоский модуль gate_executor (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import gate_executor as _target

sys.modules[__name__] = _target
