"""Алиас: shared.generate_runtime -> плоский модуль generate_runtime (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import generate_runtime as _target

sys.modules[__name__] = _target
