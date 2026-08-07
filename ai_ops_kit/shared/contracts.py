"""Алиас: shared.contracts -> плоский модуль contracts (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import contracts as _target

sys.modules[__name__] = _target
