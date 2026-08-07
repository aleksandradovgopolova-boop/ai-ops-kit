"""Алиас: lifecycle.merge_memory -> плоский модуль merge_memory (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import merge_memory as _target

sys.modules[__name__] = _target
