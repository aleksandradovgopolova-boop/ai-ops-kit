"""Алиас: lifecycle.lifecycle_store -> плоский модуль lifecycle_store (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import lifecycle_store as _target

sys.modules[__name__] = _target
