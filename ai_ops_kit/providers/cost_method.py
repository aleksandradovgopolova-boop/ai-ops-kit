"""Алиас: providers.cost_method -> плоский модуль cost_method (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import cost_method as _target

sys.modules[__name__] = _target
