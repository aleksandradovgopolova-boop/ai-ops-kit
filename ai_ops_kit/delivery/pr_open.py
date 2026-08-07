"""Алиас: delivery.pr_open -> плоский модуль pr_open (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import pr_open as _target

sys.modules[__name__] = _target
