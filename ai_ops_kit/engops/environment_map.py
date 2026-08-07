"""Алиас: engops.environment_map -> плоский модуль environment_map (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import environment_map as _target

sys.modules[__name__] = _target
