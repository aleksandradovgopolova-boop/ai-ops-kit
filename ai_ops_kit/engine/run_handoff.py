"""Алиас: engine.run_handoff -> плоский модуль run_handoff (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import run_handoff as _target

sys.modules[__name__] = _target
