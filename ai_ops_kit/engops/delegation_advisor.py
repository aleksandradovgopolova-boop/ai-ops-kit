"""Алиас: engops.delegation_advisor -> плоский модуль delegation_advisor (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import delegation_advisor as _target

sys.modules[__name__] = _target
