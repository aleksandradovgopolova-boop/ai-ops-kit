"""Алиас: security.security_enforcement -> плоский модуль security_enforcement (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import security_enforcement as _target

sys.modules[__name__] = _target
