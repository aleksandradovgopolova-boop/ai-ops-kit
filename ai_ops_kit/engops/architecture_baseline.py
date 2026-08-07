"""Алиас: engops.architecture_baseline -> плоский модуль architecture_baseline (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import architecture_baseline as _target

sys.modules[__name__] = _target
