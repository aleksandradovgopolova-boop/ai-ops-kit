"""Алиас: gates.preflight -> плоский модуль preflight (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import preflight as _target

sys.modules[__name__] = _target
