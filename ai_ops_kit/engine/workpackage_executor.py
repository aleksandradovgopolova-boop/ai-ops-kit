"""Алиас: engine.workpackage_executor -> плоский модуль workpackage_executor (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import workpackage_executor as _target

sys.modules[__name__] = _target
