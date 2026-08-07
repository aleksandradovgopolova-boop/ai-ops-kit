"""Алиас: engine.ai_ops_run -> плоский модуль ai_ops_run (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import ai_ops_run as _target

sys.modules[__name__] = _target
