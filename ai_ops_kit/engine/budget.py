"""Алиас: engine.budget -> плоский модуль budget (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import budget as _target

sys.modules[__name__] = _target
