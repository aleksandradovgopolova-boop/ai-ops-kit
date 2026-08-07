"""Алиас: security.security_scan -> плоский модуль security_scan (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import security_scan as _target

sys.modules[__name__] = _target
