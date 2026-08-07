"""Алиас: devtools.promotion_qual -> плоский модуль promotion_qual (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import promotion_qual as _target

sys.modules[__name__] = _target
