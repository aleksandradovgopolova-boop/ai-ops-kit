"""Алиас: gates.gate_result_v2 -> плоский модуль gate_result_v2 (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import gate_result_v2 as _target

sys.modules[__name__] = _target
