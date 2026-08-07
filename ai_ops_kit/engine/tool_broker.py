"""Алиас: engine.tool_broker -> плоский модуль tool_broker (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import tool_broker as _target

sys.modules[__name__] = _target
