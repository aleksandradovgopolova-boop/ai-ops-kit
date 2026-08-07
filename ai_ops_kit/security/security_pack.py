"""Алиас: security.security_pack -> плоский модуль security_pack (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import security_pack as _target

sys.modules[__name__] = _target
