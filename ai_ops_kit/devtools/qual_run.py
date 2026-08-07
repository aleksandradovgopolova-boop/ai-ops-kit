"""Алиас: devtools.qual_run -> плоский модуль qual_run (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import qual_run as _target

sys.modules[__name__] = _target
