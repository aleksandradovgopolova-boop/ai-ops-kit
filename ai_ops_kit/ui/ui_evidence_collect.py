"""Алиас: ui.ui_evidence_collect -> плоский модуль ui_evidence_collect (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import ui_evidence_collect as _target

sys.modules[__name__] = _target
