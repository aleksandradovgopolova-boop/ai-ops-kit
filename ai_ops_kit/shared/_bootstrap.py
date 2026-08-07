"""Алиас: shared._bootstrap -> плоский модуль _bootstrap (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import _bootstrap as _target

sys.modules[__name__] = _target
