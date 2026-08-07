"""Алиас: gates.gate_runtime -> плоский модуль gate_runtime (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import gate_runtime as _target

sys.modules[__name__] = _target
