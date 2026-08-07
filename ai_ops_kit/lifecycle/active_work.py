"""Алиас: lifecycle.active_work -> плоский модуль active_work (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import active_work as _target

sys.modules[__name__] = _target
