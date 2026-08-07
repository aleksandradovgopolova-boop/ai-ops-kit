"""Алиас: devtools.kit_observability -> плоский модуль kit_observability (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import kit_observability as _target

sys.modules[__name__] = _target
