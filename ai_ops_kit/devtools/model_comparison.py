"""Алиас: devtools.model_comparison -> плоский модуль model_comparison (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import model_comparison as _target

sys.modules[__name__] = _target
