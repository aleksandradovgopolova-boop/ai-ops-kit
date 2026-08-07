"""Алиас: lifecycle.product_health -> плоский модуль product_health (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import product_health as _target

sys.modules[__name__] = _target
