"""Алиас: engops.engineering_advisor -> плоский модуль engineering_advisor (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import engineering_advisor as _target

sys.modules[__name__] = _target
