"""Алиас: ui.ui_readiness -> плоский модуль ui_readiness (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import ui_readiness as _target

sys.modules[__name__] = _target
