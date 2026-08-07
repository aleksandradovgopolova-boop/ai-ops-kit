"""Алиас: gates.approvals -> плоский модуль approvals (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import approvals as _target

sys.modules[__name__] = _target
