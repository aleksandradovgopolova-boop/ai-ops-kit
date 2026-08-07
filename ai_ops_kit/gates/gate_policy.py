"""Алиас: gates.gate_policy -> плоский модуль gate_policy (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import gate_policy as _target

sys.modules[__name__] = _target
