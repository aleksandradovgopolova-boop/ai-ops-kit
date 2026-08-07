"""Алиас: lifecycle.effect_metrics -> плоский модуль effect_metrics (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import effect_metrics as _target

sys.modules[__name__] = _target
