"""Алиас: engops.branch_policy -> плоский модуль branch_policy (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import branch_policy as _target

sys.modules[__name__] = _target
